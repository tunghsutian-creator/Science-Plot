"""Measure legend geometry and choose an unobstructed inside placement."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    DEFAULT_LEGEND_CURVE_CLEARANCE_MM,
    DEFAULT_LEGEND_EDGE_PADDING_MM,
    UNIFIED_LEGEND_KEY_LENGTH_MM,
    anchored_log_decade_ticks,
)

from sciplot_core.studio_render.models import (
    StudioSeries,
    _VeuszAxisContract,
)

from sciplot_core.studio_render.style_contract import (
    _veusz_style_contract,
)

from sciplot_core.studio_render.label_density import (
    _label_load,
)

from sciplot_core.studio_render.axis_scale import (
    _axis_scale,
)

from sciplot_core.studio_render.axis_contract import (
    _veusz_axis_contract,
)

from sciplot_core.studio_render.legend_visibility import (
    _legend_columns,
)

from sciplot_core.studio_render.value_parsing import (
    _size_mm,
    _optional_float,
)


def _legend_axis_bounds(
    series: list[StudioSeries],
    render_options: dict[str, Any],
    axis: str,
    *,
    axis_contract: _VeuszAxisContract | None = None,
) -> tuple[float, float, str] | None:
    values = [
        float(value)
        for item in series
        for value in (item.x_values if axis == "x" else item.y_values)
        if math.isfinite(float(value))
    ]
    scale = _axis_scale(render_options, axis)
    if scale == "log":
        values = [value for value in values if value > 0]
    if not values:
        return None
    if axis_contract is not None:
        minimum = _optional_float(getattr(axis_contract, f"{axis}_min"))
        maximum = _optional_float(getattr(axis_contract, f"{axis}_max"))
        if (
            minimum is not None
            and maximum is not None
            and not math.isclose(minimum, maximum)
        ):
            if scale == "log":
                if minimum <= 0.0 or maximum <= 0.0:
                    return None
                return math.log10(minimum), math.log10(maximum), scale
            return minimum, maximum, scale
    minimum = _optional_float(render_options.get(f"{axis}_min"))
    maximum = _optional_float(render_options.get(f"{axis}_max"))
    minimum = min(values) if minimum is None else minimum
    maximum = max(values) if maximum is None else maximum
    if scale == "log":
        ticks = anchored_log_decade_ticks(values)
        if ticks:
            minimum = min(minimum, ticks[0])
            maximum = max(maximum, ticks[-1])
        if minimum <= 0 or maximum <= minimum:
            return None
        return math.log10(minimum), math.log10(maximum), scale
    if maximum <= minimum:
        return None
    padding = (maximum - minimum) * 0.05
    return minimum - padding, maximum + padding, scale


def _legend_curve_samples(
    series: list[StudioSeries],
    render_options: dict[str, Any],
    *,
    axis_contract: _VeuszAxisContract | None = None,
) -> list[tuple[float, float]]:
    x_bounds = _legend_axis_bounds(
        series, render_options, "x", axis_contract=axis_contract
    )
    y_bounds = _legend_axis_bounds(
        series, render_options, "y", axis_contract=axis_contract
    )
    if x_bounds is None or y_bounds is None:
        return []
    x_low, x_high, x_scale = x_bounds
    y_low, y_high, y_scale = y_bounds

    def normalized(value: float, low: float, high: float, scale: str) -> float | None:
        if scale == "log":
            if value <= 0:
                return None
            value = math.log10(value)
        return (value - low) / (high - low)

    samples: list[tuple[float, float]] = []
    for item in series:
        points: list[tuple[float, float]] = []
        for x_value, y_value in zip(item.x_values, item.y_values, strict=True):
            x_norm = normalized(float(x_value), x_low, x_high, x_scale)
            y_norm = normalized(float(y_value), y_low, y_high, y_scale)
            if x_norm is None or y_norm is None:
                continue
            if (
                math.isfinite(x_norm)
                and math.isfinite(y_norm)
                and 0.0 <= x_norm <= 1.0
                and 0.0 <= y_norm <= 1.0
            ):
                points.append((x_norm, y_norm))
        for index, point in enumerate(points):
            samples.append(point)
            if index == 0:
                continue
            previous = points[index - 1]
            for step in range(1, 5):
                fraction = step / 5.0
                samples.append(
                    (
                        previous[0] + (point[0] - previous[0]) * fraction,
                        previous[1] + (point[1] - previous[1]) * fraction,
                    )
                )
    return samples


def _legend_footprint(
    series: list[StudioSeries],
    render_options: dict[str, Any],
) -> dict[str, float | int]:
    """Estimate Veusz's graph-local key box in final physical units."""

    style = _veusz_style_contract(render_options)
    width_mm, height_mm = _size_mm(str(render_options.get("size") or "60x55"))
    graph_width_mm = max(
        float(width_mm) - style.left_margin_mm - style.right_margin_mm, 1.0
    )
    graph_height_mm = max(
        float(height_mm) - style.top_margin_mm - style.bottom_margin_mm, 1.0
    )
    load = _label_load(series)
    columns = _legend_columns(
        series_count=load["series_count"],
        mode="inside_best",
        max_label_length=load["max_label_length"],
        figure_width_mm=float(width_mm),
    )
    rows = max(1, math.ceil(load["series_count"] / columns))
    point_to_mm = 25.4 / 72.0
    font_height_mm = max(style.legend_font_size_pt * 1.2 * point_to_mm, 0.1)
    max_text_width_mm = max(
        load["max_label_length"] * style.legend_font_size_pt * 0.56 * point_to_mm, 0.2
    )
    key_length_mm = UNIFIED_LEGEND_KEY_LENGTH_MM
    box_width_mm = (
        max_text_width_mm + font_height_mm + key_length_mm
    ) * columns + font_height_mm * (columns - 1)
    box_height_mm = rows * font_height_mm
    if style.legend_frameon:
        margin_mm = 0.15 * font_height_mm
        box_width_mm += 2.0 * margin_mm
        box_height_mm += margin_mm
    return {
        "columns": columns,
        "rows": rows,
        "font_height_mm": font_height_mm,
        "graph_width_mm": graph_width_mm,
        "graph_height_mm": graph_height_mm,
        "box_width_mm": min(box_width_mm, graph_width_mm * 0.92),
        "box_height_mm": min(box_height_mm, graph_height_mm * 0.82),
    }


