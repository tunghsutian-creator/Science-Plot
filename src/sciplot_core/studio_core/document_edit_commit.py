"""Native edit commit/recovery through the one project command repository."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.studio_core.document_edit_state import edit_state
from sciplot_core.studio_core.project_command_scope import (
    command_for_binding, command_result, project_store, query_for_apply, source_versions,
)


def _operation_result(project: Path, record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result") or record.get("draft", {}).get("result", {})
    relative = Path(result.get("document_relative") or record["metadata"]["request"]["document_relative"])
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("studio",):
        raise ValueError("An edit operation must reference a managed document")
    document = project / relative
    current = file_sha256(document) if document.is_file() else None
    companion = result.get("companion")
    companion_current = (file_sha256(project / companion["relative"]) == companion["result_sha256"]
                         if isinstance(companion, dict) else True)
    paths = record.get("artifact_paths", {})
    return {**result, "kind": "sciplot_document_edit_operation", "version": 1,
            "operation_id": record["command_id"], "project": str(project), "document": str(document),
            "status": "applied" if record["phase"] == "complete" else "pending",
            "result_is_current": current is not None and current == result.get("result_sha256") and companion_current,
            "current_sha256": current, "archive": paths.get("before.vsz"),
            "artifact_paths": paths, "project_command": {name: record[name] for name in (
                "command_id", "command_digest", "project_id", "generation", "phase")}}


def read_edit_operation(project: Path, operation_id: str) -> dict[str, Any]:
    record = ProjectCommands(project_store(project)).query(operation_id)
    if record is not None:
        if record.get("metadata", {}).get("kind") != "document_edit":
            raise ValueError("This operation is not a native document edit")
        return _operation_result(project, record)
    from sciplot_core.studio_core.document_edit_legacy import read_edit_operation as read_legacy

    return read_legacy(project, operation_id)


def prior_edit_result(project: Path, review: dict[str, Any]) -> dict[str, Any] | None:
    app = ProjectCommands(project_store(project))
    record = query_for_apply(app, review["operation_id"])
    if record is not None:
        if record.get("metadata", {}).get("request", {}).get("review_sha256") != review["operation_id"]:
            raise ValueError("The command key belongs to another reviewed native edit")
        if record["phase"] == "reserved":
            return None
        record = app.resume(ProjectCommand.from_payload(record["metadata"]))
        result = _operation_result(project, record)
        if not result["result_is_current"]:
            raise ValueError("The applied native document has since changed; preserve its evidence")
        return {**result, "status": "already_applied", "export_required": True}
    from sciplot_core.studio_core.document_edit_state import history_directory
    from sciplot_core.studio_core.document_edit_legacy import read_edit_operation as read_legacy

    root = history_directory(project, review["operation_id"])
    if not (root / "outcome.json").exists():
        return None
    saved = json.loads((root / "preview.json").read_text())
    if saved != review:
        raise ValueError("The historical edit preview identity changed")
    result = read_legacy(project, review["operation_id"])
    if file_sha256(root / "before.vsz") != result["previous_document_sha256"]:
        raise ValueError("The archived native edit baseline archive changed")
    if result["result_is_current"]:
        return {**result, "status": "already_applied", "export_required": True,
                "legacy_evidence_read_only": True}
    if file_sha256(Path(result["document"])) == result["previous_document_sha256"]:
        return None
    raise ValueError("The historical native edit has since changed; preserve its evidence")


def commit_document_edit(project: Path, document: Path, candidate: Path, review: dict[str, Any],
                         *, spec: Path | None = None, candidate_spec: Path | None = None) -> dict[str, Any]:
    """Publish selected VSZ/spec and immutable evidence in one shared generation."""
    if (spec is None) != (candidate_spec is None):
        raise ValueError("Annotation commits require both current and candidate specifications")
    repository = project_store(project)
    app = ProjectCommands(repository)
    prior = prior_edit_result(project, review)
    if prior is not None:
        return prior
    binding = review.get("project_binding")
    if binding is None:
        if edit_state(project) != review["base_state"]:
            raise ValueError("Project or delivery changed after preview; inspect current state")
        snapshot = repository.snapshot(import_legacy=True)
        binding = {"project_id": snapshot["project_id"], "generation": snapshot["generation"],
                   "files": review["base_state"]["project_files"]}
    relative = repository.logical_path(document)
    candidate.chmod(document.stat().st_mode & 0o777)
    writes: dict[str, bytes | Path | None] = {relative: candidate}
    artifacts: dict[str, bytes | Path] = {
        "before.vsz": document.read_bytes(), "after.vsz": candidate,
        "preview.json": json.dumps(review, sort_keys=True, ensure_ascii=False, allow_nan=False).encode(),
    }
    result: dict[str, Any] = {"document_relative": relative, "base_sha256": file_sha256(document),
        "result_sha256": file_sha256(candidate), "export_required": True, "ready_to_use": False,
        "base_files": binding["files"], "figure_id": review.get("figure_id", "primary")}
    if spec is not None and candidate_spec is not None:
        candidate_spec.chmod(spec.stat().st_mode & 0o777)
        spec_relative = repository.logical_path(spec)
        writes[spec_relative] = candidate_spec
        artifacts.update({"before.spec.json": spec.read_bytes(), "after.spec.json": candidate_spec})
        result["companion"] = {"relative": spec_relative, "base_sha256": file_sha256(spec),
                               "result_sha256": file_sha256(candidate_spec)}
    command = command_for_binding(repository, binding, kind="document_edit", key=review["operation_id"],
        writes=list(writes), request={"review_sha256": review["operation_id"], "document_relative": relative,
            "figure_id": result["figure_id"], "actual_changes": review.get("actual_changes", review.get("changes", [])),
            "operations": review.get("operations")})
    record = app.execute(command, lambda: ProjectMutation(writes, result,
        sources=source_versions(binding, store=repository), artifacts=artifacts))
    command_result(record)
    return _operation_result(project, record)


def applied_native_edit_chain(project: Path, *, figure_id: str, document: Path, spec: Path,
                              baseline_files: dict[str, Any]) -> list[str] | None:
    app = ProjectCommands(project_store(project))
    relative, spec_relative = document.relative_to(project).as_posix(), spec.relative_to(project).as_posix()
    transitions: dict[tuple[str, str], list[tuple[tuple[str, str], str]]] = {}
    for record in app.commands():
        if record.get("projection_pending"):
            from sciplot_core.project_store.errors import ProjectRecoveryRequired

            raise ProjectRecoveryRequired("Explicitly recover the native generation before checking its contiguous history")
        result = record.get("result", {})
        if (record.get("phase") != "complete" or record.get("metadata", {}).get("kind") != "document_edit"
                or result.get("figure_id") != figure_id or result.get("document_relative") != relative):
            continue
        before_spec = result.get("base_files", {}).get(spec_relative)
        after_spec = result.get("companion", {}).get("result_sha256", before_spec)
        before, after = (result["base_sha256"], before_spec), (result["result_sha256"], after_spec)
        paths = record["artifact_paths"]
        if file_sha256(Path(paths["before.vsz"])) != before[0] or file_sha256(Path(paths["after.vsz"])) != after[0]:
            raise ValueError("Native edit history document archives changed")
        for name, digest in baseline_files.items():
            path = Path(name)
            if path not in {document, spec} and path.is_relative_to(project):
                if result["base_files"].get(path.relative_to(project).as_posix()) != digest:
                    raise ValueError("Native edit history used another source or project baseline")
        transitions.setdefault(after, []).append((before, record["command_id"]))
    state, baseline, chain, visited = ((file_sha256(document), file_sha256(spec)),
        (baseline_files[str(document)], baseline_files[str(spec)]), [], set())
    while state != baseline and state not in visited and len(transitions.get(state, [])) == 1:
        visited.add(state)
        state, key = transitions[state][0]
        chain.append(key)
    if state == baseline:
        return list(reversed(chain))
    from sciplot_core.studio_core.document_edit_legacy import applied_native_edit_chain as legacy_chain

    return legacy_chain(project, figure_id=figure_id, document=document, spec=spec, baseline_files=baseline_files)
