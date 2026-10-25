"""Freeze whole-source revisions and publish their complete generation once."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store, query_for_apply, whole_memberships
from sciplot_core.project_commands.resources import PreparedFile
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio_core.source_update_files import project_inventory, relocate_metadata


def source_mutation(project: Path, candidate: Path, review: dict[str, Any], *,
                    relocate_companion: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
                    expected: dict[str, str] | None = None,
                    store: FileProjectStore | None = None) -> tuple[dict[str, bytes | Path | PreparedFile | None], dict[str, bytes | Path]]:
    names = sorted(path.name for path in candidate.iterdir()
                   if path.name not in {"runs", "delivery", ".sciplot_store", ".sciplot_resources"})
    if not {"plot_request.json", "studio", "source", "raw"}.issubset(names):
        raise ValueError("Prepared source update is missing required active project parts")
    for path in [*candidate.glob("*.json"), *(candidate / "studio").rglob("*.json")]:
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
    before = expected if expected is not None else project_inventory(project)
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


def stage_source_update(project: Path, candidate: Path, review: dict[str, Any], *,
                        relocate_companion: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    repository = project_store(project, with_snapshot=True)
    snapshot = repository.snapshot(import_legacy=True)
    before = project_inventory(project)
    if canonical_json_sha256(before) != review["project_sha256"]:
        # Historical payload_hash uses the same canonical JSON, without whitespace.
        from sciplot_core.studio_core.source_update_review import payload_hash

        if payload_hash(before) != review["project_sha256"]:
            raise ValueError("Project changed while its source candidate was prepared")
    (candidate / "source_update.json").write_text(json.dumps(review, ensure_ascii=False, indent=2))
    writes, artifacts = source_mutation(project, candidate, review, relocate_companion=relocate_companion, expected=before,
                                       store=repository)
    reads = {name: value["sha256"] for name, value in snapshot["files"].items()}
    binding = {"project_id": snapshot["project_id"], "generation": snapshot["generation"], "files": reads,
               "read_memberships": whole_memberships(repository, snapshot)}
    intent = {name: review.get(name) for name in ("source_tree_sha256", "source_files", "worksheet",
        "mapping_request", "annotation_decisions", "project_sha256", "delivery_sha256")}
    key = canonical_json_sha256({"kind": "source_update", "project_id": binding["project_id"], "intent": intent})
    command = command_for_binding(repository, binding, kind="source_update", key=key,
                                   writes=list(writes), request=intent)
    source = Path(review["source"])
    sources = [{"source_id": canonical_json_sha256({"project_id": binding["project_id"], "source": str(source), "member": name})[:32],
                "path": str(source / name if source.is_dir() else source), "version": digest}
               for name, digest in review["source_files"].items()]
    record = ProjectCommands(repository).preview(command, lambda: ProjectMutation(writes,
        {"status": "updated", "project": str(project), "review": review}, sources=sources,
        review=review, artifacts=artifacts))
    return _public_review(project, record)


def decide_source_update(project: Path, supplied: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.studio_core.source_update_state import _applied_result, _check_external_state

    app = ProjectCommands(project_store(project))
    record = query_for_apply(app, str(supplied.get("command_key") or ""))
    if record is None or supplied != _public_review(project, record):
        raise ValueError("A complete unchanged stored source-update preview is required")
    original = record["review"]
    if record["phase"] != "complete":
        _check_external_state(project, Path(original["source"]), original)
    completed = app.decide(ProjectCommand.from_payload(record["metadata"]),
                           decision_id=record["decision_id"], accept=True)
    archived = Path(completed["artifact_root"]) / "before"
    return {**_applied_result(project, supplied, archived,
             status="already_applied" if record["phase"] == "complete" else "updated"),
            "project_command": {key: completed[key] for key in ("command_id", "phase", "project_id", "generation")}}
