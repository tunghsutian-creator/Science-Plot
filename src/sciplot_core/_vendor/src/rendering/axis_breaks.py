from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, TypedDict, cast

import numpy as np
from matplotlib.axes import Axes
from matplotlib.collections import PathCollection
from matplotlib.ticker import FixedFormatter, FixedLocator, NullLocator

from src import plot_style
from src.rendering.advanced_plot_axes import mark_primary_axis, primary_axis
from src.rendering.models import QAReport, RenderedPlot, RenderOptions

_X_BREAK_ATTR = "_sciplot_x_axis_break_spec"
_Y_BREAK_ATTR = "_sciplot_y_axis_break_spec"
_X_PANEL_AXES_ATTR = "_sciplot_x_axis_break_panel_axes"
_Y_PANEL_AXES_ATTR = "_sciplot_y_axis_break_panel_axes"
_X_PANEL_RANGE_ATTR = "_sciplot_x_axis_break_panel_range"
_Y_PANEL_RANGE_ATTR = "_sciplot_y_axis_break_panel_range"
_BREAK_GAP_FRACTION = 0.055
_BREAK_PANEL_GAP_FRACTION = 0.045
_VALID_BREAK_DISPLAY_MODES = frozenset({"compress", "split"})


class AxisBreakPayloadDict(TypedDict):
    id: str
    enabled: bool
    start: float
    end: float
    display_mode: str


@dataclass(frozen=True)
class AxisBreakOptions:
    id: str
    enabled: bool = True
    start: float = 0.0
    end: float = 1.0
    display_mode: str = "compress"


@dataclass(frozen=True)
class AxisBreakSpan:
    start: float
    end: float
    display_start: float
    display_end: float


@dataclass(frozen=True)
class AxisBreakSpec:
    axis_name: str
    original_min: float
    original_max: float
    transformed_min: float
    transformed_max: float
    spans: tuple[AxisBreakSpan, ...]

    @property
    def gap_centers(self) -> tuple[float, ...]:
        return tuple((span.display_start + span.display_end) / 2.0 for span in self.spans)


def _append_autofixes(report: QAReport | None, *, autofix_ids: tuple[str, ...]) -> QAReport | None:
    if report is None:
        return None
    applied = tuple(report.autofixes_applied)
    merged = applied + tuple(item for item in autofix_ids if item not in applied)
    return replace(report, autofixes_applied=merged)


def _iter_break_maps(value: object, *, axis_name: str) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, bytearray, Mapping)):
        raise ValueError(f"`{axis_name}_axis_breaks` must be a list of mappings.")
    items: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"`{axis_name}_axis_breaks` items must be mappings.")
        items.append(item)
    return tuple(items)


def _string(value: object, *, field_name: str, default: str) -> str:
    cleaned = str(value if value is not None else default).strip() or default
    if not cleaned:
        raise ValueError(f"`{field_name}` must not be blank.")
    return cleaned


def _finite_float(value: object, *, field_name: str, default: float) -> float:
    if value is None:
        numeric = default
    elif isinstance(value, int | float | str):
        numeric = float(cast(Any, value))
    else:
        raise ValueError(f"`{field_name}` must be numeric.")
    if not math.isfinite(numeric):
        raise ValueError(f"`{field_name}` must be a finite number.")
    return numeric


def _display_mode(value: object, *, field_name: str) -> str:
    mode = _string(value, field_name=field_name, default="compress").lower()
    if mode not in _VALID_BREAK_DISPLAY_MODES:
        raise ValueError(
            f"`{field_name}` must be one of {', '.join(sorted(_VALID_BREAK_DISPLAY_MODES))}."
        )
    return mode


def normalize_axis_breaks_payload(
    value: object,
    *,
    axis_name: str,
) -> tuple[AxisBreakPayloadDict, ...] | None:
    items = _iter_break_maps(value, axis_name=axis_name)
    if not items:
        return None

    normalized: list[AxisBreakPayloadDict] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        break_id = _string(
            item.get("id"),
            field_name=f"{axis_name}_axis_breaks[{index}].id",
            default=f"{axis_name}-axis-break-{index + 1}",
        )
        if break_id in seen_ids:
            raise ValueError(f"`{axis_name}_axis_breaks` ids must be unique.")
        seen_ids.add(break_id)
        start = _finite_float(
            item.get("start"),
            field_name=f"{axis_name}_axis_breaks[{index}].start",
            default=0.0,
        )
        end = _finite_float(
            item.get("end"),
            field_name=f"{axis_name}_axis_breaks[{index}].end",
            default=1.0,
        )
        if end < start:
            start, end = end, start
        normalized.append(
            {
                "id": break_id,
                "enabled": bool(item.get("enabled", True)),
                "start": start,
                "end": end,
                "display_mode": _display_mode(
                    item.get("display_mode"),
                    field_name=f"{axis_name}_axis_breaks[{index}].display_mode",
                ),
            }
        )
    return tuple(normalized)


