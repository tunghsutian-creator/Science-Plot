"""Inspectable external edits of saved native documents, without a GUI selection."""

from __future__ import annotations

import json
import tempfile
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.project_store.native_artifacts import (
    NativeArtifactInput, NativeArtifactOutput, native_artifact_binding, native_artifact_runtime,
)
from sciplot_core.project_store.source_resolver import ProjectSourceResolver
from sciplot_core.source_coverage.native_file_snapshots import observed_native_document
from sciplot_core.studio_core.document_edit_commit import (
    commit_document_edit,
    prior_edit_result,
)
from sciplot_core.studio_core.document_edit_policy import validate_edit_science_policy
from sciplot_core.studio_core.project_command_scope import figure_read_state, project_read_runtime
from sciplot_core.studio_core.document_edit_state import (
    audit_edited_document as audit_edited_document,
    check_artifact,
    edit_state,
    new_preview_directory,
    preview_identity,
    run_document_worker,
)
from sciplot_core.studio_core.project_query import (
    resolve_project_figure,
    resolve_project_path,
)


@project_read_runtime
def preview_project_document(
    project: Path, *, output_dir: Path, figure_id: str | None = None
) -> dict[str, Any]:
    project = resolve_project_path(project)
    selected = resolve_project_figure(project, figure_id)
    document = Path(selected["document"])
    state = figure_read_state(project, selected)
    output = new_preview_directory(project, output_dir)
    arguments = ["preview-document", str(document), "--out", str(output / "current.png")]
    resolver = selected_source_resolver()
    context: AbstractContextManager[None] = nullcontext()
    if isinstance(resolver, ProjectSourceResolver) and native_artifact_binding(arguments, resolver) is None:
        context = native_artifact_runtime(arguments,
            inputs=[NativeArtifactInput("document", document, selected["document_sha256"], document.stat().st_mode & 0o777)],
            outputs=[NativeArtifactOutput("out", output / "current.png")])
    with context, observed_native_document(arguments, document, expected_sha256=selected["document_sha256"]):
        rendered = run_document_worker("preview-document", document, "--out", output / "current.png")
    identity = {
        "path": str(document),
        "sha256": state["project_files"][str(document.relative_to(project))],
    }
    if figure_read_state(project, selected) != state or rendered["document"] != identity:
        raise ValueError(
            "The project changed while creating its preview; inspect again."
        )
    result = {
        "kind": "sciplot_project_document_preview",
        "version": 1,
        "status": "ok",
        "project": str(project),
        "figure_id": selected["figure_id"],
        "document": identity,
        "preview": rendered["preview"],
        "ready_to_use": False,
    }
    atomic_write_json(output / "preview.json", result)
    return result


