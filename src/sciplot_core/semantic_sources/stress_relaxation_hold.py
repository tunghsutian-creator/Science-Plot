"""Detect and normalize the terminal strain-controlled relaxation hold."""

from __future__ import annotations

import math


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
    _StressRelaxationHoldError,
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
    if len(aligned) < 6:
        raise _StressRelaxationHoldError(
            "A strain-controlled stress-relaxation hold needs at least six "
            "aligned time, response, and shear-strain points."
        )

    tail_count = min(len(aligned), max(5, math.ceil(len(aligned) * 0.2)))
    tail_control = [
        control_value for _time, _response, control_value in aligned[-tail_count:]
    ]
    target_strain = _median(tail_control)
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

    tail_mad = _median([abs(value - target_strain) for value in tail_control])
    relative_tolerance = abs(target_strain) * 0.01
    tolerance = max(relative_tolerance, 3.0 * 1.4826 * tail_mad, 1.0e-12)
    maximum_reasonable_tolerance = max(abs(target_strain) * 0.05, 1.0e-12)
    if tolerance > maximum_reasonable_tolerance:
        raise _StressRelaxationHoldError(
            "The terminal shear-strain signal does not form a stable target "
            "platform within a five-percent relative tolerance."
        )
    tail_inside_count = sum(
        abs(value - target_strain) <= tolerance + 1.0e-12 for value in tail_control
    )
    minimum_tail_inside = max(3, math.ceil(tail_count * 0.8))
    if tail_inside_count < minimum_tail_inside:
        raise _StressRelaxationHoldError(
            "The terminal shear-strain signal does not contain a sufficiently "
            "stable target platform."
        )

    minimum_consecutive = 3
    onset_index: int | None = None
    for index in range(len(aligned) - minimum_consecutive + 1):
        window = aligned[index : index + minimum_consecutive]
        window_inside = all(
            abs(control_value - target_strain) <= tolerance + 1.0e-12
            for _time, _response, control_value in window
        )
        remaining_control = [
            control_value for _time, _response, control_value in aligned[index:]
        ]
        remaining_inside = sum(
            abs(control_value - target_strain) <= tolerance + 1.0e-12
            for control_value in remaining_control
        )
        remaining_inside_fraction = remaining_inside / len(remaining_control)
        remaining_maximum_deviation = max(
            abs(control_value - target_strain) for control_value in remaining_control
        )
        if (
            window_inside
            and remaining_inside_fraction >= 0.9
            and remaining_maximum_deviation <= maximum_reasonable_tolerance + 1.0e-12
        ):
            onset_index = index
            break
    if onset_index is None:
        raise _StressRelaxationHoldError(
            "No shear-strain hold onset has at least three consecutive points "
            "inside the terminal-platform tolerance."
        )

    onset_time, baseline, onset_strain = aligned[onset_index]
    response_scale = max(
        (abs(response_value) for _time, response_value, _control in aligned),
        default=0.0,
    )
    near_zero_response = max(1.0e-12, response_scale * 1.0e-9)
    if abs(baseline) <= near_zero_response:
        raise _StressRelaxationHoldError(
            "The response at the detected shear-strain hold onset is zero or "
            "too close to zero to define sigma0."
        )

    normalized_points = tuple(
        (time_value, response_value / baseline)
        for time_value, response_value, _control_value in aligned[onset_index:]
    )
    if len(normalized_points) < 2:
        raise _StressRelaxationHoldError(
            "The detected hold has fewer than two response points at or after onset."
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
    post_onset_control = [
        control_value for _time, _response, control_value in aligned[onset_index:]
    ]
    diagnostics = {
        **(response.diagnostics or {}),
        "control_signal": "Shear strain",
        "control_signal_unit": control.y_unit,
        "target_strain": target_strain,
        "target_strain_unit": control.y_unit,
        "hold_target_strain": target_strain,
        "hold_target_strain_unit": control.y_unit,
        "hold_tolerance": tolerance,
        "hold_tolerance_unit": control.y_unit,
        "hold_detection_tolerance": tolerance,
        "hold_detection_tolerance_unit": control.y_unit,
        "hold_detection_minimum_consecutive_points": minimum_consecutive,
        "hold_post_onset_inside_fraction": (
            sum(
                abs(value - target_strain) <= tolerance + 1.0e-12
                for value in post_onset_control
            )
            / len(post_onset_control)
        ),
        "hold_post_onset_maximum_deviation": max(
            abs(value - target_strain) for value in post_onset_control
        ),
        "hold_onset_source_time": onset_time,
        "hold_onset_source_time_unit": response.x_unit,
        "hold_onset_control_value": onset_strain,
        "hold_interval_selection_policy": "last_common_selected_interval",
        "hold_interval_index": hold_interval_index,
        "available_interval_indexes": list(response_intervals),
        "excluded_prior_interval_points": sum(
            1
            for interval_index in response_point_intervals
            if interval_index != hold_interval_index
        ),
        "excluded_loading_points": onset_index,
        "excluded_hold_onset_points": 0,
        "source_point_count": len(aligned),
        "selected_point_count": len(normalized_points),
        "time_reset_applied": False,
        "time_reset_definition": (
            "not applied; source time is preserved"
        ),
        "time_coordinate_definition": (
            "time = source_time; preserve the instrument time at and after "
            "the detected hold onset"
        ),
        "normalization_definition": (
            "divide the response at and after detected shear-strain hold onset "
            "by the onset response; retain the onset point as sigma/sigma0 = 1"
        ),
        "baseline_response": baseline,
        "baseline_response_unit": response.y_unit,
        "sigma0": baseline,
        "sigma0_unit": response.y_unit,
        "normalization_baseline_value": baseline,
        "normalization_baseline_source_time": onset_time,
        "normalization_baseline_time": onset_time,
        "normalized_minimum": min(normalized_values),
        "normalized_maximum": max(normalized_values),
        "normalized_final": normalized_values[-1],
        "negative_normalized_response_count": negative_response_count,
        "post_peak_half_response_crossing_count": (threshold_crossing_count),
        "normalization_quality": (
            "review_noisy_or_nonmonotonic_response"
            if negative_response_count or threshold_crossing_count > 1
            else "passed"
        ),
    }
    return CurveSeriesPayload(
        sample=response.sample,
        x_label="Time",
        x_unit=response.x_unit,
        y_label=y_label,
        y_unit=y_unit,
        points=normalized_points,
        diagnostics=diagnostics,
    )
