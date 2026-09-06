"""Inspectable external edits of saved native documents, without a GUI selection."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.project_manifest import locked_intake_project_manifest
from sciplot_core.studio_core.document_edit_commit import (
    commit_document_edit,
    prior_edit_result,
)
from sciplot_core.studio_core.document_edit_policy import validate_edit_science_policy
from sciplot_core.studio_core.document_edit_state import (
    audit_edited_document,
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
from sciplot_core.studio_core.project_session import external_project_session


def preview_project_document(
    project: Path, *, output_dir: Path, figure_id: str | None = None
) -> dict[str, Any]:
    project = resolve_project_path(project)
    selected = resolve_project_figure(project, figure_id)
    document = Path(selected["document"])
    state = edit_state(project)
    output = new_preview_directory(project, output_dir)
    rendered = run_document_worker(
        "preview-document", document, "--out", output / "current.png"
    )
    identity = {
        "path": str(document),
        "sha256": state["project_files"][str(document.relative_to(project))],
    }
    if edit_state(project) != state or rendered["document"] != identity:
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
    document: Path, spec: Path, changes: list[dict[str, Any]], output: Path
) -> dict[str, Any]:
    validate_edit_science_policy(changes, spec)
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
    )
    result["scientific_audit"] = audit_edited_document(
        Path(result["candidate"]["path"]), spec
    )
    return result


def preview_document_edit(
    project: Path,
    changes: list[dict[str, Any]],
    *,
    output_dir: Path,
    figure_id: str | None = None,
    expected_document_sha256: str,
) -> dict[str, Any]:
    project = resolve_project_path(project)
    selected = resolve_project_figure(project, figure_id)
    document, spec = Path(selected["document"]), Path(selected["spec"])
    if file_sha256(document) != expected_document_sha256:
        raise ValueError(
            "The document revision is stale. Inspect its current objects first."
        )
    state = edit_state(project)
    if (
        state["project_files"].get(str(document.relative_to(project)))
        != expected_document_sha256
    ):
        raise ValueError(
            "The document revision changed while capturing the edit baseline."
        )
    output = new_preview_directory(project, output_dir)
    audit_edited_document(document, spec)
    candidate = _candidate(document, spec, changes, output)
    if edit_state(project) != state:
        raise ValueError("Project or delivery changed during the edit preview.")
    review = {
        "kind": "sciplot_document_edit_preview",
        "version": 1,
        "status": "ready",
        "project": str(project),
        "figure_id": selected["figure_id"],
        "document": str(document),
        "document_sha256": expected_document_sha256,
        "base_state": state,
        "changes": changes,
        "actual_changes": candidate["changes"],
        "candidate": candidate["candidate"],
        "preview": candidate["preview"],
        "scientific_audit": candidate["scientific_audit"],
        "ready_to_use": False,
    }
    review["operation_id"] = preview_identity(review)
    path = output / "edit-preview.json"
    atomic_write_json(path, review)
    return {**review, "review_path": str(path)}


def apply_document_edit(project: Path, preview: dict[str, Any]) -> dict[str, Any]:
    project = resolve_project_path(project)
    # review_path is a convenience reference in CLI output, never signed state.
    review = {k: v for k, v in preview.items() if k != "review_path"}
    if (
        review.get("kind") != "sciplot_document_edit_preview"
        or review.get("version") != 1
        or review.get("status") != "ready"
        or review.get("project") != str(project)
        or review.get("operation_id") != preview_identity(review)
    ):
        raise ValueError(
            "A complete unchanged edit preview for this project is required."
        )
    with external_project_session(project), locked_intake_project_manifest(project):
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
        # Re-run the allowed native operations. Caller-controlled candidate bytes
        # are never installed, even if their hashes and science audit look valid.
        with tempfile.TemporaryDirectory(
            prefix=".sciplot-edit-", dir=project.parent
        ) as directory:
            candidate = _candidate(document, spec, review["changes"], Path(directory))
            if (
                candidate["changes"] != review["actual_changes"]
                or candidate["preview"]["sha256"] != review["preview"]["sha256"]
            ):
                raise ValueError(
                    "The native edit no longer matches its reviewed preview."
                )
            return commit_document_edit(
                project, document, Path(candidate["candidate"]["path"]), review
            )