def axis_breaks_from_payload(value: object, *, axis_name: str) -> tuple[AxisBreakOptions, ...]:
    payload = normalize_axis_breaks_payload(value, axis_name=axis_name)
    if payload is None:
        return ()
    return tuple(
        AxisBreakOptions(
            id=item["id"],
            enabled=item["enabled"],
            start=item["start"],
            end=item["end"],
            display_mode=item["display_mode"],
        )
        for item in payload
    )


def has_axis_breaks(options: RenderOptions) -> bool:
    return bool(options.x_axis_breaks or options.y_axis_breaks)


def _spec_attr_name(axis_name: str) -> str:
    return _X_BREAK_ATTR if axis_name == "x" else _Y_BREAK_ATTR


def axis_break_spec(ax: Axes, *, axis_name: str) -> AxisBreakSpec | None:
    return cast(AxisBreakSpec | None, getattr(ax, _spec_attr_name(axis_name), None))


def _set_axis_break_spec(ax: Axes, *, axis_name: str, spec: AxisBreakSpec | None) -> None:
    setattr(ax, _spec_attr_name(axis_name), spec)


def _panel_axes_attr_name(axis_name: str) -> str:
    return _X_PANEL_AXES_ATTR if axis_name == "x" else _Y_PANEL_AXES_ATTR


def _panel_range_attr_name(axis_name: str) -> str:
    return _X_PANEL_RANGE_ATTR if axis_name == "x" else _Y_PANEL_RANGE_ATTR


def _set_panel_axes(rendered: RenderedPlot, *, axis_name: str, axes: tuple[Axes, ...] | None) -> None:
    setattr(rendered.figure, _panel_axes_attr_name(axis_name), axes)


def _set_panel_range(ax: Axes, *, axis_name: str, visible_range: tuple[float, float] | None) -> None:
    setattr(ax, _panel_range_attr_name(axis_name), visible_range)


def axis_break_panel_axes(rendered: RenderedPlot, *, axis_name: str) -> tuple[Axes, ...]:
    axes = getattr(rendered.figure, _panel_axes_attr_name(axis_name), None)
    if isinstance(axes, tuple) and axes:
        return tuple(axis for axis in axes if isinstance(axis, Axes))
    primary = primary_axis(rendered)
    return (primary,) if primary is not None else ()


def axis_break_panel_range(ax: Axes, *, axis_name: str) -> tuple[float, float] | None:
    value = getattr(ax, _panel_range_attr_name(axis_name), None)
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(item, int | float) for item in value)
    ):
        start, end = value
        return float(start), float(end)
    return None


def _merged_visible_breaks(
    breaks: tuple[AxisBreakOptions, ...],
    *,
    lower: float,
    upper: float,
) -> tuple[tuple[float, float], ...]:
    visible_min = min(lower, upper)
    visible_max = max(lower, upper)
    merged: list[tuple[float, float]] = []
    for axis_break in sorted((item for item in breaks if item.enabled), key=lambda item: item.start):
        start = max(visible_min, axis_break.start)
        end = min(visible_max, axis_break.end)
        if not end > start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return tuple(merged)


def _visible_segments(
    merged_breaks: tuple[tuple[float, float], ...],
    *,
    lower: float,
    upper: float,
) -> tuple[tuple[float, float], ...]:
    visible_min = min(lower, upper)
    visible_max = max(lower, upper)
    segments: list[tuple[float, float]] = []
    cursor = visible_min
    for start, end in merged_breaks:
        if cursor < start:
            segments.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < visible_max:
        segments.append((cursor, visible_max))
    return tuple(segment for segment in segments if segment[1] > segment[0])


def _axis_break_display_mode(breaks: tuple[AxisBreakOptions, ...]) -> str:
    modes = {item.display_mode for item in breaks if item.enabled}
    if not modes:
        modes = {item.display_mode for item in breaks}
    return next(iter(modes), "compress")


