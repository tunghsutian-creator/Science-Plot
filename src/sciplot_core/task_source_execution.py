"""Task checkpoints around reviewed source revisions and exact-current export."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_execution import _phase, run_export
from sciplot_core.task_planning import assert_source_current
from sciplot_core.task_source_update import apply_source_update_review, prepare_source_update_review
from sciplot_core.task_storage import save_task


def run_source_preview(root: Path, state: dict[str, Any]) -> None:
    source = assert_source_current(state)
    _phase(root, state, "previewing")
    index = int(state.get("preview_attempt", 0)) + 1
    state["preview_attempt"] = index
    save_task(root, state)
    request = state["request"]
    review = prepare_source_update_review(
        Path(request["project"]), source, worksheet=request.get("worksheet"),
        review_path=root / f"source_review_{index:03}.json",
    )
    state.update(project=review["project"], revision_id=review["revision_id"])
    if review["status"] != "ready":
        state.update(status="blocked", blocker={
            "reason_code": "source_update_blocked",
            "message": review["source_update"].get("reason", "源更新预览未就绪。"),
            "review_path": review["review_path"],
        })
        save_task(root, state)
        return
    candidates = [item for item in review["previews"] if item["scope"] == "candidate"]
    if not candidates:
        raise TaskControlError("source_update_preview_missing", "源更新缺少可审阅的候选图。")
    state.update(status="needs_review", phase="review", previews=review["previews"], preview={
        "image": candidates[0]["preview"], "review_path": review["review_path"],
        "changes": review["source_update"],
    })
    save_task(root, state)


def validate_source_response(state: dict[str, Any], response: dict[str, Any]) -> None:
    if set(response) != {"accept_source_update", "expected_revision_id"} or type(response.get("accept_source_update")) is not bool:
        raise TaskControlError("invalid_task_response", "审阅全部源更新候选图后，回答 accept_source_update 并附当前 expected_revision_id。")
    if response["expected_revision_id"] != state["revision_id"]:
        raise TaskControlError("stale_source_review", "此答案对应旧源更新预览，请读取当前修订。")


def run_source_apply_export(root: Path, state: dict[str, Any]) -> None:
    assert_source_current(state)
    _phase(root, state, "applying")
    result = apply_source_update_review(
        Path(state["project"]), review_path=Path(state["preview"]["review_path"]),
        expected_revision_id=state["revision_id"],
    )
    if result.get("status") not in {"updated", "already_applied"}:
        raise TaskControlError("source_update_not_applied", "源更新尚未完成，请保留原审阅并检查项目。")
    state["source_update_outcome"] = result
    _phase(root, state, "exporting")  # Export retries must never prepare the source again.
    run_export(root, state)
