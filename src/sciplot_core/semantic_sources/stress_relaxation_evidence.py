"""Project stress-relaxation hold selection into structured diagnostics."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def interval_numeric_x_counts(
    diagnostics: dict[str, Any],
    interval_indexes: tuple[int, ...],
    point_intervals: tuple[int, ...],
) -> dict[int, int]:
    """Return recorded numeric-x counts or the existing point-count fallback."""

    counts = diagnostics.get("selected_interval_numeric_x_row_counts")
    if isinstance(counts, list) and len(counts) == len(interval_indexes):
        recorded = {
            interval_index: int(count)
            for interval_index, count in zip(interval_indexes, counts, strict=True)
            if isinstance(count, int | float)
        }
        if recorded:
            return recorded
    return {
        interval_index: sum(
            point_interval == interval_index for point_interval in point_intervals
        )
        for interval_index in set(point_intervals)
    }


def interval_candidate_counts(
    diagnostics: dict[str, Any],
    interval_indexes: tuple[int, ...],
    numeric_x_counts: dict[int, int],
) -> dict[int, int]:
    """Return rows with a numeric coordinate or response/control value."""

    counts = diagnostics.get("selected_interval_candidate_row_counts")
    if isinstance(counts, list) and len(counts) == len(interval_indexes):
        recorded = {
            interval_index: int(count)
            for interval_index, count in zip(interval_indexes, counts, strict=True)
            if isinstance(count, int | float)
        }
        if recorded:
            return recorded
    return dict(numeric_x_counts)


def unmatched_interval_identity_counts(
    response_identities: Iterable[tuple[int, float]],
    control_identities: Iterable[tuple[int, float]],
) -> tuple[int, int]:
    """Count unmatched response and control identities without changing alignment."""

    response_set = set(response_identities)
    control_set = set(control_identities)
    return (
        len(response_set - control_set),
        len(control_set - response_set),
    )


def closed_stress_relaxation_exclusions(
    diagnostics: dict[str, Any],
    *,
    retained_point_count: int,
    sample: str,
) -> tuple[int, int, dict[str, int]]:
    """Return mutually exclusive response exclusions that exactly close candidates."""

    reasons = {
        "prior_interval": int(
            diagnostics.get(
                "excluded_prior_interval_response_point_count",
                diagnostics.get("excluded_prior_interval_points") or 0,
            )
        ),
        "nonfinite_or_missing_time": int(
            diagnostics.get("excluded_nonfinite_or_missing_hold_response_time_count")
            or 0
        ),
        "nonfinite_or_missing_response": int(
            diagnostics.get("excluded_nonfinite_or_missing_hold_response_count") or 0
        ),
        "unmatched_response_control": int(
            diagnostics.get("excluded_unmatched_hold_response_count") or 0
        ),
        "loading_before_anchor": int(diagnostics.get("excluded_loading_points") or 0),
        "nonpositive_log_x": int(
            diagnostics.get("excluded_nonpositive_time_count") or 0
        ),
        "nonfinite_log_point": int(
            diagnostics.get("excluded_nonfinite_log_domain_point_count") or 0
        ),
    }
    source_count_value = diagnostics.get("source_point_count")
    if not isinstance(source_count_value, int | float):
        source_count_value = diagnostics.get("log_domain_source_point_count")
    source_point_count = (
        int(source_count_value)
        if isinstance(source_count_value, int | float)
        else retained_point_count
    )
    excluded_point_count = source_point_count - retained_point_count
    if excluded_point_count < 0 or sum(reasons.values()) != excluded_point_count:
        raise ValueError(
            f"Stress-relaxation exclusion evidence is incomplete for {sample!r}."
        )
    reasons["other_parser_exclusion"] = 0
    return source_point_count, excluded_point_count, reasons


def build_stress_relaxation_hold_diagnostics(
    *,
    response_diagnostics: dict[str, Any],
    control_diagnostics: dict[str, Any],
    response_result: object,
    response_intervals: tuple[int, ...],
    response_point_intervals: tuple[int, ...],
    response_numeric_x_counts: dict[int, int],
    control_numeric_x_counts: dict[int, int],
    response_candidate_counts: dict[int, int],
    control_candidate_counts: dict[int, int],
    hold_interval_index: int,
    target_strain: float,
    interval_control: list[float],
    onset_time: float,
    onset_strain: float,
    onset_index: int,
    response_x_unit: str,
    response_y_unit: str,
    control_y_unit: str,
    unmatched_response_count: int,
    unmatched_control_count: int,
    response_identity_count: int,
    control_identity_count: int,
    aligned_point_count: int,
    normalized_values: list[float],
    baseline: float,
    threshold_crossing_count: int,
    negative_response_count: int,
) -> dict[str, Any]:
    """Assemble source-boundary normalization and exclusion evidence."""

    response_invalid_time = response_candidate_counts.get(
        hold_interval_index, 0
    ) - response_numeric_x_counts.get(hold_interval_index, 0)
    control_invalid_time = control_candidate_counts.get(
        hold_interval_index, 0
    ) - control_numeric_x_counts.get(hold_interval_index, 0)
    response_invalid_value = (
        response_numeric_x_counts.get(hold_interval_index, 0)
        - response_identity_count
    )
    control_invalid_value = (
        control_numeric_x_counts.get(hold_interval_index, 0)
        - control_identity_count
    )
    if min(
        response_invalid_time,
        control_invalid_time,
        response_invalid_value,
        control_invalid_value,
    ) < 0:
        raise ValueError("Stress-relaxation interval evidence is inconsistent.")

    return {
        **response_diagnostics,
        "transform_source_columns": {
            "selected_result_index": response_result,
            "selected_result_label": response_diagnostics.get(
                "selected_result_label"
            ),
            "interval_index": hold_interval_index,
            "response": _interval_column_identity(
                response_diagnostics, hold_interval_index
            ),
            "control": _interval_column_identity(
                control_diagnostics, hold_interval_index
            ),
        },
        "source_control_column_index": control_diagnostics.get(
            "source_y_column_index"
        ),
        "source_control_header": control_diagnostics.get("source_y_header"),
        "source_control_unit": control_diagnostics.get(
            "source_y_unit", control_y_unit
        ),
        "control_signal": "Shear strain",
        "control_signal_unit": control_y_unit,
        "target_strain": target_strain,
        "target_strain_unit": control_y_unit,
        "hold_target_strain": target_strain,
        "hold_target_strain_unit": control_y_unit,
        "hold_tolerance": None,
        "hold_tolerance_unit": control_y_unit,
        "hold_detection_tolerance": None,
        "hold_detection_tolerance_unit": control_y_unit,
        "hold_detection_minimum_consecutive_points": None,
        "hold_post_onset_inside_fraction": None,
        "hold_post_onset_maximum_deviation": max(
            abs(value - target_strain) for value in interval_control
        ),
        "hold_onset_source_time": onset_time,
        "hold_onset_source_time_unit": response_x_unit,
        "hold_onset_control_value": onset_strain,
        "hold_interval_selection_policy": "last_common_selected_interval",
        "hold_interval_index": hold_interval_index,
        "available_interval_indexes": list(response_intervals),
        "excluded_prior_interval_points": sum(
            1
            for interval_index in response_point_intervals
            if interval_index != hold_interval_index
        ),
        "excluded_prior_interval_response_point_count": sum(
            count
            for interval_index, count in response_candidate_counts.items()
            if interval_index != hold_interval_index
        ),
        "excluded_prior_interval_control_point_count": sum(
            count
            for interval_index, count in control_candidate_counts.items()
            if interval_index != hold_interval_index
        ),
        "excluded_nonfinite_or_missing_hold_response_time_count": (
            response_invalid_time
        ),
        "excluded_nonfinite_or_missing_hold_control_time_count": control_invalid_time,
        "excluded_nonfinite_or_missing_hold_response_count": response_invalid_value,
        "excluded_nonfinite_or_missing_hold_control_count": control_invalid_value,
        "excluded_unmatched_hold_response_count": unmatched_response_count,
        "excluded_unmatched_hold_control_count": unmatched_control_count,
        "excluded_loading_points": onset_index,
        "excluded_hold_onset_points": 0,
        "source_point_count": sum(response_candidate_counts.values()),
        "source_control_point_count": sum(control_candidate_counts.values()),
        "aligned_point_count": aligned_point_count,
        "selected_point_count": len(normalized_values),
        "time_reset_applied": False,
        "time_reset_definition": "not applied; source time is preserved",
        "time_coordinate_definition": (
            "time = source_time; preserve every aligned point in the final "
            "common source interval"
        ),
        "normalization_definition": (
            "divide every aligned response in the final common source interval "
            "by its first response; retain the interval-boundary point as "
            "sigma/sigma0 = 1"
        ),
        "baseline_response": baseline,
        "baseline_response_unit": response_y_unit,
        "sigma0": baseline,
        "sigma0_unit": response_y_unit,
        "normalization_baseline_value": baseline,
        "normalization_baseline_source_time": onset_time,
        "normalization_baseline_time": onset_time,
        "normalized_minimum": min(normalized_values),
        "normalized_maximum": max(normalized_values),
        "normalized_final": normalized_values[-1],
        "negative_normalized_response_count": negative_response_count,
        "post_peak_half_response_crossing_count": threshold_crossing_count,
        "normalization_quality": (
            "review_noisy_or_nonmonotonic_response"
            if negative_response_count or threshold_crossing_count > 1
            else "passed"
        ),
    }


def _interval_column_identity(
    diagnostics: dict[str, Any], interval_index: int
) -> dict[str, Any]:
    entries = diagnostics.get("selected_interval_columns")
    if not isinstance(entries, list):
        return {}
    return next(
        (
            dict(entry)
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("interval_index") == interval_index
        ),
        {},
    )


__all__ = [
    "build_stress_relaxation_hold_diagnostics",
    "closed_stress_relaxation_exclusions",
    "interval_candidate_counts",
    "interval_numeric_x_counts",
    "unmatched_interval_identity_counts",
]