def _build_axis_break_spec(
    breaks: tuple[AxisBreakOptions, ...],
    *,
    axis_name: str,
    lower: float,
    upper: float,
) -> AxisBreakSpec | None:
    merged = _merged_visible_breaks(breaks, lower=lower, upper=upper)
    if not merged:
        return None
    visible_min = min(lower, upper)
    visible_max = max(lower, upper)
    visible_range = visible_max - visible_min
    if visible_range <= 0.0:
        return None
    gap_width = max(visible_range * _BREAK_GAP_FRACTION, visible_range * 0.015)
    spans: list[AxisBreakSpan] = []
    cumulative_shift = 0.0
    for start, end in merged:
        display_start = start - cumulative_shift
        compressed = max(end - start - gap_width, 0.0)
        cumulative_shift += compressed
        spans.append(
            AxisBreakSpan(
                start=start,
                end=end,
                display_start=display_start,
                display_end=display_start + gap_width,
            )
        )
    return AxisBreakSpec(
        axis_name=axis_name,
        original_min=visible_min,
        original_max=visible_max,
        transformed_min=visible_min,
        transformed_max=visible_max - cumulative_shift,
        spans=tuple(spans),
    )


def value_hidden_by_axis_break(
    ax: Axes,
    *,
    axis_name: str,
    value: float,
) -> bool:
    spec = axis_break_spec(ax, axis_name=axis_name)
    if spec is None:
        return False
    return any(span.start < value < span.end for span in spec.spans)


def transform_axis_break_value(
    ax: Axes,
    *,
    axis_name: str,
    value: float,
) -> float | None:
    spec = axis_break_spec(ax, axis_name=axis_name)
    if spec is None:
        return value
    if value_hidden_by_axis_break(ax, axis_name=axis_name, value=value):
        return None
    shifted = value
    for span in spec.spans:
        if value >= span.end:
            shifted -= (span.end - span.start) - (span.display_end - span.display_start)
    return shifted


def transform_axis_break_interval_segments(
    ax: Axes,
    *,
    axis_name: str,
    start: float,
    end: float,
) -> tuple[tuple[float, float], ...]:
    spec = axis_break_spec(ax, axis_name=axis_name)
    lower = min(start, end)
    upper = max(start, end)
    if spec is None:
        return ((lower, upper),)
    segments: list[tuple[float, float]] = []
    cursor = lower
    for span in spec.spans:
        if span.end <= cursor:
            continue
        if span.start >= upper:
            break
        if cursor < span.start:
            mapped_start = transform_axis_break_value(ax, axis_name=axis_name, value=cursor)
            mapped_end = transform_axis_break_value(ax, axis_name=axis_name, value=min(span.start, upper))
            if mapped_start is not None and mapped_end is not None and mapped_end >= mapped_start:
                segments.append((mapped_start, mapped_end))
        cursor = max(cursor, span.end)
    if cursor < upper:
        mapped_start = transform_axis_break_value(ax, axis_name=axis_name, value=cursor)
        mapped_end = transform_axis_break_value(ax, axis_name=axis_name, value=upper)
        if mapped_start is not None and mapped_end is not None and mapped_end >= mapped_start:
            segments.append((mapped_start, mapped_end))
    return tuple(segments)


def axis_break_panel_for_value(
    rendered: RenderedPlot,
    *,
    axis_name: str,
    value: float,
) -> Axes | None:
    panel_axes = axis_break_panel_axes(rendered, axis_name=axis_name)
    if len(panel_axes) <= 1:
        return panel_axes[0] if panel_axes else None
    for axis in panel_axes:
        visible_range = axis_break_panel_range(axis, axis_name=axis_name)
        if visible_range is None:
            continue
        lower, upper = visible_range
        if lower <= value <= upper:
            return axis
    return None


def _interval_crosses_break(value_a: float, value_b: float, spec: AxisBreakSpec | None) -> bool:
    if spec is None:
        return False
    lower = min(value_a, value_b)
    upper = max(value_a, value_b)
    return any(lower < span.end and upper > span.start for span in spec.spans)


