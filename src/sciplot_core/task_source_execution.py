"""Task checkpoints around reviewed source revisions and exact-current export."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_execution import _phase, run_export
from sciplot_core.task_planning import assert_source_current
from sciplot_core.task_source_update import apply_source_update_review, prepare_source_update_review
from sciplot_core.task_storage import save_task
from sciplot_core.task_column_mapping import column_question, mapped_plan_request, pause_for_columns


def run_source_preview(root: Path, state: dict[str, Any]) -> None:
    source = assert_source_current(state)
    request = state["request"]
    previous = json.loads((Path(request["project"]) / "plot_request.json").read_text())
    requires_mapping = request.get("choose_columns") or any(
        key in previous for key in ("data_mapping", "data_mapping_application", "data_mapping_execution", "data_mapping_proposal_id", "data_mapping_plan_binding")
    )
    if requires_mapping and not state.get("mapping_choice"):
        selected = {key: previous[key] for key in ("rule_id", "template")}
        question = column_question(source, selected, explicit=True)
        if question is None:
            raise TaskControlError("column_mapping_unsupported", "更新需要重新选择当前原始列。")
        question["message"] += " 此次更新必须重新核验映射，旧列位置不会自动复用。"
        from sciplot_core.foundation.json_hashing import canonical_json_sha256
        question["question_id"] = canonical_json_sha256({k: v for k, v in question.items() if k != "question_id"}, allow_nan=False)
        pause_for_columns(state, question)
        save_task(root, state)
        return
    mapping_request = mapped_plan_request(state) if state.get("mapping_choice") else None
    _phase(root, state, "previewing")
    index = int(state.get("preview_attempt", 0)) + 1
    state["preview_attempt"] = index
    save_task(root, state)
    review = prepare_source_update_review(
        Path(request["project"]), source, worksheet=request.get("worksheet"),
        review_path=root / f"source_review_{index:03}.json",
        **({"mapping_request": mapping_request} if mapping_request else {}),
        **({"annotation_decisions": state["annotation_decisions"]} if "annotation_decisions" in state else {}),
    )
    state.update(project=review["project"], revision_id=review["revision_id"])
    if review["status"] == "needs_annotation_choices":
        state.pop("mapping_error", None)
        state.pop("annotation_error", None)
        state.update(status="needs_input", phase="scientific_choice", previews=review["previews"],
            question={"field": "annotation_rebinding", "reason_code": "annotation_rebinding_required",
                "message": "请检查原图和候选图中的峰位置；图中 P 编号对应候选记录的 preview_marker、样品及数值。对每个待处理注释选择 rebind/remove/replace。重绑需指定当前候选 ID 和确认后的文字。固定注释默认保持原位置。",
                "revision_id": review["revision_id"], "evidence": review["source_update"]["annotation_review"],
                "review_path": review["review_path"]})
        save_task(root, state)
        return
    if review["status"] != "ready":
        reason = review["source_update"].get("reason", "源更新预览未就绪。")
        if state.get("mapping_choice") and reason.startswith("Fresh source mapping cannot prepare"):
            choice = state.pop("mapping_choice")
            state.pop("data_mapping", None)
            pause_for_columns(state, choice["question"])
            state["mapping_error"] = {"reason_code": "source_mapping_invalid", "message": reason}
            save_task(root, state)
            return
        state.update(status="blocked", blocker={
            "reason_code": "source_update_blocked",
            "message": reason,
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
    state.pop("question", None)
    state.pop("annotation_error", None)
    state.pop("mapping_error", None)
    save_task(root, state)


def accept_annotation_response(root: Path, state: dict[str, Any], response: dict[str, Any]) -> None:
    from copy import deepcopy
    from jsonschema import Draft202012Validator, ValidationError
    from sciplot_core.task_choice_schema import annotation_response_schema
    from sciplot_core.studio_core.source_update_commit import project_inventory
    from sciplot_core.studio_core.source_update_review import payload_hash

    try:
        Draft202012Validator(annotation_response_schema()).validate(response)
    except ValidationError as exc:
        raise TaskControlError("invalid_task_response", "请使用 annotation_choices 的公布字段并附当前 expected_revision_id。") from exc
    if response["expected_revision_id"] != state["revision_id"]:
        raise TaskControlError("stale_source_review", "此答案对应旧源更新预览。")
    review = json.loads(Path(state["question"]["review_path"]).read_text())
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    if canonical_json_sha256({k: v for k, v in review.items() if k != "revision_id"}, allow_nan=False) != state["revision_id"]:
        raise TaskControlError("stale_source_review", "注释审阅记录已变化。")
    if payload_hash(project_inventory(Path(state["request"]["project"]))) != review["source_update"]["project_sha256"]:
        raise TaskControlError("stale_source_review", "项目已变化，请重新开始源更新审阅。")
    previous = deepcopy(state)
    incoming = response["annotation_choices"]
    identities = [(item.get("figure_id"), item.get("id")) for item in incoming]
    if len(identities) != len(set(identities)):
        raise TaskControlError("invalid_task_response", "同一注释不能重复回答。")
    state["annotation_decisions"] = [
        item for item in state.get("annotation_decisions", [])
        if (item.get("figure_id"), item.get("id")) not in identities
    ] + incoming
    save_task(root, state)
    run_source_preview(root, state)
    if state["status"] == "blocked":
        error, attempt = state.get("blocker"), state.get("preview_attempt")
        state.clear()
        state.update(previous, annotation_error=error, preview_attempt=attempt)
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