def _candidate(
    document: Path, spec: Path, changes: list[dict[str, Any]], output: Path,
    *, operations: list[dict[str, Any]] | None = None, figure_id: str = "",
) -> dict[str, Any]:
    if operations is not None:
        from sciplot_core.studio_core.annotation_batch import compile_annotation_operations

        compile_annotation_operations(json.loads(spec.read_text()), operations,
                                      document_sha256=file_sha256(document), figure_id=figure_id)
        operation_path = output / "operations.json"
        operation_path.write_text(json.dumps(operations, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        result = run_document_worker(
            "edit-annotations", document, spec, "--operations", operation_path,
            "--figure-id", figure_id, "--output-document", output / "document.vsz",
            "--output-spec", output / "spec.json", "--preview-png", output / "candidate.png",
            "--audit-candidate",
        )
        if not isinstance(result.get("document_audit"), dict):
            raise ValueError("Native candidate editing did not return its required scientific audit.")
        result["scientific_audit"] = audit_edited_document(
            Path(result["candidate"]["path"]), Path(result["candidate_spec"]["path"]),
            native_audit=result["document_audit"])
        return result
    validate_edit_science_policy(changes, spec)
    return _audited_setting_candidate(document, spec, changes, output)


def _audited_setting_candidate(
    document: Path, spec: Path, changes: list[dict[str, Any]], output: Path,
) -> dict[str, Any]:
    """Execute a compiled batch with the shared native and exact-science audits."""
    change_path = output / "changes.json"
    change_path.write_text(
        json.dumps(changes, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    result = run_document_worker(
        "edit-document",
        document,
        "--changes",
        change_path,
        "--output-document",
        output / "document.vsz",
        "--preview-png",
        output / "candidate.png",
        "--audit-spec", spec,
    )
    if not isinstance(result.get("document_audit"), dict):
        raise ValueError("Native candidate editing did not return its required scientific audit.")
    result["scientific_audit"] = audit_edited_document(
        Path(result["candidate"]["path"]), spec, native_audit=result["document_audit"],
    )
    return result


def preview_document_edit(
    project: Path,
    changes: list[dict[str, Any]],
    *,
    output_dir: Path,
    figure_id: str | None = None,
    expected_document_sha256: str,
    operations: list[dict[str, Any]] | None = None,
    expected_spec_sha256: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    from sciplot_core.studio_core.document_edit_commands import preview_native_edit

    return preview_native_edit(project, changes, output_dir=output_dir, figure_id=figure_id,
        expected_document_sha256=expected_document_sha256, operations=operations,
        expected_spec_sha256=expected_spec_sha256, candidate_builder=_candidate, audit_document=audit_edited_document,
        request_id=request_id)


def apply_document_edit(project: Path, preview: dict[str, Any]) -> dict[str, Any]:
    if preview.get("version") == 3:
        from sciplot_core.studio_core.document_edit_commands import apply_native_edit

        return apply_native_edit(project, preview)
    project = resolve_project_path(project)
    # review_path is a convenience reference in CLI output, never signed state.
    review = {k: v for k, v in preview.items() if k != "review_path"}
    if (
        review.get("kind") != "sciplot_document_edit_preview"
        or review.get("version") not in {1, 2}
        or review.get("status") != "ready"
        or review.get("project") != str(project)
        or review.get("operation_id") != preview_identity(review)
    ):
        raise ValueError(
            "A complete unchanged edit preview for this project is required."
        )
    prior = prior_edit_result(project, review)
    if prior is not None:
        return prior
    selected = resolve_project_figure(project, review["figure_id"])
    document, spec = Path(selected["document"]), Path(selected["spec"])
    if (
        file_sha256(document) != review["document_sha256"]
        or review["base_state"]["project_files"].get(
            str(document.relative_to(project))
        )
        != review["document_sha256"]
    ):
        raise ValueError(
            "The edit baseline does not match its expected document revision."
        )
    if (
        str(document) != review["document"]
        or edit_state(project) != review["base_state"]
    ):
        raise ValueError(
            "The project revision is stale. Inspect and preview current state."
        )
    check_artifact(review["candidate"])
    check_artifact(review["preview"])
    if review["version"] == 2:
        if review.get("spec") != str(spec) or review.get("changes") != [] or not isinstance(review.get("operations"), list):
            raise ValueError("The annotation preview must name its current specification.")
        check_artifact(review["candidate_spec"])
    # Re-run the allowed native operations. Caller-controlled candidate bytes
    # are never installed, even if their hashes and science audit look valid.
    with tempfile.TemporaryDirectory(
        prefix=".sciplot-edit-", dir=project.parent
    ) as directory:
        candidate = _candidate(document, spec, review["changes"], Path(directory),
                               operations=review.get("operations") if review["version"] == 2 else None,
                               figure_id=review["figure_id"])
        if (
            candidate["changes"] != review["actual_changes"]
            or candidate["preview"]["sha256"] != review["preview"]["sha256"]
        ):
            raise ValueError(
                "The native edit no longer matches its reviewed preview."
            )
        if review["version"] == 2 and candidate["candidate_spec"]["sha256"] != review["candidate_spec"]["sha256"]:
            raise ValueError("The annotation specification no longer matches its preview.")
        return commit_document_edit(
            project, document, Path(candidate["candidate"]["path"]), review,
            spec=spec if review["version"] == 2 else None,
            candidate_spec=Path(candidate["candidate_spec"]["path"]) if review["version"] == 2 else None,
        )
