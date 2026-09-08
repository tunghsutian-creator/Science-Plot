"""Bind one Studio figure queue item to the source it actually renders."""

from __future__ import annotations

from typing import Any, NoReturn

from sciplot_core.figure_plan.execution import request_for_figure_task
from sciplot_core.figure_plan.metric_binding import CartesianMetricBinding
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS
from sciplot_core.mechanical_task_sources import MechanicalTaskSource
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding

from sciplot_core.studio_core.figure_requests import (
    _impact_condition_figure_request,
    _rheology_frequency_figure_request,
)


def figure_source_request(
    request: dict[str, Any],
    *,
    figure: dict[str, Any],
    task: FigureTask | None,
    figure_plan: ResolvedFigurePlan | None,
    queue_override: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], MaterializedTerminalSourceBinding | None]:
    """Return the task request plus any private materialized-source binding."""

    mechanical_source = _mechanical_task_source(
        figure,
        expected_task=task,
        expected_plan=figure_plan,
    )
    if mechanical_source is not None:
        assert task is not None
        projected = request_for_figure_task(request, task)
        projected["input"] = str(mechanical_source.source)
        projected["series_order"] = list(mechanical_source.binding.sample_order)
        projected["explicit_render_option_keys"] = list(
            mechanical_source.explicit_render_option_keys
        )
        projected["render_options"] = dict(mechanical_source.render_options)
        return projected, mechanical_source.binding
    if figure_plan is not None and figure_plan.rule_id == "rheology_frequency_sweep":
        # Task projection chooses data; the existing rheology owner also binds
        # this metric's label, unit and scale instead of inheriting the primary.
        return _rheology_frequency_figure_request(request, figure), None
    projected = (
        request_for_figure_task(request, task)
        if task is not None
        and figure_plan is not None
        and figure_plan.rule_id != "impact_metric"
        else _impact_condition_figure_request(request, figure)
        if queue_override is not None
        else _rheology_frequency_figure_request(request, figure)
    )
    return projected, None


def _mechanical_task_source(
    figure: dict[str, Any],
    *,
    expected_task: FigureTask | None,
    expected_plan: ResolvedFigurePlan | None,
) -> MechanicalTaskSource | None:
    value = figure.get("_mechanical_task_source")
    if value is None:
        return None
    if (
        not isinstance(value, MechanicalTaskSource)
        or expected_task is None
        or expected_plan is None
        or expected_plan.rule_id not in MECHANICAL_RULE_IDS
        or expected_task not in expected_plan.tasks
        or value.task != expected_task
        or not isinstance(expected_task.metric_binding, CartesianMetricBinding)
    ):
        _raise_mechanical_task_source_mismatch()
    expected_x = expected_task.metric_binding.x_metric
    expected_y = expected_task.metric_binding.y_metric
    binding = value.binding
    source = value.source.expanduser().resolve()
    if (
        value.source.is_symlink()
        or not source.is_file()
        or binding.task_key != expected_task.figure_id
        or binding.rule_id != expected_plan.rule_id
        or binding.template != expected_task.template
        or binding.x_metric != expected_x
        or binding.y_metric != expected_y
        or binding.terminal_source.path != str(source)
        or binding.sample_order != expected_task.sample_order
        or (
            value.render_options.get("x_metric"),
            value.render_options.get("y_metric"),
        )
        != (expected_x, expected_y)
    ):
        _raise_mechanical_task_source_mismatch()
    return value


def _raise_mechanical_task_source_mismatch() -> NoReturn:
    raise ValueError(
        "studio_figure_task_mismatch: mechanical task source does not "
        "match its selected FigureTask."
    )


__all__ = ["figure_source_request"]
