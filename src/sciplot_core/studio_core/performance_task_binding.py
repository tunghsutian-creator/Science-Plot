"""Bind one prepared performance payload to its exact selected task."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.figure_plan.metric_binding import (
    CartesianMetricBinding,
    OrderedMetricsBinding,
)
from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.figure_plan.source_binding import source_tree_sha256
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.studio_render.models import StudioPreparationBlocked


def validate_performance_payload_task(
    payload: dict[str, Any],
    *,
    request: dict[str, Any],
    authority_source: Path,
) -> FigureTask | None:
    """Reject any task/template/metric/material/source identity divergence."""

    task_value = request.get("resolved_figure_task")
    if task_value is None:
        return None
    try:
        task = FigureTask.from_payload(task_value)
        plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    except (TypeError, ValueError) as exc:
        _mismatch(f"Invalid performance task authority: {exc}")
    if task.template != payload.get("template"):
        _mismatch("Prepared performance template does not match its FigureTask.")
    actual_order = tuple(
        str(item.get("label") or "")
        for item in payload.get("series", [])
        if isinstance(item, dict)
    )
    if task.sample_order and actual_order != task.sample_order:
        _mismatch("Prepared performance material order does not match its FigureTask.")
    binding = task.metric_binding
    if isinstance(binding, CartesianMetricBinding):
        actual_binding = (
            str(
                payload.get("x_metric", {}).get("metric_id")
                if isinstance(payload.get("x_metric"), dict)
                else ""
            ),
            str(
                payload.get("y_metric", {}).get("metric_id")
                if isinstance(payload.get("y_metric"), dict)
                else ""
            ),
        )
        if actual_binding != (binding.x_metric, binding.y_metric):
            _mismatch("Prepared Cartesian metrics do not match their FigureTask.")
    elif isinstance(binding, OrderedMetricsBinding):
        actual_metrics = tuple(
            str(item.get("metric_id") or "")
            for item in payload.get("metrics", [])
            if isinstance(item, dict)
        )
        if actual_metrics != binding.metric_ids:
            _mismatch("Prepared ordered metrics do not match their FigureTask.")
    else:
        _mismatch("Performance FigureTask has an unsupported metric binding.")
    if plan is not None:
        selected = next(
            (item for item in plan.tasks if item.figure_id == task.figure_id),
            None,
        )
        if (
            plan.rule_id != "performance_comparison"
            or selected != task
            or plan.source_sha256 != source_tree_sha256(authority_source)
        ):
            _mismatch("Prepared performance payload diverges from its FigurePlan.")
    return task


def _mismatch(message: str) -> NoReturn:
    raise StudioPreparationBlocked("performance_figure_task_mismatch", message)


__all__ = ["validate_performance_payload_task"]
