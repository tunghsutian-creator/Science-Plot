"""Persist source-update review images and reuse the existing revision owners."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.studio_core.document_edit_state import (
    check_artifact, new_preview_directory, run_document_worker,
)
from sciplot_core.studio_core.project_query_paths import canonical_path, resolve_project_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.studio_core.source_update import (
    apply_project_source_update, preview_project_source_update,
)
from sciplot_core.studio_core.source_update_review import project_figures
from sciplot_core.task_contract import TaskControlError


def prepare_source_update_review(
    project: Path, source: Path, *, review_path: Path, worksheet: str | None = None,
    mapping_request: dict[str, Any] | None = None,
    annotation_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep before/candidate PNGs after the isolated candidate is discarded."""
    project, source = resolve_project_path(project), canonical_path(source)
    path = canonical_path(review_path)
    image_dir = path.with_name(path.stem + "_images")
    if path.exists() or path == source or path.is_relative_to(source) or image_dir.is_relative_to(source):
        raise TaskControlError("task_review_path_overlap", "请使用原始数据、项目及成图目录之外的新审阅路径。")
    # The shared owner checks project, original source and visible delivery paths.
    image_dir = new_preview_directory(project, image_dir)
    previews: list[dict[str, Any]] = []

    def capture(candidate: Path, review: dict[str, Any]) -> None:
        for scope, root in (("before", project), ("candidate", candidate)):
            for index, (figure_id, (document, _spec)) in enumerate(project_figures(root).items()):
                identity = {"path": str(document), "sha256": file_sha256(document)}
                output = image_dir / f"{scope}_{index:03}.png"
                rendered = run_document_worker("preview-document", document, "--out", output)
                if rendered.get("document") != identity or file_sha256(document) != identity["sha256"]:
                    raise ValueError("The source-update figure changed while rendering its review.")
                check_artifact(rendered["preview"])
                previews.append({"figure_id": figure_id, "scope": scope, "preview": rendered["preview"]})

    review = preview_project_source_update(project, source, worksheet=worksheet, on_candidate=capture,
        **({"mapping_request": mapping_request} if mapping_request else {}),
        **({"annotation_decisions": annotation_decisions} if annotation_decisions is not None else {}))
    result = {
        "kind": "sciplot_task_source_update_review", "version": 1,
        "status": review["status"], "project": str(project), "review_path": str(path),
        "source_update": review, "previews": previews,
    }
    result["revision_id"] = canonical_json_sha256(result, allow_nan=False)
    atomic_write_json(path, result)
    return result


def apply_source_update_review(
    project: Path, *, review_path: Path, expected_revision_id: str,
) -> dict[str, Any]:
    """Apply the exact reviewed source revision, or recover a proven saved result."""
    project, path = resolve_project_path(project), canonical_path(review_path)
    review = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(review, dict)
        or review.get("kind") != "sciplot_task_source_update_review" or review.get("version") != 1
        or review.get("status") != "ready" or review.get("project") != str(project)
        or review.get("review_path") != str(path)
        or review.get("revision_id") != expected_revision_id
        or canonical_json_sha256({key: value for key, value in review.items() if key != "revision_id"}, allow_nan=False)
        != expected_revision_id
    ):
        raise TaskControlError("task_review_changed", "源更新审阅记录已变化，请查询并审阅当前修订。")
    for item in review["previews"]:
        check_artifact(item["preview"])
    with external_project_session(project):
        result = apply_project_source_update(project, review["source_update"])
    return {**result, "revision_id": expected_revision_id, "review_path": str(path)}


__all__ = ["prepare_source_update_review", "apply_source_update_review"]