def _transform_line_artist(line, *, x_spec: AxisBreakSpec | None, y_spec: AxisBreakSpec | None) -> None:
    x_values = np.asarray(line.get_xdata(orig=False), dtype=float)
    y_values = np.asarray(line.get_ydata(orig=False), dtype=float)
    if x_values.size == 0 or y_values.size == 0:
        return

    transformed_x: list[float] = []
    transformed_y: list[float] = []
    previous_visible = False
    previous_x = math.nan
    previous_y = math.nan

    for x_value, y_value in zip(x_values, y_values, strict=False):
        finite = math.isfinite(x_value) and math.isfinite(y_value)
        visible = (
            finite
            and not (x_spec is not None and value_hidden_by_axis_break(line.axes, axis_name="x", value=float(x_value)))
            and not (y_spec is not None and value_hidden_by_axis_break(line.axes, axis_name="y", value=float(y_value)))
        )
        if not visible:
            transformed_x.append(math.nan)
            transformed_y.append(math.nan)
            previous_visible = False
            previous_x = x_value
            previous_y = y_value
            continue

        crosses_break = (
            previous_visible
            and (
                _interval_crosses_break(previous_x, x_value, x_spec)
                or _interval_crosses_break(previous_y, y_value, y_spec)
            )
        )
        if crosses_break:
            transformed_x.append(math.nan)
            transformed_y.append(math.nan)

        mapped_x = (
            transform_axis_break_value(line.axes, axis_name="x", value=float(x_value))
            if x_spec is not None
            else float(x_value)
        )
        mapped_y = (
            transform_axis_break_value(line.axes, axis_name="y", value=float(y_value))
            if y_spec is not None
            else float(y_value)
        )
        transformed_x.append(float(mapped_x if mapped_x is not None else math.nan))
        transformed_y.append(float(mapped_y if mapped_y is not None else math.nan))
        previous_visible = True
        previous_x = x_value
        previous_y = y_value

    line.set_xdata(np.asarray(transformed_x, dtype=float))
    line.set_ydata(np.asarray(transformed_y, dtype=float))


def _transform_scatter_collection(
    collection: PathCollection,
    *,
    x_spec: AxisBreakSpec | None,
    y_spec: AxisBreakSpec | None,
) -> None:
    axes = collection.axes
    if not isinstance(axes, Axes):
        return
    offsets = np.asarray(collection.get_offsets(), dtype=float)
    if offsets.size == 0:
        return
    visible_mask = np.isfinite(offsets[:, 0]) & np.isfinite(offsets[:, 1])
    if x_spec is not None:
        visible_mask &= np.array(
            [
                not value_hidden_by_axis_break(axes, axis_name="x", value=float(value))
                for value in offsets[:, 0]
            ],
            dtype=bool,
        )
    if y_spec is not None:
        visible_mask &= np.array(
            [
                not value_hidden_by_axis_break(axes, axis_name="y", value=float(value))
                for value in offsets[:, 1]
            ],
            dtype=bool,
        )
    filtered = offsets[visible_mask]
    if filtered.size == 0:
        collection.set_offsets(np.empty((0, 2), dtype=float))
        return
    if x_spec is not None:
        filtered[:, 0] = [
            cast(float, transform_axis_break_value(axes, axis_name="x", value=float(value)))
            for value in filtered[:, 0]
        ]
    if y_spec is not None:
        filtered[:, 1] = [
            cast(float, transform_axis_break_value(axes, axis_name="y", value=float(value)))
            for value in filtered[:, 1]
        ]
    collection.set_offsets(filtered)


def _transform_data_texts(ax: Axes, *, x_spec: AxisBreakSpec | None, y_spec: AxisBreakSpec | None) -> None:
    for text in ax.texts:
        if text.get_transform() != ax.transData:
            continue
        x_value, y_value = text.get_position()
        if (
            (x_spec is not None and value_hidden_by_axis_break(ax, axis_name="x", value=float(x_value)))
            or (y_spec is not None and value_hidden_by_axis_break(ax, axis_name="y", value=float(y_value)))
        ):
            text.set_visible(False)
            continue
        mapped_x = (
            transform_axis_break_value(ax, axis_name="x", value=float(x_value))
            if x_spec is not None
            else float(x_value)
        )
        mapped_y = (
            transform_axis_break_value(ax, axis_name="y", value=float(y_value))
            if y_spec is not None
            else float(y_value)
        )
        if mapped_x is None or mapped_y is None:
            text.set_visible(False)
            continue
        text.set_position((mapped_x, mapped_y))


def _format_tick_label(axis, value: float) -> str:
    formatter = axis.get_major_formatter()
    for method_name in ("format_data_short", "format_data"):
        method = getattr(formatter, method_name, None)
        if callable(method):
            try:
                label = str(method(value))
            except Exception:
                continue
            if label:
                return label
    try:
        label = str(formatter(value, 0))
        if label:
            return label
    except Exception:
        pass
    return f"{value:g}"


