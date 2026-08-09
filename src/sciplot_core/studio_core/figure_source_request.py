"""Bind one Studio figure queue item to the source it actually renders."""

from __future__ import annotations

from typing import Any

from sciplot_core.figure_plan.execution import request_for_figure_task
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
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
) -> Any:
    value = figure.get("_mechanical_task_source")
    if value is None:
        return None
    from sciplot_core.mechanical_task_sources import MechanicalTaskSource

    if (
        not isinstance(value, MechanicalTaskSource)
        or expected_task is None
        or value.task != expected_task
        or not value.source.is_file()
    ):
        raise ValueError(
            "studio_figure_task_mismatch: mechanical task source does not "
            "match its selected FigureTask."
        )
    return value


__all__ = ["figure_source_request"]
