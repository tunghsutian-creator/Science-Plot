"""Apply baseline, stacking, and template-specific series transformations."""

from __future__ import annotations

import math
import sys
from dataclasses import replace
from typing import Any

from sciplot_core.studio_render.models import (
    STACKED_TEMPLATE_IDS,
    StudioSeries,
)

from sciplot_core.studio_render.template_resolution import (
    _request_template,
    _finite_values,
    _quantile,
    _robust_peak_height,
    _nice_ceiling,
    _mean,
)

from sciplot_core.studio_render.value_parsing import (
    _optional_float,
)


def _apply_template_series_transforms(
    series: list[StudioSeries],
    *,
    request: dict[str, Any],
    render_options: dict[str, Any],
) -> list[StudioSeries]:
    transformed = series
    baseline_mode = str(render_options.get("baseline") or "none").strip().casefold()
    if baseline_mode != "none":
        transformed = [_baseline_correct_series(item) for item in transformed]
    if _request_template(request) in STACKED_TEMPLATE_IDS:
        transformed = _stack_studio_series(
            transformed,
            render_options=render_options,
            full_peak_envelope=(
                str(request.get("rule_id") or "").strip() == "dsc_curve"
                or render_options.get("stack_peak_envelope") is True
            ),
        )
    return transformed


def _baseline_correct_series(item: StudioSeries) -> StudioSeries:
    x_values = item.x_values
    y_values = item.y_values
    valid_indexes = [
        index
        for index, (x_value, y_value) in enumerate(zip(x_values, y_values, strict=True))
        if math.isfinite(x_value) and math.isfinite(y_value)
    ]
    if len(valid_indexes) < 3:
        return item

    n_edge = max(3, min(len(valid_indexes) // 12, 30))
    start_indexes = valid_indexes[:n_edge]
    end_indexes = valid_indexes[-n_edge:]
    x_start = _mean(x_values[index] for index in start_indexes)
    y_start = _mean(y_values[index] for index in start_indexes)
    x_end = _mean(x_values[index] for index in end_indexes)
    y_end = _mean(y_values[index] for index in end_indexes)
    if math.isclose(x_start, x_end):
        corrected = tuple(
            y_value - y_start if math.isfinite(y_value) else y_value
            for y_value in y_values
        )
    else:
        slope = (y_end - y_start) / (x_end - x_start)
        corrected = tuple(
            y_value - (y_start + slope * (x_value - x_start))
            if math.isfinite(x_value) and math.isfinite(y_value)
            else y_value
            for x_value, y_value in zip(x_values, y_values, strict=True)
        )
    return replace(item, y_values=corrected)


def _stack_studio_series(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
    full_peak_envelope: bool = False,
) -> list[StudioSeries]:
    if len(series) <= 1:
        return series

    if full_peak_envelope:
        prepared_full: list[tuple[StudioSeries, tuple[float, ...], float]] = []
        full_spans: list[float] = []
        for item in series:
            finite = _finite_values(item.y_values)
            data_min = min(finite) if finite else 0.0
            data_max = max(finite) if finite else data_min
            span = max(data_max - data_min, sys.float_info.epsilon)
            shifted = tuple(
                y_value - data_min if math.isfinite(y_value) else y_value
                for y_value in item.y_values
            )
            prepared_full.append((item, shifted, span))
            full_spans.append(span)
        maximum_span = max(full_spans) if full_spans else 1.0
        gap = max(0.22 * maximum_span, sys.float_info.epsilon)
        cursor = 0.08 * maximum_span
        stacked_full: list[StudioSeries] = []
        for item, shifted, span in prepared_full:
            stacked_full.append(
                replace(item, y_values=tuple(value + cursor for value in shifted))
            )
            cursor += span + gap
        return stacked_full

    prepared: list[tuple[StudioSeries, tuple[float, ...], float, float]] = []
    spans: list[float] = []
    peak_heights: list[float] = []
    lower_guards: list[float] = []
    for item in series:
        finite = _finite_values(item.y_values)
        q01 = _quantile(finite, 0.01) if finite else 0.0
        shifted = tuple(
            y_value - q01 if math.isfinite(y_value) else y_value
            for y_value in item.y_values
        )
        shifted_finite = _finite_values(shifted)
        lower_guards.append(max(0.0, -min(shifted_finite)) if shifted_finite else 0.0)
        peak = _robust_peak_height(finite)
        prepared.append((item, shifted, peak, peak))
        spans.append(peak)
        peak_heights.append(peak)

    max_span = max(spans) if spans else 1.0
    max_peak = max(peak_heights) if peak_heights else max_span
    spacing_scale = _optional_float(render_options.get("stack_spacing_scale"))
    if spacing_scale is None:
        peak = max(max_peak, sys.float_info.epsilon)
        series_count = len(series)
        min_gap = 0.25 * peak
        padding = 0.10 * peak
        lower_guard = max(lower_guards) if lower_guards else 0.0
        required_span = (
            series_count * peak
            + (series_count - 1) * min_gap
            + 2.0 * padding
            + lower_guard
        )
        y_span = _nice_ceiling(required_span)
        gap = (y_span - series_count * peak - 2.0 * padding - lower_guard) / max(
            series_count - 1, 1
        )
        step = peak + max(gap, min_gap)
        floor = padding + lower_guard
    else:
        scale = max(spacing_scale, 0.05)
        floor = max(max_span * 0.22, max_peak * 0.16) * scale
        peak_clearance = max(max_span * 0.22 * 0.95, max_peak * 0.24)
        step = max(max_span * 1.22, max_peak + peak_clearance) * scale

    stacked: list[StudioSeries] = []
    for index, (item, shifted, _span, _peak) in enumerate(prepared):
        offset = floor + index * step
        stacked.append(
            replace(item, y_values=tuple(y_value + offset for y_value in shifted))
        )
    return stacked
