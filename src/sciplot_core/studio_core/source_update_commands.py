"""Freeze whole-source revisions and publish their complete generation once."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation, SourceTreeRead, InputRead
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store, query_for_apply, whole_memberships
from sciplot_core.project_commands.resources import PreparedFile
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.io import read_file, sha
from sciplot_core.studio_core.source_update_files import project_inventory, relocate_metadata


def selected_worksheet(request: dict[str, Any], worksheet: str | None) -> str | None:
    if worksheet is not None:
        return worksheet.strip() or None
    old = {str(c["sheet"]) for c in request.get("column_confirmations", [])
           if c.get("sheet_selected") is True and c.get("sheet")}
    if len(old) > 1:
        raise ValueError("Select one current worksheet explicitly before updating this project.")
    return next(iter(old), None)


def lookup_source_preview(project: Path, source: Path, *, worksheet: str | None,
                          mapping_request: dict[str, Any] | None,
                          annotation_decisions: list[dict[str, Any]] | None,
                          ) -> tuple[FileProjectStore, dict[str, Any], dict[str, Any]] | None:
    """Query an exact saved intent before admitting any new preparation work."""
    from sciplot_core.foundation.canonical_paths import canonical_path
    from sciplot_core.project_host_factory import _admitted_request
    from sciplot_core.project_manifest_locations import admitted_project_generation
    from sciplot_core.project_store import ProjectConflict

    if not (project / ".sciplot_store/head.json").is_file():
        return None
    source = canonical_path(source)
    with admitted_project_generation(project) as (primary, _io, current):
        request = _admitted_request(project)
        supplied = {"source": str(source), "worksheet": selected_worksheet(request, worksheet),
                    "mapping_request": mapping_request, "annotation_decisions": annotation_decisions or []}
        candidates = []
        for prior in primary.commands():
            metadata = prior.get("metadata", {})
            intent = metadata.get("request", {})
            if (metadata.get("kind") != "source_update" or not isinstance(intent, dict)
                    or any(intent.get(key) != value for key, value in supplied.items())):
                continue
            command = ProjectCommand.from_payload(metadata)
            if (command.key != prior["command_id"] or command.project_id != current["project_id"]
                    or prior["project_id"] != command.project_id or command.command_digest != prior["command_digest"]):
                raise ProjectConflict("The saved source preview has inconsistent command identity.")
            candidates.append((command, intent))
    if not candidates:
        return None
    repository = project_store(project)
    snapshot = repository.snapshot()
    from sciplot_core.output_contract import requested_delivery_root
    from sciplot_core.studio_core.source_update_review import payload_hash
    from sciplot_core.studio_core.source_update_state import _delivery_inventory
    from sciplot_core.studio_core.source_update_staging import source_mapping_required

    project_hash = payload_hash(project_inventory(project))
    delivery_hash = payload_hash(_delivery_inventory(requested_delivery_root({"request": request}, run_output=project)))
    current_candidates = [(command, intent) for command, intent in candidates
        if source_review_binding(repository, snapshot, intent)[1:] == (intent, command.key)
        and intent.get("project_sha256") == project_hash and intent.get("delivery_sha256") == delivery_hash]
    # Unknown execution cannot be resolved by rereading data or rerunning a
    # callback. Coarse metadata alone is never called an exact input version.
    for _command, stored in current_candidates:
        prior_source_preview(repository, snapshot, stored)
    if not source_mapping_required(request, mapping_request) or not current_candidates:
        return None  # NEW admission must precede observing its actual version.
    if len(current_candidates) != 1:
        raise ProjectConflict("Multiple stored source versions require an exact saved decision or fresh source mapping.")
    _command, intent = current_candidates[0]
    record = verified_source_preview(repository, snapshot, intent)
    assert record is not None
    return repository, snapshot, record


def verified_source_preview(repository: FileProjectStore, snapshot: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any] | None:
    """Consume one exact key, using the original saved input/read witnesses."""
    from sciplot_core.project_store import ProjectConflict

    project, source = repository.root, Path(intent["source"])
    record = prior_source_preview(repository, snapshot, intent)
    if record is None:
        return None
    command = ProjectCommand.from_payload(record["metadata"])
    if (command.kind != "source_update" or json.loads(command.request_json) != intent or command.key != record["command_id"]
            or command.project_id != snapshot["project_id"] or command.command_digest != record["command_digest"]):
        raise ProjectConflict("The saved source preview has inconsistent command identity.")
    review = record.get("review")
    if not isinstance(review, dict) or source_review_binding(repository, snapshot, review)[1:] != (intent, command.key):
        raise ProjectConflict("The frozen source review differs from its exact normalized command.")
    if snapshot.get("outside_changes"):
        raise ProjectConflict("The saved source preview's current project read witness changed.")
    from sciplot_core.project_store import input_reads, source_trees
    from sciplot_core.project_store.runtime import project_runtime
    from sciplot_core.studio_core.source_update_sources import incoming_scope
    from sciplot_core.studio_core.source_update_state import _check_external_state
    from sciplot_core.studio_core.source_update_review import payload_hash

    with repository._locked() as (io, current):
        if source_review_binding(repository, current, review)[1:] != (intent, command.key):
            raise ProjectConflict("The saved source preview's current project read witness changed.")
        if not any(tree.locator == str(source) for tree in command.source_trees):
            raise ProjectConflict("The saved source preview has no exact incoming source-tree declaration.")
        source_trees.require(io, current, record)
        input_reads.require(io, current, record, observed={})
        with project_runtime(repository, generation=current["generation"]), incoming_scope(repository, current, source, review["source_files"]):
            if payload_hash(project_inventory(project)) != review["project_sha256"]:
                raise ProjectConflict("The saved source preview's current project read witness changed.")
            _check_external_state(project, source, review)
    return record


def source_mutation(project: Path, candidate: Path, review: dict[str, Any], *,
                    relocate_companion: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
                    expected: dict[str, str] | None = None,
                    store: FileProjectStore | None = None, logical_paths_bound: bool = False) -> tuple[dict[str, bytes | Path | PreparedFile | None], dict[str, bytes | Path]]:
    names = sorted(path.name for path in candidate.iterdir()
                   if path.name not in {"runs", "delivery", ".sciplot_store", ".sciplot_resources"})
    before = expected if expected is not None else project_inventory(project)
    required = {"plot_request.json", "studio"} | {name for name in ("raw", "source")
        if any(member == name or member.startswith(name + "/") for member in before)}
    if not required.issubset(names):
        raise ValueError("Prepared source update is missing required active project parts")
    for path in ([] if logical_paths_bound else [*candidate.glob("*.json"), *(candidate / "studio").rglob("*.json")]):
        value = json.loads(path.read_text())
        relocated = relocate_metadata(value, candidate, project)
        if isinstance(value, dict) and value.get("native_annotations"):
            if relocate_companion is None:
                raise ValueError("Annotated source installation requires reviewed provenance relocation")
            relocated = relocate_companion(value, relocated)
        path.write_text(json.dumps(relocated, ensure_ascii=False, indent=2))
    if (candidate / "Open_in_Veusz.command").exists():
        from sciplot_core.studio_core.launchers import _write_veusz_launcher

        _write_veusz_launcher(candidate, project / "studio/document.vsz")
    writes: dict[str, bytes | Path | PreparedFile | None] = {}
    artifacts: dict[str, bytes | Path] = {"review.json": json.dumps(review, ensure_ascii=False, allow_nan=False).encode()}
    for logical in before:
        if logical.split("/", 1)[0] in names:
            writes[logical] = None
            artifacts["before/" + logical] = (project / logical).read_bytes()
    for path in sorted(candidate.rglob("*")):
        if path.is_file() and path.relative_to(candidate).parts[0] in names:
            writes[path.relative_to(candidate).as_posix()] = path
    if store is not None and "snapshot" in store.locations and "intake_manifest.json" in writes:
        from sciplot_core.project_manifest import stage_intake_project_manifest

        manifest_source = writes["intake_manifest.json"]
        assert isinstance(manifest_source, Path)
        payload = json.loads(manifest_source.read_text())
        writes.update(stage_intake_project_manifest(project, payload, store=store, project_writes=writes))
    return writes, artifacts


def _public_review(project: Path, record: dict[str, Any]) -> dict[str, Any]:
    return {**record["review"], "version": 2, "project": str(project),
            "command_key": record["command_id"], "decision_id": record["decision_id"]}


def source_review_binding(repository: FileProjectStore, snapshot: dict[str, Any], review: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    binding = {"project_id": snapshot["project_id"], "generation": snapshot["generation"],
               "files": {name: value["sha256"] for name, value in snapshot["files"].items()},
               "read_memberships": whole_memberships(repository, snapshot)}
    intent = {name: review.get(name) for name in ("source", "source_kind", "source_tree_sha256", "source_files", "worksheet",
        "mapping_request", "annotation_decisions", "project_sha256", "delivery_sha256")}
    intent["read_witness"] = canonical_json_sha256({"files": snapshot["files"], "memberships": binding["read_memberships"]})
    key = canonical_json_sha256({"kind": "source_update", "project_id": binding["project_id"], "intent": intent})
    return binding, intent, key


def prior_source_preview(repository: FileProjectStore, snapshot: dict[str, Any], review: dict[str, Any]) -> dict[str, Any] | None:
    from sciplot_core.project_commands import ProjectCommandUnknown

    _binding, _intent, key = source_review_binding(repository, snapshot, review)
    record = ProjectCommands(repository).query(key)
    if record is None:
        return None
    if record["phase"] not in {"needs_review", "accepted", "complete"}:
        raise ProjectCommandUnknown()
    return record


def stage_source_update(project: Path, candidate: Path, review: dict[str, Any], *,
                        relocate_companion: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
                        prepared_sources: tuple[PreparedSource, ...] = (), logical_paths_bound: bool = False,
                        before_snapshot: dict[str, Any] | None = None,
                        input_reads: tuple[InputRead, ...] = ()) -> dict[str, Any]:
    repository = project_store(project, with_snapshot=True)
    snapshot = before_snapshot if before_snapshot is not None else repository.snapshot(import_legacy=True)
    before = project_inventory(project)
    if canonical_json_sha256(before) != review["project_sha256"]:
        # Historical payload_hash uses the same canonical JSON, without whitespace.
        from sciplot_core.studio_core.source_update_review import payload_hash

        if payload_hash(before) != review["project_sha256"]:
            raise ValueError("Project changed while its source candidate was prepared")
    (candidate / "source_update.json").write_text(json.dumps(review, ensure_ascii=False, indent=2))
    writes, artifacts = source_mutation(project, candidate, review, relocate_companion=relocate_companion, expected=before,
                                       store=repository, logical_paths_bound=logical_paths_bound)
    for item in input_reads:
        if item.resource not in writes:
            continue
        value = writes[item.resource]
        if isinstance(value, Path):
            fd = os.open(value.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                data, mode = read_file(fd, value.name)
            finally:
                os.close(fd)
        elif isinstance(value, PreparedFile):
            data, mode = value.data, value.mode
        else:
            data, mode = value or b"", 0o644
        old = snapshot["files"].get(item.resource)
        if old is None or value is None or sha(data) != item.sha256 or mode != old["mode"]:
            raise ValueError("A source candidate changed immutable mapping metadata instead of preserving its exact preimage")
        del writes[item.resource]  # An unchanged input is read, never reinstalled as an output.
    binding, intent, key = source_review_binding(repository, snapshot, review)
    command = command_for_binding(repository, binding, kind="source_update", key=key,
                                   writes=list(writes), request=intent)
    source = Path(review["source"])
    tree = ({"kind": "directory", "files": [{"path": name, "content_sha256": digest}
             for name, digest in sorted(review["source_files"].items())]} if source.is_dir() else
            {"kind": "file", "content_sha256": next(iter(review["source_files"].values()))})
    tree_sha = canonical_json_sha256(tree, allow_nan=False)
    if review.get("source_tree_sha256", tree_sha) != tree_sha:
        raise ValueError("The confirmed source-tree hash differs from its exact file inventory")
    tree_reads = {str(source): SourceTreeRead(str(source), tree_sha)}
    for supplied in review.get("mapping_source_trees", []):
        tree_read = SourceTreeRead(**supplied)
        if tree_read.locator in tree_reads and tree_reads[tree_read.locator] != tree_read:
            raise ValueError("The mapping and incoming source tree witnesses disagree")
        tree_reads[tree_read.locator] = tree_read
    command = replace(command, source_trees=tuple(tree_reads[name] for name in sorted(tree_reads)))
    sources = []
    for name, digest in review["source_files"].items():
        literal = str(source / name if source.is_dir() else source)
        from sciplot_core.studio_core.preparation_commands import source_identity_for_locator

        identity = source_identity_for_locator(snapshot, literal)
        sources.append({"source_id": identity, "path": literal, "locator": literal, "version": digest})
    record = ProjectCommands(repository).preview(command, lambda: ProjectMutation(writes,
        {"status": "updated", "project": str(project), "review": review}, sources=sources,
        review=review, artifacts=artifacts, prepared_sources=prepared_sources, input_reads=input_reads))
    return _public_review(project, record)


def decide_source_update(project: Path, supplied: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.studio_core.source_update_state import _applied_result, _check_external_state

    repository = project_store(project)
    app = ProjectCommands(repository)
    record = query_for_apply(app, str(supplied.get("command_key") or ""))
    if (record is None or record.get("metadata", {}).get("kind") != "source_update"
            or record.get("phase") not in {"needs_review", "accepted", "complete"}
            or not isinstance(record.get("review"), dict)):
        raise ValueError("A complete unchanged stored source-update preview is required")
    original_root = record.get("review", {}).get("project") if record is not None else None
    original_view = _public_review(Path(original_root), record) if isinstance(original_root, str) and record is not None else None
    if record is None or supplied not in (_public_review(project, record), original_view):
        raise ValueError("A complete unchanged stored source-update preview is required")
    original = record["review"]
    command = ProjectCommand.from_payload(record["metadata"])
    if record["phase"] != "complete" and not record.get("committed_generation"):
        source = Path(original["source"])
        tree = next((item for item in command.source_trees if item.locator == str(source)), None)
        selected = (repository.prepared_tree_path(command.key, command.command_digest, decision_id=record["decision_id"],
                    locator=str(source), tree_sha256=tree.tree_sha256) if tree is not None else None)
        delivery = repository.locations.get("delivery")
        if delivery is None and isinstance(original_root, str):
            from sciplot_core.output_contract import requested_delivery_root

            request = json.loads((project / "plot_request.json").read_text())
            declared = requested_delivery_root({"request": request}, run_output=project)
            if declared.is_relative_to(Path(original_root)):
                delivery = project / declared.relative_to(original_root)
        _check_external_state(project, source, original, source_override=selected, delivery_override=delivery)
    completed = app.decide(command,
                           decision_id=record["decision_id"], accept=True)
    archived = Path(completed["artifact_root"]) / "before"
    return {**_applied_result(project, supplied, archived,
             status="already_applied" if record["phase"] == "complete" else "updated"),
            "project_command": {key: completed[key] for key in ("command_id", "phase", "project_id", "generation")}}
