"""Project an already normalized source onto the explicitly selected time display."""

from __future__ import annotations

import math

from sciplot_core.semantic_sources.models import CurveSeriesPayload


def _retain_positive_stress_relaxation_time(
    series: CurveSeriesPayload, *, require_positive_anchor: bool = True,
) -> CurveSeriesPayload:
    baseline_time = (series.diagnostics or {}).get(
        "normalization_baseline_source_time",
        (series.diagnostics or {}).get("normalization_baseline_time"),
    )
    if (
        require_positive_anchor and isinstance(baseline_time, int | float)
        and math.isfinite(float(baseline_time))
        and float(baseline_time) <= 0.0
    ):
        raise ValueError(
            "The normalization anchor is not compatible with logarithmic time: "
            "its retained source time must be greater than zero."
        )
    retained = tuple(
        (time_value, response_value)
        for time_value, response_value in series.points
        if (
            math.isfinite(time_value)
            and math.isfinite(response_value)
            and time_value > 0.0
        )
    )
    excluded_nonpositive_time = sum(
        math.isfinite(time_value) and time_value <= 0.0
        for time_value, _response_value in series.points
    )
    excluded_nonfinite_points = sum(
        not (math.isfinite(time_value) and math.isfinite(response_value))
        for time_value, response_value in series.points
    )
    if len(retained) < 2:
        raise ValueError(
            "Stress-relaxation logarithmic time rendering needs at least two "
            "finite points with time > 0."
        )
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=series.y_label,
        y_unit=series.y_unit,
        points=retained,
        diagnostics={
            **(series.diagnostics or {}),
            "log_domain_source_point_count": len(series.points),
            "excluded_nonpositive_time_count": excluded_nonpositive_time,
            "excluded_nonfinite_log_domain_point_count": excluded_nonfinite_points,
            "log_domain_selected_point_count": len(retained),
            "time_log_domain_policy": (
                "retain only finite time > 0 for logarithmic time rendering"
            ),
        },
    )


def _project_stress_relaxation_time(
    series: CurveSeriesPayload, *, xscale: str, require_positive_anchor: bool = True,
) -> CurveSeriesPayload:
    if xscale not in {"log", "linear"}:
        raise ValueError("Stress-relaxation xscale must be log or linear.")
    selected = (_retain_positive_stress_relaxation_time(
        series, require_positive_anchor=require_positive_anchor,
    ) if xscale == "log" else series)
    return CurveSeriesPayload(
        sample=selected.sample, x_label=selected.x_label, x_unit=selected.x_unit,
        y_label=selected.y_label, y_unit=selected.y_unit, points=selected.points,
        diagnostics={**(selected.diagnostics or {}),
            "pre_display_point_count": len(series.points),
            "pre_display_first_point": list(series.points[0]),
            "active_display_scale": xscale,
            "display_excluded_point_count": len(series.points) - len(selected.points)},
    )
