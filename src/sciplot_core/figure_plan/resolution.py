"""Resolve Study Model recommendations and source facts into selected tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.constants import REQUIRED_FIGURE_PLAN_RULE_IDS
from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.impact_resolution import (
    resolve_impact_plan,
    stable_impact_figure_id,
)
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.figure_plan.preparation_validation import (
    validate_preparation_figure_plan,
)
from sciplot_core.figure_plan.source_binding import source_tree_sha256


def resolve_current_figure_plan(
    *,
    persisted: object,
    rule_id: str | None,
    template: str,
    study_model: dict[str, Any],
    input_path: Path | None,
    request: dict[str, Any],
) -> ResolvedFigurePlan | None:
    """Resolve current source facts and reject a stale or malformed saved plan."""

    try:
        persisted_plan = resolved_figure_plan_from_payload(persisted)
    except (TypeError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "invalid_resolved_figure_plan",
            f"The persisted figure plan is invalid: {exc}",
        ) from exc
    normalized_rule = str(rule_id or "").strip()
    if normalized_rule in REQUIRED_FIGURE_PLAN_RULE_IDS and input_path is None:
        raise FigurePlanResolutionError(
            "figure_plan_source_required",
            f"Figure planning for `{normalized_rule}` requires an explicit source.",
        )
    try:
        current_plan = resolve_figure_plan(
            rule_id=rule_id,
            template=template,
            study_model=study_model,
            input_path=input_path,
            request=request,
        )
    except FigurePlanResolutionError:
        raise
    except (OSError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "resolved_figure_plan_unavailable",
            f"SciPlot could not resolve the current figure plan: {exc}",
        ) from exc
    if current_plan is None and normalized_rule in REQUIRED_FIGURE_PLAN_RULE_IDS:
        raise FigurePlanResolutionError(
            "resolved_figure_plan_unavailable",
            f"SciPlot could not resolve a figure plan for `{normalized_rule}`.",
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
        current_plan is None or persisted_plan.plan_sha256 != current_plan.plan_sha256
    ):
        raise FigurePlanResolutionError(
            "stale_resolved_figure_plan",
            "The persisted figure plan no longer matches the current rule, "
            "template, Study Model, or source conditions.",
        )
    return current_plan


def resolve_preparation_figure_plan(
    *,
    persisted: object,
    rule_id: str | None,
    template: str,
    study_model: dict[str, Any],
    input_path: Path | None,
    request: dict[str, Any],
) -> ResolvedFigurePlan | None:
    """Resolve a new plan for a render that will replace generated artifacts.

    A preparation may refresh task selection after source or Study Model changes,
    but it may not silently discard an invalid plan or cross rule boundaries.
    Exact-current reuse and publication must use ``resolve_current_figure_plan``.
    """

    current_plan = resolve_current_figure_plan(
        persisted=None,
        rule_id=rule_id,
        template=template,
        study_model=study_model,
        input_path=input_path,
        request=request,
    )
    return validate_preparation_figure_plan(
        persisted=persisted,
        rule_id=rule_id,
        current_plan=current_plan,
    )


def resolve_figure_plan(
    *,
    rule_id: str | None,
    template: str,
    study_model: dict[str, Any],
    input_path: Path | None,
    request: dict[str, Any],
    dma_temperature_source_resolution: Any | None = None,
) -> ResolvedFigurePlan | None:
    """Resolve the current plan for supported rule families without writes."""

    normalized_rule = str(rule_id or "").strip()
    if not normalized_rule:
        return None
    from sciplot_core.materials_rules.catalog import get_rule

    try:
        adapter = get_rule(normalized_rule).figure_plan_adapter
    except ValueError:
        return None
    if adapter is None:
        return None
    if adapter == "dma_temperature":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "DMA temperature figure planning requires an explicit source path.",
            )
        from sciplot_core.figure_plan.dma_temperature_resolution import (
            resolve_dma_temperature_plan,
        )

        return resolve_dma_temperature_plan(
            input_path=input_path,
            request={**request, "template": template},
            source_resolution=dma_temperature_source_resolution,
        )
    if adapter == "registered_single_curve":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "Registered single-curve planning requires an explicit source path.",
            )
        from sciplot_core.semantic_sources.scientific_source import (
            ScientificSourceResolutionError,
            resolve_scientific_source,
        )

        try:
            source_resolution = resolve_scientific_source(
                input_path,
                rule_id=normalized_rule,
                request=request,
                template=template,
                study_model=study_model,
            )
        except ScientificSourceResolutionError as exc:
            raise FigurePlanResolutionError(exc.reason_code, str(exc)) from exc
        if source_resolution is None or source_resolution.figure_plan is None:
            raise FigurePlanResolutionError(
                "registered_single_curve_source_unavailable",
                "SciPlot could not resolve the registered single-curve source.",
            )
        return source_resolution.figure_plan
    if adapter == "mechanical":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "Mechanical figure planning requires an explicit source path.",
            )
        from sciplot_core.figure_plan.mechanical_resolution import (
            resolve_mechanical_plan,
        )

        return resolve_mechanical_plan(
            input_path=input_path,
            rule_id=normalized_rule,
            template=template,
            study_model=study_model,
            request=request,
        )
    if adapter == "performance":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "Performance figure planning requires an explicit source path.",
            )
        from sciplot_core.figure_plan.performance_resolution import (
            resolve_performance_plan,
        )

        return resolve_performance_plan(
            input_path=input_path,
            request=request,
        )
    if adapter == "rheology_temperature":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "Temperature figure planning requires an explicit source path.",
            )
        from sciplot_core.figure_plan.temperature_resolution import (
            resolve_temperature_plan,
        )

        return resolve_temperature_plan(
            input_path=input_path,
            request=request,
        )
    if adapter == "rheology_frequency":
        from sciplot_core.figure_plan.frequency_resolution import (
            resolve_frequency_plan,
        )

        return resolve_frequency_plan(
            study_model=study_model,
            input_path=input_path,
            request=request,
        )
    if adapter == "impact":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "Impact figure planning requires an explicit source path.",
            )
        return resolve_impact_plan(
            input_path=input_path,
            template=template,
            request=request,
            source_sha256=source_tree_sha256(input_path),
        )
    raise RuntimeError(f"Unknown FigurePlan adapter `{adapter}`.")


__all__ = [
    "FigurePlanResolutionError",
    "resolve_current_figure_plan",
    "resolve_preparation_figure_plan",
    "resolve_figure_plan",
    "stable_impact_figure_id",
]
