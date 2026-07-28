"""Detect torque processing events and apply explicit curve selections."""

from __future__ import annotations

from typing import Any
import pandas as pd
from sciplot_core.foundation.json_values import json_safe as _json_safe
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
)
from sciplot_core.source_tables import (
    normalize_unit,
)
from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)


def _normalize_torque_unit(unit: str) -> str:
    cleaned = _clean_text(unit).strip("[]()")
    if cleaned in {"Nm", "N m", "N.m", "N·m"}:
        return "N·m"
    return normalize_unit(cleaned)


def _smooth_torque(values: list[float]) -> list[float]:
    if len(values) < 5:
        return values
    window = max(3, min(21, len(values) // 80))
    if window % 2 == 0:
        window += 1
    return list(pd.Series(values).rolling(window, center=True, min_periods=1).median())


def _contiguous_true_runs(flags: list[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def _median_positive_step(values: list[float]) -> float:
    diffs = [
        abs(stop - start)
        for start, stop in zip(values, values[1:], strict=False)
        if abs(stop - start) > 0
    ]
    if not diffs:
        return 1.0
    return float(pd.Series(diffs).median())


def _auto_torque_event_selection(series: CurveSeriesPayload) -> dict[str, Any]:
    points = list(series.points)
    if len(points) < 3:
        raise ValueError(
            f"Torque series `{series.sample}` needs at least three numeric points."
        )
    x_values = [x_value for x_value, _y_value in points]
    y_values = [y_value for _x_value, y_value in points]
    smooth = _smooth_torque(y_values)
    y_frame = pd.Series(y_values)
    low_level = float(y_frame.quantile(0.05))
    work_level = float(y_frame[y_frame > y_frame.quantile(0.25)].median())
    if pd.isna(work_level):
        work_level = float(y_frame.median())
    low_threshold = min(
        max(low_level + 0.5, min(1.5, work_level * 0.45)), work_level * 0.75
    )
    high_threshold = work_level + max(5.0, (max(y_values) - work_level) * 0.35)
    pre_drop_threshold = low_threshold + max(0.75, (work_level - low_threshold) * 0.25)

    high_flags = [value >= high_threshold for value in y_values]
    raw_low_runs = _contiguous_true_runs([value <= low_threshold for value in y_values])
    low_runs = _contiguous_true_runs([value <= low_threshold for value in smooth])
    discharge_run: tuple[int, int] | None = None
    selected_peak_runs: list[tuple[int, int]] = []
    time_step = _median_positive_step(x_values)
    minimum_mixing_span_s = max(120.0, time_step * 30.0)
    for start, stop in reversed(low_runs):
        if stop - start + 1 < 3:
            continue
        if not any(high_flags[:start]):
            continue
        before_start = max(0, start - 30)
        if start <= 0 or max(smooth[before_start:start] or [0.0]) <= pre_drop_threshold:
            continue
        candidate_peak_runs = _contiguous_true_runs(
            [index < start and flag for index, flag in enumerate(high_flags)]
        )
        if not candidate_peak_runs:
            continue
        peak_start, peak_stop = candidate_peak_runs[-1]
        candidate_peak_index = max(
            range(peak_start, peak_stop + 1), key=lambda index: y_values[index]
        )
        # A cleaning/start-up spike can occur after the real discharge.  It is
        # not a new mixing event unless the high-torque feed signal is followed
        # by a substantial working interval before the next low-torque run.
        if x_values[start] - x_values[candidate_peak_index] < minimum_mixing_span_s:
            continue
        discharge_run = (start, stop)
        selected_peak_runs = candidate_peak_runs
        break

    if discharge_run is None:
        tail_count = max(2, min(1200, int(len(points) * 0.25)))
        start_index = len(points) - tail_count
        end_index = len(points) - 1
        feed_peak_index = max(
            range(start_index, end_index + 1), key=lambda index: y_values[index]
        )
        return {
            "sample": series.sample,
            "start_s": x_values[start_index],
            "feed_peak_s": x_values[feed_peak_index],
            "discharge_drop_s": x_values[end_index],
            "end_s": x_values[end_index],
            "time_zero": "start_s",
            "source": "auto_fallback_tail",
            "confidence": 35.0,
            "needs_human_review": True,
            "reason": "Could not detect a final discharge drop; fell back to the final quarter of the trace.",
        }

    discharge_start, discharge_stop = discharge_run
    search_stop = max(0, discharge_start - 1)
    peak_runs = selected_peak_runs or _contiguous_true_runs(
        [index < search_stop and flag for index, flag in enumerate(high_flags)]
    )
    if peak_runs:
        peak_start, peak_stop = peak_runs[-1]
        feed_peak_index = max(
            range(peak_start, peak_stop + 1), key=lambda index: y_values[index]
        )
    else:
        feed_peak_index = max(
            range(0, max(1, search_stop)), key=lambda index: y_values[index]
        )

    prior_low_runs = [run for run in raw_low_runs if run[1] < feed_peak_index]
    if prior_low_runs:
        start_index = max(0, prior_low_runs[-1][0] - 5)
    else:
        time_step = _median_positive_step(x_values)
        buffer_points = max(5, int(round(60 / time_step))) if time_step else 30
        start_index = max(0, feed_peak_index - buffer_points)
    event_span = max(time_step, x_values[discharge_start] - x_values[start_index])
    post_drop_span = max(time_step * 5, min(60.0, event_span * 0.05))
    target_end = x_values[discharge_start] + post_drop_span
    end_index = discharge_start
    while end_index < discharge_stop and x_values[end_index] < target_end:
        end_index += 1
    return {
        "sample": series.sample,
        "start_s": x_values[start_index],
        "feed_peak_s": x_values[feed_peak_index],
        "discharge_drop_s": x_values[discharge_start],
        "end_s": x_values[end_index],
        "time_zero": "start_s",
        "source": "auto_detected",
        "confidence": 82.0 if peak_runs else 55.0,
        "needs_human_review": not bool(peak_runs),
        "reason": "Detected the final feed peak and discharge drop event.",
        "mixing_span_s": x_values[discharge_start] - x_values[feed_peak_index],
        "minimum_mixing_span_s": minimum_mixing_span_s,
    }


def _apply_torque_selection(
    series: CurveSeriesPayload,
    selection: dict[str, Any],
) -> CurveSeriesPayload:
    start_s = float(selection.get("start_s", series.points[0][0]))
    end_s = float(selection.get("end_s", series.points[-1][0]))
    if end_s < start_s:
        start_s, end_s = end_s, start_s
    selected = [
        (x_value, y_value)
        for x_value, y_value in series.points
        if start_s <= x_value <= end_s
    ]
    if not selected:
        selected = list(series.points)
        start_s = selected[0][0]
    zero = (
        start_s
        if selection.get("time_zero", "start_s") == "start_s"
        else selected[0][0]
    )
    sample = _clean_text(selection.get("plot_label")) or series.sample
    return CurveSeriesPayload(
        sample=sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=series.y_label,
        y_unit=series.y_unit,
        points=tuple((x_value - zero, y_value) for x_value, y_value in selected),
        diagnostics={
            **(series.diagnostics or {}),
            "event_selection": _json_safe(selection),
            "source_point_count": len(series.points),
            "selected_point_count": len(selected),
        },
    )