def _apply_axis_ticks(ax: Axes, *, axis_name: str, spec: AxisBreakSpec | None) -> None:
    if spec is None:
        return
    axis = ax.xaxis if axis_name == "x" else ax.yaxis
    original_ticks = list(axis.get_ticklocs())
    candidates = {float(spec.original_min), float(spec.original_max)}
    candidates.update(original_ticks)
    for span in spec.spans:
        candidates.add(float(span.start))
        candidates.add(float(span.end))
    visible_ticks = [
        tick
        for tick in sorted(candidates)
        if spec.original_min <= tick <= spec.original_max
        and not value_hidden_by_axis_break(ax, axis_name=axis_name, value=tick)
    ]
    transformed_ticks = [
        cast(float, transform_axis_break_value(ax, axis_name=axis_name, value=tick))
        for tick in visible_ticks
    ]
    axis.set_major_locator(FixedLocator(transformed_ticks))
    axis.set_major_formatter(FixedFormatter([_format_tick_label(axis, tick) for tick in visible_ticks]))
    axis.set_minor_locator(NullLocator())


def _axis_fraction(ax: Axes, *, axis_name: str, value: float) -> float:
    lower, upper = ax.get_xlim() if axis_name == "x" else ax.get_ylim()
    span = upper - lower
    if math.isclose(span, 0.0):
        return 0.5
    return (value - lower) / span


def _draw_break_markers(ax: Axes, *, x_spec: AxisBreakSpec | None, y_spec: AxisBreakSpec | None) -> None:
    stroke = plot_style.current_stroke()
    color = ax.spines["bottom" if "bottom" in ax.spines else next(iter(ax.spines))].get_edgecolor()
    line_width = max(0.8, stroke.line_width_pt * 0.9)
    slash_dx = 0.010
    slash_dy = 0.018
    slash_offset = 0.006
    if x_spec is not None:
        for center in x_spec.gap_centers:
            x_center = _axis_fraction(ax, axis_name="x", value=center)
            for offset in (-slash_offset, slash_offset):
                ax.plot(
                    [x_center + offset - slash_dx, x_center + offset + slash_dx],
                    [-slash_dy, slash_dy],
                    transform=ax.transAxes,
                    color=color,
                    linewidth=line_width,
                    clip_on=False,
                    zorder=5.0,
                )
                ax.plot(
                    [x_center + offset - slash_dx, x_center + offset + slash_dx],
                    [1.0 - slash_dy, 1.0 + slash_dy],
                    transform=ax.transAxes,
                    color=color,
                    linewidth=line_width,
                    clip_on=False,
                    zorder=5.0,
                )
    if y_spec is not None:
        for center in y_spec.gap_centers:
            y_center = _axis_fraction(ax, axis_name="y", value=center)
            for offset in (-slash_offset, slash_offset):
                ax.plot(
                    [-slash_dy, slash_dy],
                    [y_center + offset - slash_dx, y_center + offset + slash_dx],
                    transform=ax.transAxes,
                    color=color,
                    linewidth=line_width,
                    clip_on=False,
                    zorder=5.0,
                )
                ax.plot(
                    [1.0 - slash_dy, 1.0 + slash_dy],
                    [y_center + offset - slash_dx, y_center + offset + slash_dx],
                    transform=ax.transAxes,
                    color=color,
                    linewidth=line_width,
                    clip_on=False,
                    zorder=5.0,
                )


