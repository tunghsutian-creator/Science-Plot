"""Comparison receipts bind alternatives to one native project baseline."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.studio_core.document_edit_state import check_artifact, preview_identity
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_comparison_contract import candidate_request, comparison_request_schema
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_group_contract import validate_shape
from sciplot_core.task_storage import load_task


def comparison_path(path: Path) -> Path:
    path = canonical_path(path)
    return path.parent if path.name == "comparison.json" else path


def save_comparison(root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["state_sha256"] = canonical_json_sha256({k: v for k, v in state.items() if k != "state_sha256"}, allow_nan=False)
    atomic_write_json(root / "comparison.json", state)


def load_comparison(root: Path) -> dict[str, Any]:
    state = json.loads((root / "comparison.json").read_text())
    if (not isinstance(state, dict) or state.get("kind") != "sciplot_task_comparison"
            or state.get("version") != 1 or state.get("comparison_dir") != str(root)):
        raise TaskControlError("invalid_comparison", "比较记录的位置或版本不匹配。")
    digest = canonical_json_sha256({k: v for k, v in state.items() if k != "state_sha256"}, allow_nan=False)
    if digest != state.get("state_sha256"):
        raise TaskControlError("comparison_record_changed", "比较记录已变化，请保留原记录。")
    validate_shape(state["request"], comparison_request_schema())
    return dict(state)


def candidate_task(root: Path, state: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    directory = canonical_path(root / "candidates" / item["id"])
    if not directory.exists():
        return None
    child = load_task(directory)
    if child["request"] != candidate_request(state["request"], item) or child.get("edit_revisions"):
        raise TaskControlError("comparison_candidate_changed", "候选任务已被单独修改，请新建比较。")
    return child


def candidate_review(root: Path, state: dict[str, Any], item: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    path = canonical_path(root / "candidates" / item["id"] / "review.json")
    review = json.loads(path.read_text())
    if not isinstance(review, dict):
        raise TaskControlError("comparison_preview_changed", "候选预览记录不是完整对象。")
    signed = {k: v for k, v in review.items() if k != "review_path"}
    if (signed.get("kind") != "sciplot_document_edit_preview" or signed.get("version") != 2 or signed.get("status") != "ready"
            or signed.get("operation_id") != preview_identity(signed)
            or signed.get("operation_id") != child.get("operation_id")
            or signed.get("base_state") != state["baseline"]
            or signed.get("project") != state["request"]["project"]
            or signed.get("figure_id") != state["request"]["figure_id"]
            or signed.get("document_sha256") != state["request"]["expected_document_sha256"]
            or signed.get("scientific_audit", {}).get("status") != "passed"):
        raise TaskControlError("comparison_preview_changed", "候选不再对应本次比较的原始基准。")
    for key in ("preview", "candidate", "candidate_spec"):
        if key in signed:
            artifact = check_artifact(signed[key])
            if not artifact.is_relative_to(path.parent):
                raise TaskControlError("comparison_artifact_location", "候选文件必须位于自己的任务目录内。")
    return dict(review)
