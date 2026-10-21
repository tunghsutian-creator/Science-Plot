"""Measure explicitly bound categorical keys without changing retained algorithms."""
from __future__ import annotations

import math
from typing import Any

from sciplot_core.studio_render.axis_contract import _veusz_axis_contract
from sciplot_core.studio_render.axis_extent import _expand_axis_for_visual_extents
from sciplot_core.studio_render.categorical_plot_spec import _categorical_plot_contract
from sciplot_core.studio_render.domain_defaults import _explicit_render_options
from sciplot_core.studio_render.legend_placement import (
    _auto_inside_legend_placement, _legend_curve_samples, _legend_footprint,
    _point_rectangle_distance_mm,
)
from sciplot_core.studio_render.legend_visibility import _legend_columns
from sciplot_core.studio_render.models import StudioPreparationBlocked, StudioSeries, _VeuszAxisContract
from sciplot_core.studio_render.style_contract import _veusz_style_contract
from sciplot_core.studio_render.value_parsing import _size_mm


def legend_columns(*, series_count: int, mode: str = "inside_best",
                   max_label_length: int = 0, figure_width_mm: float | None = None,
                   requested: object = None) -> int:
    if requested is None:
        return _legend_columns(series_count=series_count, mode=mode,
            max_label_length=max_label_length, figure_width_mm=figure_width_mm)
    if type(requested) is not int or not 1 <= requested <= 12:
        raise StudioPreparationBlocked("invalid_legend_columns", "Legend columns must be an explicit integer from 1 to 12.")
    return requested


def categorical_legend_axis(series: list[StudioSeries], options: dict[str, Any], *,
                             request: dict[str, Any], template_id: str,
                             source_bindings: dict[str, Any] | None = None) -> _VeuszAxisContract:
    """Use exactly the final writer's compact-domain and physical-extent owners."""
    axis = _veusz_axis_contract(options, template_id=template_id, series=series,
        explicit_render_options=_explicit_render_options(request))
    width, height = _size_mm(str(options.get("size") or "60x55"))
    expanded, _ = _expand_axis_for_visual_extents(axis, request=request,
        render_options=options, template_id=template_id, series=series,
        categorical_contract=_categorical_plot_contract(series, template_id=template_id, render_options=options, source_bindings=source_bindings),
        style=_veusz_style_contract(options), width_mm=width, height_mm=height)
    return expanded


def _bound_footprint(series: list[StudioSeries], options: dict[str, Any], columns: int) -> dict[str, float]:
    # Reuse the retained one-column physical measurement. Expanding its cells
    # changes only this new request's native key grid, never its curve samples.
    widest = max(series, key=lambda item: len(str(item.label)))
    cell = _legend_footprint([widest], options)
    font = float(cell["font_height_mm"])
    margin = 0.15 * font if _veusz_style_contract(options).legend_frameon else 0.0
    rows = max(1, math.ceil(len(series) / columns))
    graph_width, graph_height = float(cell["graph_width_mm"]), float(cell["graph_height_mm"])
    width = (float(cell["box_width_mm"]) - 2 * margin) * columns + font * (columns - 1) + 2 * margin
    return {**{key: float(value) for key, value in cell.items()}, "columns": float(columns),
        "rows": float(rows), "box_width_mm": min(width, graph_width * 0.92),
        "box_height_mm": min(rows * font + margin, graph_height * 0.82)}


def _measure_bound_columns(placement: dict[str, Any], series: list[StudioSeries],
                           options: dict[str, Any], template_id: str, columns: int) -> dict[str, Any]:
    footprint = _bound_footprint(series, options, columns)
    graph_width, graph_height = footprint["graph_width_mm"], footprint["graph_height_mm"]
    width, height = footprint["box_width_mm"] / graph_width, footprint["box_height_mm"] / graph_height
    axis = _veusz_axis_contract(options, template_id=template_id, series=series)
    samples = _legend_curve_samples(series, options, axis_contract=axis)
    required = float(placement["required_curve_clearance_mm"])
    metrics: dict[str, Any] = {}
    for name, candidate in placement["candidates"].items():
        left, right, bottom, top = map(float, candidate["rectangle_fraction"])
        if name.endswith("left"):
            left = min(left, max(0.0, 1.0 - width))
            right = left + width
        else:
            right = max(right, width)
            left = right - width
        if name.startswith("lower"):
            bottom = min(bottom, max(0.0, 1.0 - height))
            top = bottom + height
        else:
            top = max(top, height)
            bottom = top - height
        rectangle = (left, right, bottom, top)
        distances = [_point_rectangle_distance_mm(point, rectangle,
            graph_width_mm=graph_width, graph_height_mm=graph_height) for point in samples]
        minimum = min(distances, default=float("inf"))
        metrics[name] = {"rectangle_fraction": [round(value, 6) for value in rectangle],
            "overlap_samples": sum(value <= 1e-9 for value in distances),
            "near_samples": sum(value < required for value in distances),
            "minimum_curve_clearance_mm": round(minimum, 6) if math.isfinite(minimum) else None,
            "clearance_deficit_mm": round(max(required - minimum, 0.0), 6),
            "proximity_load": round(sum((required - value) / required for value in distances
                if required > 0.0 and value < required), 6)}
    return {**placement, "footprint": {key: round(value, 6) for key, value in footprint.items()},
        "candidates": metrics}


def categorical_legend_placement(series: list[StudioSeries], options: dict[str, Any], *,
                                 request: dict[str, Any], template_id: str,
                                 position: str | None = None) -> dict[str, Any]:
    from sciplot_core.mapping_contract.categorical import validate_categorical_context

    validate_categorical_context(request)
    axis = categorical_legend_axis(series, options, request=request, template_id=template_id)
    measured_options = {**options, "x_min": axis.x_min, "x_max": axis.x_max,
        "y_min": axis.y_min, "y_max": axis.y_max, "x_ticks": list(axis.x_ticks), "y_ticks": list(axis.y_ticks)}
    placement = _auto_inside_legend_placement(series, measured_options, template_id=template_id)
    requested = request["categorical_binding"].get("legend_columns")
    if requested is not None and series:
        placement = _measure_bound_columns(placement, series, measured_options, template_id,
            legend_columns(series_count=len(series), requested=requested))
    # Keep the retained auto choice, or the explicitly requested corner. This
    # adapter measures the actual grid; it does not introduce another scorer.
    selected = position or str(placement["position"])
    minimum = placement["candidates"][selected]["minimum_curve_clearance_mm"]
    return {**placement, "position": selected, "minimum_curve_clearance_mm": minimum,
        "measurement_axes": {"x": [axis.x_min, axis.x_max], "y": [axis.y_min, axis.y_max]},
        "clearance_status": "safe" if minimum is None or minimum >= placement["required_curve_clearance_mm"] else "best_available_needs_reserve"}