def _ordered_split_segments(
    ax: Axes,
    *,
    axis_name: str,
    segments: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    if axis_name == "x":
        return tuple(reversed(segments)) if ax.xaxis_inverted() else segments
    return segments if ax.yaxis_inverted() else tuple(reversed(segments))


def _split_panel_rects(
    ax: Axes,
    *,
    axis_name: str,
    panel_count: int,
    weights: tuple[float, ...],
) -> tuple[tuple[float, float, float, float], ...]:
    bbox = ax.get_position()
    gap_count = max(panel_count - 1, 0)
    if axis_name == "x":
        gap_size = bbox.width * _BREAK_PANEL_GAP_FRACTION
        usable = max(bbox.width - gap_size * gap_count, bbox.width * 0.4)
        cursor = bbox.x0
        rects: list[tuple[float, float, float, float]] = []
        for weight in weights:
            width = usable * weight
            rects.append((cursor, bbox.y0, width, bbox.height))
            cursor += width + gap_size
        return tuple(rects)

    gap_size = bbox.height * _BREAK_PANEL_GAP_FRACTION
    usable = max(bbox.height - gap_size * gap_count, bbox.height * 0.4)
    cursor = bbox.y1
    rects = []
    for weight in weights:
        height = usable * weight
        rects.append((bbox.x0, cursor - height, bbox.width, height))
        cursor -= height + gap_size
    return tuple(rects)


def _clone_line_to_axis(line, *, axis: Axes) -> None:
    axis.plot(
        line.get_xdata(orig=False),
        line.get_ydata(orig=False),
        label=line.get_label(),
        color=line.get_color(),
        linewidth=line.get_linewidth(),
        linestyle=line.get_linestyle(),
        alpha=line.get_alpha(),
        drawstyle=line.get_drawstyle(),
        marker=line.get_marker(),
        markersize=line.get_markersize(),
        markerfacecolor=line.get_markerfacecolor(),
        markeredgecolor=line.get_markeredgecolor(),
        markeredgewidth=line.get_markeredgewidth(),
        markevery=line.get_markevery(),
        zorder=line.get_zorder(),
    )


def _clone_scatter_to_axis(collection: PathCollection, *, axis: Axes) -> None:
    offsets = np.asarray(collection.get_offsets(), dtype=float)
    if offsets.size == 0:
        return
    paths = collection.get_paths()
    collection_any = cast(Any, collection)
    axis.scatter(
        offsets[:, 0],
        offsets[:, 1],
        label=collection.get_label(),
        s=collection.get_sizes(),
        marker=paths[0] if paths else "o",
        facecolors=collection_any.get_facecolors(),
        edgecolors=collection_any.get_edgecolors(),
        linewidths=collection_any.get_linewidths(),
        alpha=collection.get_alpha(),
        zorder=collection.get_zorder(),
    )


def _text_bbox_kwargs(text) -> dict[str, object] | None:
    bbox_patch = text.get_bbox_patch()
    if bbox_patch is None:
        return None
    return {
        "facecolor": bbox_patch.get_facecolor(),
        "alpha": bbox_patch.get_alpha(),
        "linewidth": bbox_patch.get_linewidth(),
        "boxstyle": bbox_patch.get_boxstyle(),
    }


def _clone_text_to_axis(text, *, source_axis: Axes, axis: Axes, anchor: bool) -> None:
    kwargs = {
        "ha": text.get_ha(),
        "va": text.get_va(),
        "fontsize": text.get_fontsize(),
        "color": text.get_color(),
        "alpha": text.get_alpha(),
        "rotation": text.get_rotation(),
        "clip_on": text.get_clip_on(),
        "bbox": _text_bbox_kwargs(text),
        "zorder": text.get_zorder(),
    }
    if text.get_transform() == source_axis.transData:
        x_value, y_value = text.get_position()
        data_kwargs = dict(kwargs)
        data_kwargs["clip_on"] = True
        axis.text(
            x_value,
            y_value,
            text.get_text(),
            transform=axis.transData,
            **data_kwargs,
        )
        return
    if text.get_transform() == source_axis.transAxes and anchor:
        x_value, y_value = text.get_position()
        axis.text(
            x_value,
            y_value,
            text.get_text(),
            transform=axis.transAxes,
            **kwargs,
        )


def _rebuild_split_legend(source_axis: Axes, *, anchor_axis: Axes) -> None:
    legend = source_axis.get_legend()
    if legend is None:
        return
    handles, labels = anchor_axis.get_legend_handles_labels()
    filtered = [
        (handle, label)
        for handle, label in zip(handles, labels, strict=False)
        if label and label != "_nolegend_"
    ]
    if not filtered:
        return
    anchor_axis.legend(
        [item[0] for item in filtered],
        [item[1] for item in filtered],
        loc=getattr(legend, "_loc", "upper right"),
    )


def _draw_split_break_markers(panel_axes: tuple[Axes, ...], *, axis_name: str) -> None:
    if len(panel_axes) <= 1:
        return
    stroke = plot_style.current_stroke()
    line_width = max(0.8, stroke.line_width_pt * 0.9)
    spine_name = "bottom" if "bottom" in panel_axes[0].spines else next(iter(panel_axes[0].spines))
    color = panel_axes[0].spines[spine_name].get_edgecolor()
    slash_dx = 0.010
    slash_dy = 0.018
    for left_axis, right_axis in zip(panel_axes, panel_axes[1:], strict=False):
        if axis_name == "x":
            for axis, x_center in ((left_axis, 1.0), (right_axis, 0.0)):
                axis.plot(
                    [x_center - slash_dx, x_center + slash_dx],
                    [-slash_dy, slash_dy],
                    transform=axis.transAxes,
                    color=color,
                    linewidth=line_width,
                    clip_on=False,
                    zorder=5.0,
                )
                axis.plot(
                    [x_center - slash_dx, x_center + slash_dx],
                    [1.0 - slash_dy, 1.0 + slash_dy],
                    transform=axis.transAxes,
                    color=color,
                    linewidth=line_width,
                    clip_on=False,
                    zorder=5.0,
                )
            continue

        for axis, y_center in ((left_axis, 0.0), (right_axis, 1.0)):
            axis.plot(
                [-slash_dy, slash_dy],
                [y_center - slash_dx, y_center + slash_dx],
                transform=axis.transAxes,
                color=color,
                linewidth=line_width,
                clip_on=False,
                zorder=5.0,
            )
            axis.plot(
                [1.0 - slash_dy, 1.0 + slash_dy],
                [y_center - slash_dx, y_center + slash_dx],
                transform=axis.transAxes,
                color=color,
                linewidth=line_width,
                clip_on=False,
                zorder=5.0,
            )


def _apply_split_axis_breaks(
    rendered: RenderedPlot,
    *,
    axis_name: str,
    segments: tuple[tuple[float, float], ...],
) -> RenderedPlot:
    source_axis = primary_axis(rendered)
    if source_axis is None or len(segments) <= 1:
        return rendered

    ordered_segments = _ordered_split_segments(source_axis, axis_name=axis_name, segments=segments)
    lengths = tuple(max(end - start, 1e-9) for start, end in ordered_segments)
    total_length = sum(lengths)
    weights = tuple(length / total_length for length in lengths)
    panel_axes: list[Axes] = []
    rects = _split_panel_rects(source_axis, axis_name=axis_name, panel_count=len(ordered_segments), weights=weights)
    original_xlim = source_axis.get_xlim()
    original_ylim = source_axis.get_ylim()

    for index, ((start, end), rect) in enumerate(zip(ordered_segments, rects, strict=True)):
        panel_axis = rendered.figure.add_axes(rect)
        panel_axis.set_facecolor(source_axis.get_facecolor())
        panel_axis.set_xscale(source_axis.get_xscale())
        panel_axis.set_yscale(source_axis.get_yscale())
        if axis_name == "x":
            panel_axis.set_xlim(end, start) if source_axis.xaxis_inverted() else panel_axis.set_xlim(start, end)
            panel_axis.set_ylim(*original_ylim)
            if source_axis.yaxis_inverted():
                panel_axis.invert_yaxis()
        else:
            panel_axis.set_xlim(*original_xlim)
            panel_axis.set_ylim(end, start) if source_axis.yaxis_inverted() else panel_axis.set_ylim(start, end)
            if source_axis.xaxis_inverted():
                panel_axis.invert_xaxis()

        for line in list(source_axis.lines):
            _clone_line_to_axis(line, axis=panel_axis)
        for collection in list(source_axis.collections):
            if isinstance(collection, PathCollection):
                _clone_scatter_to_axis(collection, axis=panel_axis)
        for text in list(source_axis.texts):
            _clone_text_to_axis(text, source_axis=source_axis, axis=panel_axis, anchor=index == 0)

        if axis_name == "x":
            panel_axis.set_ylabel("")
            panel_axis.tick_params(labelleft=index == 0, left=index == 0)
            panel_axis.spines["left"].set_visible(index == 0)
            panel_axis.spines["right"].set_visible(False)
        else:
            panel_axis.set_xlabel("")
            panel_axis.tick_params(
                labelbottom=index == len(ordered_segments) - 1,
                bottom=index == len(ordered_segments) - 1,
            )
            panel_axis.spines["bottom"].set_visible(index == len(ordered_segments) - 1)
            panel_axis.spines["top"].set_visible(False)

        _set_panel_range(panel_axis, axis_name=axis_name, visible_range=(start, end))
        panel_axes.append(panel_axis)

    if axis_name == "x":
        rendered.figure.supxlabel(source_axis.get_xlabel())
        rendered.figure.supylabel(source_axis.get_ylabel())
    else:
        rendered.figure.supxlabel(source_axis.get_xlabel())
        rendered.figure.supylabel(source_axis.get_ylabel())

    if panel_axes:
        mark_primary_axis(panel_axes[0])
        panel_axes[0].set_title(source_axis.get_title())
        _rebuild_split_legend(source_axis, anchor_axis=panel_axes[0])
        _set_panel_axes(rendered, axis_name=axis_name, axes=tuple(panel_axes))
        _draw_split_break_markers(tuple(panel_axes), axis_name=axis_name)

    source_axis.remove()
    return replace(
        rendered,
        qa_report=_append_autofixes(
            rendered.qa_report,
            autofix_ids=("axis_break_overlay", "axis_break_split_layout"),
        ),
    )


def apply_axis_breaks(rendered: RenderedPlot, *, options: RenderOptions) -> RenderedPlot:
    primary = primary_axis(rendered)
    if primary is None:
        return rendered

    x_breaks = axis_breaks_from_payload(options.x_axis_breaks, axis_name="x")
    y_breaks = axis_breaks_from_payload(options.y_axis_breaks, axis_name="y")
    _set_panel_axes(rendered, axis_name="x", axes=None)
    _set_panel_axes(rendered, axis_name="y", axes=None)
    x_spec = _build_axis_break_spec(x_breaks, axis_name="x", lower=primary.get_xlim()[0], upper=primary.get_xlim()[1])
    y_spec = _build_axis_break_spec(y_breaks, axis_name="y", lower=primary.get_ylim()[0], upper=primary.get_ylim()[1])
    x_mode = _axis_break_display_mode(x_breaks)
    y_mode = _axis_break_display_mode(y_breaks)
    if x_spec is None and y_spec is None:
        return rendered
    if x_spec is not None and x_mode == "split":
        split_segments = _visible_segments(
            _merged_visible_breaks(x_breaks, lower=primary.get_xlim()[0], upper=primary.get_xlim()[1]),
            lower=primary.get_xlim()[0],
            upper=primary.get_xlim()[1],
        )
        return _apply_split_axis_breaks(rendered, axis_name="x", segments=split_segments)
    if y_spec is not None and y_mode == "split":
        split_segments = _visible_segments(
            _merged_visible_breaks(y_breaks, lower=primary.get_ylim()[0], upper=primary.get_ylim()[1]),
            lower=primary.get_ylim()[0],
            upper=primary.get_ylim()[1],
        )
        return _apply_split_axis_breaks(rendered, axis_name="y", segments=split_segments)

    _set_axis_break_spec(primary, axis_name="x", spec=x_spec)
    _set_axis_break_spec(primary, axis_name="y", spec=y_spec)

    for line in list(primary.lines):
        _transform_line_artist(line, x_spec=x_spec, y_spec=y_spec)
    for collection in list(primary.collections):
        if isinstance(collection, PathCollection):
            _transform_scatter_collection(collection, x_spec=x_spec, y_spec=y_spec)
    _transform_data_texts(primary, x_spec=x_spec, y_spec=y_spec)

    if x_spec is not None:
        if primary.xaxis_inverted():
            primary.set_xlim(x_spec.transformed_max, x_spec.transformed_min)
        else:
            primary.set_xlim(x_spec.transformed_min, x_spec.transformed_max)
        _apply_axis_ticks(primary, axis_name="x", spec=x_spec)
    if y_spec is not None:
        if primary.yaxis_inverted():
            primary.set_ylim(y_spec.transformed_max, y_spec.transformed_min)
        else:
            primary.set_ylim(y_spec.transformed_min, y_spec.transformed_max)
        _apply_axis_ticks(primary, axis_name="y", spec=y_spec)

    _draw_break_markers(primary, x_spec=x_spec, y_spec=y_spec)
    return replace(
        rendered,
        qa_report=_append_autofixes(rendered.qa_report, autofix_ids=("axis_break_overlay",)),
    )


__all__ = [
    "AxisBreakOptions",
    "AxisBreakPayloadDict",
    "apply_axis_breaks",
    "axis_break_panel_axes",
    "axis_break_panel_for_value",
    "axis_break_panel_range",
    "axis_break_spec",
    "axis_breaks_from_payload",
    "has_axis_breaks",
    "normalize_axis_breaks_payload",
    "transform_axis_break_interval_segments",
    "transform_axis_break_value",
    "value_hidden_by_axis_break",
]
