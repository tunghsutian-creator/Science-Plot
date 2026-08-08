"""Dispatch renderer-neutral categorical contracts by presentation kind."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_render.component_stack_contract import (
    _component_stack_contract,
)
from sciplot_core.studio_render.categorical_point_line import (
    categorical_point_line_contract,
)
from sciplot_core.studio_render.impact_point_line_contract import (
    _impact_point_line_contract,
)
from sciplot_core.studio_render.models import StudioSeries
from sciplot_core.studio_render.replicate_distribution_contract import (
    _replicate_distribution_contract,
)


def _categorical_plot_contract(
    series: list[StudioSeries],
    *,
    template_id: str,
    render_options: dict[str, Any],
) -> dict[str, Any] | None:
    point_line_contract = categorical_point_line_contract(
        series,
        template_id=template_id,
    )
    if point_line_contract is not None:
        return point_line_contract

    impact_contract = _impact_point_line_contract(
        series,
        template_id=template_id,
    )
    if impact_contract is not None:
        return impact_contract

    component_contract = _component_stack_contract(
        series,
        template_id=template_id,
        render_options=render_options,
    )
    if component_contract is not None:
        return component_contract

    return _replicate_distribution_contract(
        series,
        template_id=template_id,
        render_options=render_options,
    )
