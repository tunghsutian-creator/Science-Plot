"""Pure failure classification over stable codes; no text guessing or mutation."""

from typing import Any


_OPERATION_ERRORS = frozenset({
    "invalid_operations", "invalid_operation", "unsupported_operation", "invalid_sample_style",
    "unknown_sample_style_target", "ambiguous_sample_style_target", "unsupported_sample_style",
    "invalid_coordinate", "unit_mismatch", "coordinate_out_of_bounds", "invalid_annotation_id",
    "invalid_annotation_text", "unsupported_annotation_scope", "duplicate_axis_range",
    "duplicate_annotation_id", "annotation_limit", "invalid_axis_range", "unsupported_axis_range",
    "axis_clipping_not_authorized", "invalid_style_value",
})
_STALE_ERRORS = frozenset({
    "stale_revision", "stale_annotation", "stale_peak_candidate", "stale_axis_range",
    "stale_task_preview", "task_review_changed",
})


def recovery_action(state: dict[str, Any], code: str) -> str:
    """Classify only known safe continuations, preserving uncertain writes."""
    phase = state["phase"]
    if code == "source_changed":
        return "resolve_source_change"
    if code == "project_busy":
        return "release_project_then_retry"
    if code == "task_worker_timeout" and phase in {"previewing", "applying", "exporting"}:
        return "retry_same_task"
    if phase == "previewing" and state["request"]["action"] == "edit":
        if code in _STALE_ERRORS:
            return "refresh_edit_context"
        if code in _OPERATION_ERRORS:
            return "revise_operations"
    return "inspect_diagnostics"


def refresh_context_argv(state: dict[str, Any]) -> list[str]:
    """Name exactly the read needed after a stale edit, not a stale task target."""
    request = state["request"]
    revisions = state.get("edit_revisions") or []
    operations = revisions[-1]["revise_operations"] if revisions else request["operations"]
    command = ["sciplot", "task", "edit-context", request["project"]]
    for name in sorted({item["op"] for item in operations}):
        command.extend(["--operation", name])
    if request.get("figure_id"):
        command.extend(["--figure", request["figure_id"]])
    return [*command, "--json"]
