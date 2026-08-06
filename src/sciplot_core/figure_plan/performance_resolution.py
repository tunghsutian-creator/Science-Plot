"""Resolve performance-comparison source facts into a pure figure plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.performance_comparison import (
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PERFORMANCE_SCATTER_TEMPLATE_ID,
    PerformanceComparison,
    PerformanceComparisonError,
    build_performance_radar_payload,
    build_performance_scatter_payload,
    load_performance_comparison,
)

from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.metric_binding import (
    CartesianMetricBinding,
    OrderedMetricsBinding,
)
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.source_binding import source_tree_sha256
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.foundation.file_hashing import file_sha256


_PERFORMANCE_SCATTER_FIGURE_ID = "performance_scatter"
_PERFORMANCE_POLAR_FIGURE_ID = "performance_polar_curve"


def resolve_performance_plan(
    *,
    input_path: Path,
    request: dict[str, Any],
) -> ResolvedFigurePlan:
    """Resolve selected performance tasks from one stable source snapshot."""

    explicit = request.get("explicit_template_selection") is True
    templates = (
        (_explicit_template(request),)
        if explicit
        else (
            PERFORMANCE_SCATTER_TEMPLATE_ID,
            PERFORMANCE_RADAR_TEMPLATE_ID,
        )
    )
    try:
        source_sha256_before = source_tree_sha256(input_path)
        if source_sha256_before is None:
            raise FigurePlanResolutionError(
                "performance_source_unavailable",
                "SciPlot could not fingerprint the performance-comparison source.",
            )
        comparison = load_performance_comparison(input_path)
        source_sha256 = source_tree_sha256(input_path)
        if (
            source_sha256 != source_sha256_before
            or input_path.is_file()
            and comparison.source_sha256 != file_sha256(input_path)
        ):
            raise FigurePlanResolutionError(
                "performance_source_changed_during_resolution",
                "The performance-comparison source changed while its figure "
                "plan was being resolved.",
            )
        material_order = tuple(
            material.material_id for material in comparison.materials
        )
        tasks = tuple(
            _task_for_template(
                comparison,
                template=template,
                order=order,
                material_order=material_order,
            )
            for order, template in enumerate(templates, start=1)
        )
    except PerformanceComparisonError as exc:
        raise FigurePlanResolutionError(exc.reason_code, str(exc)) from exc
    except OSError as exc:
        raise FigurePlanResolutionError(
            "performance_source_unavailable",
            f"SciPlot could not read the performance-comparison source: {exc}",
        ) from exc
    return ResolvedFigurePlan.planned(
        rule_id="performance_comparison",
        selection_policy=(
            "explicit_supported_template" if explicit else "default_scatter_then_polar"
        ),
        primary_figure_id=tasks[0].figure_id,
        tasks=tasks,
        source_sha256=source_sha256,
    )


def _explicit_template(request: dict[str, Any]) -> str:
    requested = request.get("template")
    try:
        return resolve_rule_template(
            "performance_comparison",
            requested if isinstance(requested, str) else None,
        )
    except ValueError as exc:
        raise FigurePlanResolutionError(
            "performance_template_invalid",
            str(exc),
        ) from exc


def _task_for_template(
    comparison: PerformanceComparison,
    *,
    template: str,
    order: int,
    material_order: tuple[str, ...],
) -> FigureTask:
    if template == PERFORMANCE_SCATTER_TEMPLATE_ID:
        build_performance_scatter_payload(comparison)
        x_metric, y_metric = comparison.scatter_metrics
        return FigureTask.with_metric_binding(
            figure_id=_PERFORMANCE_SCATTER_FIGURE_ID,
            order=order,
            title="Performance comparison scatter",
            metric_binding=CartesianMetricBinding(
                x_metric=x_metric.metric_id,
                y_metric=y_metric.metric_id,
            ),
            template=template,
            artifact_stem=_PERFORMANCE_SCATTER_FIGURE_ID,
            document_stem=_PERFORMANCE_SCATTER_FIGURE_ID,
            sample_order=material_order,
        )
    if template == PERFORMANCE_RADAR_TEMPLATE_ID:
        build_performance_radar_payload(comparison)
        return FigureTask.with_metric_binding(
            figure_id=_PERFORMANCE_POLAR_FIGURE_ID,
            order=order,
            title="Performance comparison polar curve",
            metric_binding=OrderedMetricsBinding(
                metric_ids=tuple(
                    metric.metric_id for metric in comparison.radar_metrics
                )
            ),
            template=template,
            artifact_stem=_PERFORMANCE_POLAR_FIGURE_ID,
            document_stem=_PERFORMANCE_POLAR_FIGURE_ID,
            sample_order=material_order,
        )
    raise FigurePlanResolutionError(
        "performance_template_invalid",
        f"Unsupported performance-comparison template: {template!r}.",
    )


__all__ = ["resolve_performance_plan"]
