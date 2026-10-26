"""Reviewed native edit candidates and decisions in the shared command store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from collections.abc import Callable

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.studio_core.document_edit_policy import validate_edit_science_policy
from sciplot_core.studio_core.document_edit_state import new_preview_directory, native_edit_request_key
from sciplot_core.studio_core.document_edit_review import (
    reviewed_edit as reviewed_edit, rebind_document_edit_review as rebind_document_edit_review,
)
from sciplot_core.studio_core.project_command_scope import (
    command_for_binding, figure_binding, project_command_runtime, project_store, query_for_apply, source_versions,
)
from sciplot_core.studio_core.project_query import resolve_project_figure, resolve_project_path


@project_command_runtime
def preview_native_edit(project: Path, changes: list[dict[str, Any]], *, output_dir: Path,
                        figure_id: str | None, expected_document_sha256: str,
                        operations: list[dict[str, Any]] | None,
                        expected_spec_sha256: str | None,
                        candidate_builder: Callable[..., dict[str, Any]],
                        audit_document: Callable[..., dict[str, Any]],
                        request_id: str | None = None) -> dict[str, Any]:

    project = resolve_project_path(project)
    selected = resolve_project_figure(project, figure_id)
    document, spec = Path(selected["document"]), Path(selected["spec"])
    if file_sha256(document) != expected_document_sha256:
        raise ValueError("The document revision is stale. Inspect its current objects first.")
    if expected_spec_sha256 is not None and file_sha256(spec) != expected_spec_sha256:
        raise ValueError("The sample mapping changed during style resolution; inspect again.")
    if operations is not None:
        if changes:
            raise ValueError("Use either native changes or semantic operations in one preview.")
        from sciplot_core.studio_core.annotation_batch import compile_annotation_operations

        compile_annotation_operations(json.loads(spec.read_text()), operations,
                                      document_sha256=expected_document_sha256, figure_id=selected["figure_id"])
    else:
        validate_edit_science_policy(changes, spec)
    repository = project_store(project)
    binding = figure_binding(project, selected, store=repository)
    relative = repository.logical_path(document)
    if binding["files"][relative] != expected_document_sha256:
        raise ValueError("The native document changed while capturing its selected read witness")
    writes = [relative] + ([repository.logical_path(spec)] if operations is not None else [])
    intent = {"figure_id": selected["figure_id"], "document_relative": relative,
              "expected_files": binding["files"], "projected_reads": binding["projected_reads"],
              "source_files": binding["source_files"], "changes": changes, "operations": operations}
    if request_id is not None:
        intent["request_id"] = request_id
    key = (native_edit_request_key(binding["project_id"], request_id) if request_id is not None else
           canonical_json_sha256({"kind": "document_edit", "project_id": binding["project_id"], "intent": intent}))
    app = ProjectCommands(repository)
    prior = app.query(key)
    if prior is not None:
        if prior["metadata"]["request"] != intent:
            raise ValueError("The native edit key already belongs to another business request")
        if prior["phase"] not in {"needs_review", "accepted", "complete"}:
            app.resume(ProjectCommand.from_payload(prior["metadata"]))
        return reviewed_edit(prior, project)
    command = command_for_binding(repository, binding, kind="document_edit", key=key,
                                   writes=writes, request=intent)
    output = new_preview_directory(project, output_dir)

    def prepare() -> ProjectMutation:
        audit_document(document, spec)
        candidate = candidate_builder(document, spec, changes, output, operations=operations,
                                      figure_id=selected["figure_id"])
        Path(candidate["candidate"]["path"]).chmod(document.stat().st_mode & 0o777)
        artifacts: dict[str, bytes | Path] = {"before.vsz": document.read_bytes(), "after.vsz": Path(candidate["candidate"]["path"]),
                     "candidate.png": Path(candidate["preview"]["path"])}
        installed = {relative: Path(candidate["candidate"]["path"])}
        result = {"document_relative": relative, "figure_id": selected["figure_id"],
                  "base_sha256": expected_document_sha256, "result_sha256": candidate["candidate"]["sha256"],
                  "base_files": binding["files"], "export_required": True, "ready_to_use": False}
        review = {"kind": "sciplot_document_edit_preview", "version": 3, "status": "ready",
                  "figure_id": selected["figure_id"], "document_sha256": expected_document_sha256,
                  "changes": changes, "actual_changes": candidate["changes"],
                  "candidate": candidate["candidate"], "preview": candidate["preview"],
                  "scientific_audit": candidate["scientific_audit"], "ready_to_use": False}
        if operations is not None:
            spec_relative = repository.logical_path(spec)
            installed[spec_relative] = Path(candidate["candidate_spec"]["path"])
            installed[spec_relative].chmod(spec.stat().st_mode & 0o777)
            artifacts.update({"before.spec.json": spec.read_bytes(), "after.spec.json": installed[spec_relative]})
            result["companion"] = {"relative": spec_relative, "base_sha256": file_sha256(spec),
                                   "result_sha256": candidate["candidate_spec"]["sha256"]}
            review.update(operations=operations, candidate_spec=candidate["candidate_spec"])
        artifacts["preview.json"] = json.dumps(review, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        return ProjectMutation(installed, result, sources=source_versions(binding, store=repository), review=review, artifacts=artifacts)

    record = app.preview(command, prepare)
    result = reviewed_edit(record, project)
    path = output / "edit-preview.json"
    atomic_write_json(path, result)
    return {**result, "review_path": str(path)}


def apply_native_edit(project: Path, supplied: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.studio_core.document_edit_commit import _operation_result

    project = resolve_project_path(project)
    app = ProjectCommands(project_store(project))
    review = {key: value for key, value in supplied.items() if key != "review_path"}
    record = query_for_apply(app, str(review.get("operation_id") or ""))
    if record is None or review != reviewed_edit(record, project):
        raise ValueError("A complete unchanged stored native edit preview is required")
    command = ProjectCommand.from_payload(record["metadata"])
    if command.kind.value != "document_edit":
        raise ValueError("The stored candidate is not a native document edit")
    completed = app.decide(command, decision_id=review["decision_id"], accept=True)
    result = _operation_result(project, completed)
    if not result["result_is_current"]:
        raise ValueError("The saved native edit has since changed; preserve its evidence")
    return {**result, "document_sha256": result["result_sha256"],
            "status": "already_applied" if record["phase"] == "complete" else "applied"}


def verify_document_edit_receipt(project: Path, supplied: dict[str, Any]) -> dict[str, Any] | None:
    """Verify an already completed native outcome without executing or repairing it."""
    from sciplot_core.project_store.runtime import project_runtime, resolve_runtime_path
    from sciplot_core.project_commands.read_projections import projection_digest
    from sciplot_core.studio_core.document_edit_commit import _operation_result

    if supplied.get("version") != 3:
        return None
    project = resolve_project_path(project)
    repository = project_store(project)
    record = ProjectCommands(repository).query(str(supplied.get("operation_id") or ""))
    if record is None or record["phase"] != "complete":
        return None
    review = rebind_document_edit_review(project, supplied)
    if review["decision_id"] != record.get("decision_id"):
        raise ValueError("The completed native decision differs from its owned receipt")
    result = _operation_result(project, record)
    audit = review.get("scientific_audit", {})
    selected = resolve_project_figure(project, review["figure_id"])
    native, spec = Path(selected["document"]), Path(selected["spec"])
    if repository.logical_path(native) != record["result"]["document_relative"]:
        raise ValueError("The completed native receipt no longer selects the same figure")
    snapshot = repository.snapshot()
    if snapshot["project_id"] != record["project_id"]:
        raise ValueError("The completed native receipt belongs to another stable project")
    if (not result["result_is_current"] or audit.get("status") != "passed"
            or audit.get("document_sha256") != result["result_sha256"]
            or audit.get("spec_sha256") != file_sha256(spec)):
        raise ValueError("The completed native receipt is not exact-current scientific evidence")
    for name, before in record["read_set"].items():
        write = record["draft"]["writes"].get(name)
        expected = write["sha256"] if write is not None else before
        entry = snapshot["files"].get(name)
        if (entry["sha256"] if entry is not None else None) != expected:
            raise ValueError("A completed native receipt read witness has changed")
        if entry is not None:
            actual = repository.projection_path(name)
            expected_mode = write["mode"] if write is not None else entry["mode"]
            if actual.stat().st_mode & 0o777 != expected_mode:
                raise ValueError("A completed native receipt output mode has changed")
    for value in record["metadata"].get("projected_reads", []):
        if projection_digest(repository.projection_path(value["resource"]).read_bytes(), kind=value["kind"], key=value["key"]) != value["sha256"]:
            raise ValueError("The completed native receipt selected membership or scientific task changed")
    with project_runtime(repository):
        for path, expected in record["metadata"]["request"].get("source_files", {}).items():
            if file_sha256(resolve_runtime_path(path, expected_sha256=expected)) != expected:
                raise ValueError("The completed native receipt scientific source changed")
    return {**result, "document_sha256": result["result_sha256"], "spec_sha256": audit["spec_sha256"],
            "decision_id": record["decision_id"], "read_set": record["read_set"],
            "readonly_native_receipt": True}
