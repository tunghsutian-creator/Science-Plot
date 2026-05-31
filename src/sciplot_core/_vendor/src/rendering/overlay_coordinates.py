from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from matplotlib.axes import Axes

from src.rendering.advanced_plot_axes import primary_axis
from src.rendering.axis_breaks import (
    axis_break_panel_axes,
    axis_break_panel_for_value,
    axis_break_panel_range,
    transform_axis_break_interval_segments,
    transform_axis_break_value,
    value_hidden_by_axis_break,
)
from src.rendering.extra_axes import extra_axis_binding_mode
from src.rendering.models import RenderedPlot, RenderOptions


@dataclass(frozen=True)
class AxisInterval:
    axis: Axes
    start: float
    end: float


def pixel_offset_point(
    ax: Axes,
    *,
    x: float,
    y: float,
    dx: float = 0.0,
    dy: float = 0.0,
) -> tuple[float, float]:
    display_x, display_y = ax.transData.transform((x, y))
    mapped_x, mapped_y = ax.transData.inverted().transform((display_x + dx, display_y + dy))
    return float(mapped_x), float(mapped_y)


def panel_contains_value(axis: Axes, *, axis_name: str, value: float) -> bool:
    visible_range = axis_break_panel_range(axis, axis_name=axis_name)
    if visible_range is None:
        return True
    lower, upper = visible_range
    return lower <= value <= upper


def panel_overlap(
    axis: Axes,
    *,
    axis_name: str,
    start: float,
    end: float,
) -> tuple[float, float] | None:
    visible_range = axis_break_panel_range(axis, axis_name=axis_name)
    if visible_range is None:
        return (start, end)
    lower = max(min(start, end), visible_range[0])
    upper = min(max(start, end), visible_range[1])
    if upper <= lower:
        return None
    return lower, upper


def anchor_axis_for_value(
    axes: tuple[Axes, ...],
    *,
    axis_name: str,
    value: float,
) -> Axes | None:
    if not axes:
        return None
    for axis in axes:
        if panel_contains_value(axis, axis_name=axis_name, value=value):
            return axis
    return axes[0]


def anchor_axis_for_band(
    axes: tuple[Axes, ...],
    *,
    axis_name: str,
    start: float,
    end: float,
) -> tuple[Axes | None, tuple[float, float] | None]:
    if not axes:
        return None, None
    best_axis = axes[0]
    best_overlap = panel_overlap(best_axis, axis_name=axis_name, start=start, end=end)
    best_size = -1.0 if best_overlap is None else best_overlap[1] - best_overlap[0]
    for axis in axes[1:]:
        overlap = panel_overlap(axis, axis_name=axis_name, start=start, end=end)
        size = -1.0 if overlap is None else overlap[1] - overlap[0]
        if size > best_size:
            best_axis = axis
            best_overlap = overlap
            best_size = size
    return best_axis, best_overlap


def axis_intervals(
    rendered: RenderedPlot,
    *,
    axis_name: str,
    start: float,
    end: float,
    target_axis: Axes | None = None,
) -> tuple[AxisInterval, ...]:
    primary = primary_axis(rendered)
    if primary is None:
        return ()
    if axis_name == "y" and target_axis is not None and target_axis is not primary:
        return (AxisInterval(axis=target_axis, start=start, end=end),) if end > start else ()
    panel_axes = axis_break_panel_axes(rendered, axis_name=axis_name)
    if len(panel_axes) > 1:
        intervals: list[AxisInterval] = []
        for axis in panel_axes:
            overlap = panel_overlap(axis, axis_name=axis_name, start=start, end=end)
            if overlap is None:
                continue
            intervals.append(AxisInterval(axis=axis, start=overlap[0], end=overlap[1]))
        return tuple(intervals)
    segments = transform_axis_break_interval_segments(primary, axis_name=axis_name, start=start, end=end)
    return tuple(
        AxisInterval(axis=primary, start=segment[0], end=segment[1])
        for segment in segments
        if segment[1] > segment[0]
    )


def mapped_axis_value_anchor(
    rendered: RenderedPlot,
    *,
    axis_name: str,
    value: float,
    target_axis: Axes | None = None,
) -> tuple[Axes, float] | None:
    primary = primary_axis(rendered)
    if primary is None:
        return None
    if axis_name == "y" and target_axis is not None and target_axis is not primary:
        return target_axis, value
    panel_axes = axis_break_panel_axes(rendered, axis_name=axis_name)
    if len(panel_axes) > 1:
        panel_axis = axis_break_panel_for_value(rendered, axis_name=axis_name, value=value)
        if panel_axis is None:
            return None
        return panel_axis, value
    if value_hidden_by_axis_break(primary, axis_name=axis_name, value=value):
        return None
    mapped = transform_axis_break_value(primary, axis_name=axis_name, value=value)
    if mapped is None:
        return None
    return primary, float(mapped)


def secondary_y_conversion_scale(options: RenderOptions) -> float | None:
    payload = options.extra_y_axis
    if not isinstance(payload, Mapping) or not bool(payload.get("enabled", False)):
        return None
    if extra_axis_binding_mode(payload) != "conversion":
        return None
    data_value = float(payload.get("data_value", 1.0))
    display_value = float(payload.get("display_value", 1.0))
    if data_value <= 0.0 or display_value <= 0.0:
        return None
    return display_value / data_value


__all__ = [
    "AxisInterval",
    "anchor_axis_for_band",
    "anchor_axis_for_value",
    "axis_intervals",
    "mapped_axis_value_anchor",
    "panel_contains_value",
    "panel_overlap",
    "pixel_offset_point",
    "secondary_y_conversion_scale",
]
