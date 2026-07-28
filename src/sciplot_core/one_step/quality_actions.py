"""Select deterministic quality actions from layout evidence."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.split import STACKED_TALL_FIGURE_HEIGHT_MM

from sciplot_core.one_step.quality_catalog import (
    _ISSUE_QUALITY_ACTIONS,
    _STACK_SPLIT_QUALITY_ACTION,
    _AUTOFIX_QUALITY_ACTIONS,
)


def _quality_action(
    template: dict[str, Any], *, status: str, evidence_id: str
) -> dict[str, Any]:
    action = {
        "id": str(template["id"]),
        "status": status,
        "label": str(template["label"]),
        "reason": str(template["reason"]),
        "evidence_id": evidence_id,
    }
    for key in (
        "render_options_patch",
        "clear_render_options",
        "figure_size_patch",
        "layout_strategy",
        "split_policy",
        "series_style_patch",
        "requires_rule_repair",
        "requires_human_confirmation",
    ):
        if key in template:
            action[key] = json_safe(template[key])
    action["can_apply_as_refine_draft"] = bool(
        action.get("render_options_patch")
        or action.get("clear_render_options")
        or action.get("figure_size_patch")
        or action.get("split_policy")
        or action.get("series_style_patch")
    )
    return action


def _layout_summary_height_mm(
    layout_summaries: list[dict[str, Any]] | None,
) -> float | None:
    heights: list[float] = []
    for summary in layout_summaries or []:
        if not isinstance(summary, dict):
            continue
        for key in ("requested_size_mm", "figure_size_mm"):
            value = summary.get(key)
            if not isinstance(value, list | tuple) or len(value) < 2:
                continue
            try:
                heights.append(float(value[1]))
            except (TypeError, ValueError):
                continue
    return max(heights) if heights else None


def _template_for_issue(
    issue_id: str,
    *,
    layout_summaries: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if issue_id == "stack_peak_too_small":
        height_mm = _layout_summary_height_mm(layout_summaries)
        if height_mm is not None and height_mm >= STACKED_TALL_FIGURE_HEIGHT_MM:
            return _STACK_SPLIT_QUALITY_ACTION
    return _ISSUE_QUALITY_ACTIONS.get(issue_id)


def build_quality_actions(
    *,
    issue_ids: list[str],
    autofixes_applied: list[str],
    layout_summaries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    handled: set[str] = set()
    for autofix in autofixes_applied:
        template = _AUTOFIX_QUALITY_ACTIONS.get(str(autofix))
        if not template:
            continue
        action = _quality_action(template, status="applied", evidence_id=str(autofix))
        actions.append(action)
        handled.add(str(action["id"]))
    for issue_id in issue_ids:
        template = _template_for_issue(str(issue_id), layout_summaries=layout_summaries)
        if not template:
            continue
        if str(template["id"]) in handled:
            continue
        actions.append(
            _quality_action(template, status="suggested", evidence_id=str(issue_id))
        )
        handled.add(str(template["id"]))
    return actions
