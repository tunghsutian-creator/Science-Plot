"""Detect and normalize the terminal strain-controlled relaxation hold."""

from __future__ import annotations

import math

from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
    _StressRelaxationHoldError,
)
from sciplot_core.semantic_sources.stress_relaxation_evidence import (
    build_stress_relaxation_hold_diagnostics,
    interval_candidate_counts,
    interval_numeric_x_counts,
    unmatched_interval_identity_counts,
)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _normalize_strain_controlled_hold(
    response: CurveSeriesPayload,
    control: CurveSeriesPayload,
    *,
    y_label: str = "Normalized stress",
    y_unit: str = "sigma/sigma0",
) -> CurveSeriesPayload:
    """Crop loading and normalize from a retained, source-time hold onset."""

    response_result = (response.diagnostics or {}).get("selected_result_index")
    control_result = (control.diagnostics or {}).get("selected_result_index")
    if response_result != control_result:
        raise _StressRelaxationHoldError(
            "Stress-relaxation response and shear-strain control were selected "
            "from different result sections."
        )

    response_diagnostics = response.diagnostics or {}
    control_diagnostics = control.diagnostics or {}
    response_intervals = tuple(
        int(value)
        for value in response_diagnostics.get("selected_interval_indexes", [])
    )
    control_intervals = tuple(
        int(value) for value in control_diagnostics.get("selected_interval_indexes", [])
    )
    if response_intervals != control_intervals:
        raise _StressRelaxationHoldError(
            "Stress-relaxation response and shear-strain control expose "
            "different interval indexes."
        )
    response_point_intervals = tuple(
        int(value)
        for value in response_diagnostics.get(
            "selected_point_interval_indexes",
            [],
        )
    )
    control_point_intervals = tuple(
        int(value)
        for value in control_diagnostics.get(
            "selected_point_interval_indexes",
            [],
        )
    )
    if response_intervals:
        if len(response_point_intervals) != len(response.points):
            raise _StressRelaxationHoldError(
                "Stress-relaxation response interval identity is incomplete."
            )
        if len(control_point_intervals) != len(control.points):
            raise _StressRelaxationHoldError(
                "Shear-strain control interval identity is incomplete."
            )
        hold_interval_index = response_intervals[-1]
    else:
        hold_interval_index = 0
        response_point_intervals = (hold_interval_index,) * len(response.points)
        control_point_intervals = (hold_interval_index,) * len(control.points)

    response_numeric_x_counts = interval_numeric_x_counts(
        response_diagnostics,
        response_intervals,
        response_point_intervals,
    )
    control_numeric_x_counts = interval_numeric_x_counts(
        control_diagnostics,
        control_intervals,
        control_point_intervals,
    )
    response_candidate_counts = interval_candidate_counts(
        response_diagnostics,
        response_intervals,
        response_numeric_x_counts,
    )
    control_candidate_counts = interval_candidate_counts(
        control_diagnostics,
        control_intervals,
        control_numeric_x_counts,
    )

    control_by_identity: dict[tuple[int, float], float] = {}
    for interval_index, (x_value, y_value) in zip(
        control_point_intervals,
        control.points,
        strict=True,
    ):
        if (
            interval_index != hold_interval_index
            or not math.isfinite(x_value)
            or not math.isfinite(y_value)
        ):
            continue
        identity = (interval_index, x_value)
        if identity in control_by_identity:
            raise _StressRelaxationHoldError(
                "Shear-strain control contains duplicate time values inside "
                f"interval {interval_index}."
            )
        control_by_identity[identity] = y_value
    response_identities = [
        (interval_index, time_value)
        for interval_index, (time_value, response_value) in zip(
            response_point_intervals,
            response.points,
            strict=True,
        )
        if (
            interval_index == hold_interval_index
            and math.isfinite(time_value)
            and math.isfinite(response_value)
        )
    ]
    if len(response_identities) != len(set(response_identities)):
        raise _StressRelaxationHoldError(
            "Stress-relaxation response contains duplicate time values inside "
            f"interval {hold_interval_index}."
        )
    unmatched_response_count, unmatched_control_count = (
        unmatched_interval_identity_counts(response_identities, control_by_identity)
    )
    aligned = [
        (
            time_value,
            response_value,
            control_by_identity[(interval_index, time_value)],
        )
        for interval_index, (time_value, response_value) in zip(
            response_point_intervals,
            response.points,
            strict=True,
        )
        if (
            interval_index == hold_interval_index
            and math.isfinite(time_value)
            and math.isfinite(response_value)
            and (interval_index, time_value) in control_by_identity
        )
    ]
    if len(aligned) < 2:
        raise _StressRelaxationHoldError(
            "A strain-controlled stress-relaxation hold needs at least two "
            "aligned time, response, and shear-strain points."
        )

    aligned_control = [control_value for _time, _response, control_value in aligned]
    target_strain = _median(aligned_control)
    control_scale = max(
        (abs(control_value) for _time, _response, control_value in aligned),
        default=0.0,
    )
    near_zero_control = max(1.0e-12, control_scale * 1.0e-9)
    if abs(target_strain) <= near_zero_control:
        raise _StressRelaxationHoldError(
            "The terminal shear-strain target is zero or too close to zero to "
            "define a strain-controlled hold."
        )

    onset_index = 0
    onset_time, baseline, onset_strain = aligned[onset_index]
    response_scale = max(
        (abs(response_value) for _time, response_value, _control in aligned),
        default=0.0,
    )
    near_zero_response = max(1.0e-12, response_scale * 1.0e-9)
    if abs(baseline) <= near_zero_response:
        raise _StressRelaxationHoldError(
            "The response at the final common interval boundary is zero or too "
            "close to zero to define sigma0."
        )

    normalized_points = tuple(
        (time_value, response_value / baseline)
        for time_value, response_value, _control_value in aligned[onset_index:]
    )
    if len(normalized_points) < 2:
        raise _StressRelaxationHoldError(
            "The final common interval has fewer than two aligned response points."
        )
    normalized_values = [value for _time, value in normalized_points]
    peak_index = max(
        range(len(normalized_values)),
        key=normalized_values.__getitem__,
    )
    post_peak_sides = [value > 0.5 for value in normalized_values[peak_index:]]
    threshold_crossing_count = sum(
        left != right
        for left, right in zip(
            post_peak_sides,
            post_peak_sides[1:],
            strict=False,
        )
    )
    negative_response_count = sum(value < 0.0 for value in normalized_values)
    diagnostics = build_stress_relaxation_hold_diagnostics(
        response_diagnostics=response_diagnostics,
        control_diagnostics=control_diagnostics,
        response_result=response_result,
        response_intervals=response_intervals,
        response_point_intervals=response_point_intervals,
        response_numeric_x_counts=response_numeric_x_counts,
        control_numeric_x_counts=control_numeric_x_counts,
        response_candidate_counts=response_candidate_counts,
        control_candidate_counts=control_candidate_counts,
        hold_interval_index=hold_interval_index,
        target_strain=target_strain,
        interval_control=aligned_control,
        onset_time=onset_time,
        onset_strain=onset_strain,
        onset_index=onset_index,
        response_x_unit=response.x_unit,
        response_y_unit=response.y_unit,
        control_y_unit=control.y_unit,
        unmatched_response_count=unmatched_response_count,
        unmatched_control_count=unmatched_control_count,
        response_identity_count=len(response_identities),
        control_identity_count=len(control_by_identity),
        aligned_point_count=len(aligned),
        normalized_values=normalized_values,
        baseline=baseline,
        threshold_crossing_count=threshold_crossing_count,
        negative_response_count=negative_response_count,
    )
    return CurveSeriesPayload(
        sample=response.sample,
        x_label="Time",
        x_unit=response.x_unit,
        y_label=y_label,
        y_unit=y_unit,
        points=normalized_points,
        diagnostics=diagnostics,
    )
