"""Validate an already-resolved current FigurePlan for preparation."""

from __future__ import annotations

from sciplot_core.figure_plan.constants import REQUIRED_FIGURE_PLAN_RULE_IDS
from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)


def validate_preparation_figure_plan(
    *,
    persisted: object,
    rule_id: str | None,
    current_plan: ResolvedFigurePlan | None,
) -> ResolvedFigurePlan | None:
    """Accept one already-resolved current plan without reading its source again."""

    try:
        persisted_plan = resolved_figure_plan_from_payload(persisted)
    except (TypeError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "invalid_resolved_figure_plan",
            f"The persisted figure plan is invalid: {exc}",
        ) from exc
    normalized_rule = str(rule_id or "").strip()
    if current_plan is None and normalized_rule in REQUIRED_FIGURE_PLAN_RULE_IDS:
        raise FigurePlanResolutionError(
            "resolved_figure_plan_unavailable",
            f"SciPlot could not resolve a figure plan for `{normalized_rule}`.",
        )
    if current_plan is not None and current_plan.rule_id != normalized_rule:
        raise FigurePlanResolutionError(
            "stale_resolved_figure_plan",
            "The resolved figure plan does not match the current rule.",
        )
    if (
        current_plan is not None
        and normalized_rule in REQUIRED_FIGURE_PLAN_RULE_IDS
        and current_plan.source_sha256 is None
    ):
        raise FigurePlanResolutionError(
            "figure_plan_source_unavailable",
            f"SciPlot could not fingerprint the source for `{normalized_rule}`.",
        )
    if persisted_plan is not None and (
        current_plan is None or persisted_plan.rule_id != current_plan.rule_id
    ):
        raise FigurePlanResolutionError(
            "stale_resolved_figure_plan",
            "The persisted figure plan cannot be refreshed across rule boundaries.",
        )
    return current_plan


__all__ = ["validate_preparation_figure_plan"]
