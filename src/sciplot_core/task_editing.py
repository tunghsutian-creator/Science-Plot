"""Pure task edit decisions; native validation and writes keep their existing owners."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_core.annotation_schema import validate_operation_batch
from sciplot_core.task_contract import TaskControlError, validate_task_request


def current_edit_request(state: dict[str, Any]) -> dict[str, Any]:
    revisions = state.get("edit_revisions") or []
    if not revisions:
        return dict(state["request"])
    return {**state["request"], "operations": revisions[-1]["revise_operations"]}


def _revision_binding(response: dict[str, Any]) -> tuple[str, Any]:
    for key in ("expected_operation_id", "expected_preview_revision"):
        if set(response) == {"revise_operations", key}:
            expected = response[key]
            valid = (type(expected) is int and expected >= 1) if key == "expected_preview_revision" else (
                isinstance(expected, str) and len(expected) == 64
                and all(c in "0123456789abcdef" for c in expected))
            if valid:
                return key, expected
            break
    raise TaskControlError("invalid_task_response", "提供新操作及当前预览标识；预览失败时使用当前 expected_preview_revision，两者不能混用。")


def begin_preview_revision(state: dict[str, Any], response: dict[str, Any]) -> bool:
    """Validate before changing state; an identical latest submission is a receipt retry."""
    key, expected = _revision_binding(response)
    revisions = state.get("edit_revisions") or []
    if revisions and response == revisions[-1]:
        return False
    failed_preview = (state["status"] == "blocked" and state["phase"] == "previewing")
    if (state["request"]["action"] != "edit" or state.get("preview_accepted") is True
            or "applied_operation" in state or not (failed_preview or state["status"] == "needs_review")):
        raise TaskControlError("task_not_revisable", "只能修订尚未接受的调图预览或失败的预览；不确定的应用需先恢复。")
    required_key = "expected_preview_revision" if failed_preview else "expected_operation_id"
    current = len(revisions) + 1 if failed_preview else state.get("operation_id")
    if key != required_key or expected != current:
        raise TaskControlError("stale_task_preview", "预览已变化，请查询当前预览后再修订。")
    try:
        request = validate_task_request({**state["request"], "operations": response["revise_operations"]})
        validate_operation_batch(request["operations"])
    except (ValueError, TypeError) as exc:
        raise TaskControlError("invalid_task_response", str(exc)) from exc
    if failed_preview:
        state["preview_failures"] = [*state.get("preview_failures", []), {
            "preview_revision": current, "preview_attempt": state.get("preview_attempt"),
            "blocker": dict(state.get("blocker") or {}),
        }]
    state["edit_revisions"] = [*revisions, {key: expected, "revise_operations": request["operations"]}]
    # Old files remain in their attempt directories; no old preview can be accepted
    # while the replacement is being built or has failed.
    for key in ("preview", "operation_id", "preview_accepted", "result", "edit_outcome"):
        state.pop(key, None)
    return True


def validate_preview_response(state: dict[str, Any], response: dict[str, Any]) -> None:
    if (
        set(response) - {"accept_preview", "expected_operation_id"}
        or type(response.get("accept_preview")) is not bool
    ):
        raise TaskControlError("invalid_task_response", "请返回是否采纳当前预览。")
    # First previews retain the original API. Once superseded, every acceptance
    # or rejection must name the image the caller actually reviewed.
    if "expected_operation_id" in response or state.get("edit_revisions"):
        if response.get("expected_operation_id") != state.get("operation_id"):
            raise TaskControlError("stale_task_preview", "请提供当前预览的 expected_operation_id，旧预览答复不能用于新预览。")


def unchanged_style_review(review: dict[str, Any]) -> bool:
    """Only native-normalized, audited pure style batches can bypass visual review."""
    operations, changes = review.get("operations"), review.get("actual_changes")
    return bool(
        review.get("kind") == "sciplot_document_edit_preview"
        and review.get("version") == 2 and review.get("status") == "ready"
        and (review.get("scientific_audit") or {}).get("status") == "passed"
        and isinstance(operations, list) and operations
        and all(isinstance(op, dict) and op.get("op") == "set_style" for op in operations)
        and isinstance(changes, list) and len(changes) == len(operations)
        and all(isinstance(change, dict) and {"old_value", "new_value"} <= change.keys()
                and change["old_value"] == change["new_value"] for change in changes)
    )
