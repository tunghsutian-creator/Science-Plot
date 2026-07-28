"""Normalize generic curve-series responses without mutating source payloads."""

from __future__ import annotations

import math
from sciplot_core.foundation.text_values import (
    token as _token,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)


def _normalize_series(
    series: CurveSeriesPayload, *, y_label: str, y_unit: str
) -> CurveSeriesPayload:
    if not series.points:
        return series

    diagnostics = series.diagnostics or {}
    source_measurement = " ".join(
        str(diagnostics.get(key) or "") for key in ("source_y_header", "source_y_unit")
    ).casefold()
    source_measurement_token = _token(source_measurement)
    already_normalized = (
        "normalized" in source_measurement
        or "normalised" in source_measurement
        or "归一化" in source_measurement
        or any(
            token in source_measurement_token
            for token in ("sigmasigma0", "stressstress0", "gg0", "modulusmodulus0")
        )
    )
    if already_normalized:
        return CurveSeriesPayload(
            sample=series.sample,
            x_label=series.x_label,
            x_unit=series.x_unit,
            y_label=y_label,
            y_unit=y_unit,
            points=series.points,
            diagnostics={
                **diagnostics,
                "normalization_applied": False,
                "normalization_definition": (
                    "source already reports a normalized response; preserve values and source time"
                ),
                "normalization_fallback": "already_normalized_source_preserved",
                "time_reset_definition": "preserve source time unchanged",
            },
        )

    finite_responses = [
        abs(y_value)
        for x_value, y_value in series.points
        if math.isfinite(x_value) and math.isfinite(y_value)
    ]
    response_scale = max(finite_responses, default=0.0)
    nonzero_tolerance = max(1.0e-12, response_scale * 1.0e-9)
    finite_points = [
        (x_value, y_value)
        for x_value, y_value in series.points
        if (
            math.isfinite(x_value)
            and math.isfinite(y_value)
            and abs(y_value) > nonzero_tolerance
        )
    ]
    if not finite_points:
        raise ValueError(
            "Cannot normalize a stress-relaxation curve without a non-zero finite y value."
        )
    baseline_time, baseline = finite_points[0]
    normalized_points = tuple(
        (x_value, y_value / baseline) for x_value, y_value in series.points
    )
    normalized_values = [
        value for _time, value in normalized_points if math.isfinite(value)
    ]
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=y_label,
        y_unit=y_unit,
        points=normalized_points,
        diagnostics={
            **diagnostics,
            "normalization_applied": True,
            "normalization_definition": (
                "divide by first finite non-zero response; preserve source time"
            ),
            "normalization_fallback": "no_control_signal_first_finite_nonzero_response",
            "normalization_baseline_value": baseline,
            "normalization_baseline_time": baseline_time,
            "time_reset_definition": "preserve source time unchanged",
            "normalized_minimum": min(normalized_values),
            "normalized_maximum": max(normalized_values),
            "normalized_final": normalized_values[-1],
        },
    )