def _point_rectangle_distance_mm(
    point: tuple[float, float],
    rectangle: tuple[float, float, float, float],
    *,
    graph_width_mm: float,
    graph_height_mm: float,
) -> float:
    x_value, y_value = point
    left, right, bottom, top = rectangle
    dx = max(left - x_value, 0.0, x_value - right) * graph_width_mm
    dy = max(bottom - y_value, 0.0, y_value - top) * graph_height_mm
    return math.hypot(dx, dy)


def _auto_inside_legend_placement(
    series: list[StudioSeries],
    render_options: dict[str, Any],
    *,
    template_id: str,
) -> dict[str, Any]:
    axis_contract = _veusz_axis_contract(
        render_options, template_id=template_id, series=series
    )
    samples = _legend_curve_samples(series, render_options, axis_contract=axis_contract)
    footprint = _legend_footprint(series, render_options)
    graph_width_mm = float(footprint["graph_width_mm"])
    graph_height_mm = float(footprint["graph_height_mm"])
    width = float(footprint["box_width_mm"]) / graph_width_mm
    height = float(footprint["box_height_mm"]) / graph_height_mm
    edge_padding_mm = max(
        0.0,
        _optional_float(render_options.get("legend_edge_padding_mm"))
        or DEFAULT_LEGEND_EDGE_PADDING_MM,
    )
    horizontal_pad = min(edge_padding_mm / graph_width_mm, max(0.0, 1.0 - width))
    vertical_pad = min(edge_padding_mm / graph_height_mm, max(0.0, 1.0 - height))
    candidates = {
        "upper_right": (
            1.0 - horizontal_pad - width,
            1.0 - horizontal_pad,
            1.0 - vertical_pad - height,
            1.0 - vertical_pad,
        ),
        "lower_right": (
            1.0 - horizontal_pad - width,
            1.0 - horizontal_pad,
            vertical_pad,
            vertical_pad + height,
        ),
        "upper_left": (
            horizontal_pad,
            horizontal_pad + width,
            1.0 - vertical_pad - height,
            1.0 - vertical_pad,
        ),
        "lower_left": (
            horizontal_pad,
            horizontal_pad + width,
            vertical_pad,
            vertical_pad + height,
        ),
    }
    clearance_mm = max(
        0.0,
        _optional_float(render_options.get("legend_curve_clearance_mm"))
        or DEFAULT_LEGEND_CURVE_CLEARANCE_MM,
    )
    order = ("upper_right", "lower_right", "upper_left", "lower_left")
    metrics: dict[str, dict[str, Any]] = {}
    for name, rectangle in candidates.items():
        distances = [
            _point_rectangle_distance_mm(
                point,
                rectangle,
                graph_width_mm=graph_width_mm,
                graph_height_mm=graph_height_mm,
            )
            for point in samples
        ]
        minimum = min(distances, default=float("inf"))
        overlaps = sum(distance <= 1e-9 for distance in distances)
        near = sum(distance < clearance_mm for distance in distances)
        proximity_load = sum(
            (clearance_mm - distance) / clearance_mm
            for distance in distances
            if clearance_mm > 0.0 and distance < clearance_mm
        )
        metrics[name] = {
            "rectangle_fraction": [round(value, 6) for value in rectangle],
            "overlap_samples": overlaps,
            "near_samples": near,
            "minimum_curve_clearance_mm": None
            if not math.isfinite(minimum)
            else round(minimum, 6),
            "clearance_deficit_mm": (
                0.0
                if not math.isfinite(minimum)
                else round(max(clearance_mm - minimum, 0.0), 6)
            ),
            "proximity_load": round(proximity_load, 6),
        }

    def score(name: str) -> tuple[Any, ...]:
        item = metrics[name]
        minimum = item["minimum_curve_clearance_mm"]
        safe = minimum is None or float(minimum) >= clearance_mm
        return (
            int(item["overlap_samples"] > 0),
            int(item["overlap_samples"]),
            int(not safe),
            float(item["proximity_load"]),
            float(item["clearance_deficit_mm"]),
            -(float(minimum) if minimum is not None else float("inf")),
            order.index(name),
        )

    selected = min(order, key=score) if samples else "lower_right"
    selected_metrics = metrics[selected]
    minimum = selected_metrics["minimum_curve_clearance_mm"]
    return {
        "position": selected,
        "method": "final_size_physical_clearance_v1",
        "required_curve_clearance_mm": clearance_mm,
        "edge_padding_mm": edge_padding_mm,
        "minimum_curve_clearance_mm": minimum,
        "clearance_status": (
            "safe"
            if minimum is None or float(minimum) >= clearance_mm
            else "best_available_needs_reserve"
        ),
        "footprint": {key: round(float(value), 6) for key, value in footprint.items()},
        "candidates": metrics,
    }
