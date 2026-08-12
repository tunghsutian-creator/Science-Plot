"""Project transformed stress-relaxation series into a reviewable contract."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.scientific_transform import ScientificTransformContract
from sciplot_core.semantic_sources.stress_relaxation_evidence import (
    closed_stress_relaxation_exclusions,
)


def _diagnostic_source_strings(diagnostics: dict[str, Any]) -> list[str]:
    equivalent = diagnostics.get("equivalent_source_files")
    values = equivalent if isinstance(equivalent, list) else []
    if not values and diagnostics.get("source_file"):
        values = [diagnostics["source_file"]]
    return [str(value) for value in values if str(value)]


def _stress_relaxation_contract(
    series_list: list[CurveSeriesPayload],
    *,
    selected_sources: tuple[Path, ...],
    automatic_visual_ordering: bool,
) -> ScientificTransformContract:
    x_unit = _uniform_series_value(series_list, lambda item: item.x_unit, "x unit")
    y_unit = _uniform_series_value(series_list, lambda item: item.y_unit, "y unit")
    source_columns: list[dict[str, Any]] = []
    unit_conversions: list[dict[str, Any]] = []
    anchor_selections: list[dict[str, Any]] = []
    normalizer_series: list[dict[str, Any]] = []
    output_series: list[dict[str, Any]] = []
    excluded_log_points = 0
    negative_output_values = 0

    for series in series_list:
        diagnostics = dict(series.diagnostics or {})
        columns = _source_column_contract(
            series,
            diagnostics,
            sources=_diagnostic_source_strings(diagnostics),
        )
        source_columns.append(columns)

        normalizer_operation = _normalizer_operation(diagnostics)
        source_response_unit = str(
            columns["response"].get("unit")
            or diagnostics.get("baseline_response_unit")
            or "Pa"
        )
        unit_conversions.extend(
            (
                _identity_unit_conversion(
                    series.sample,
                    "x",
                    str(columns["x"].get("unit") or series.x_unit),
                ),
                _identity_unit_conversion(
                    series.sample, "response", source_response_unit
                ),
            )
        )
        anchor_selections.append(
            _anchor_selection(series, diagnostics, normalizer_operation)
        )
        normalizer_series.append(
            {
                "sample": series.sample,
                "operation": normalizer_operation,
                "definition": str(diagnostics.get("normalization_definition") or ""),
            }
        )

        excluded_log_points += int(
            diagnostics.get("excluded_nonpositive_time_count") or 0
        ) + int(diagnostics.get("excluded_nonfinite_log_domain_point_count") or 0)
        negative_count = sum(y_value < 0.0 for _x_value, y_value in series.points)
        negative_output_values += negative_count
        source_point_count, excluded_point_count, excluded_by_reason = (
            closed_stress_relaxation_exclusions(
                diagnostics,
                retained_point_count=len(series.points),
                sample=series.sample,
            )
        )
        candidate_point_counts: dict[str, int] = {
            "response": source_point_count,
            "aligned": int(
                diagnostics.get("aligned_point_count")
                or diagnostics.get("log_domain_source_point_count")
                or len(series.points)
            ),
        }
        if diagnostics.get("source_control_point_count") is not None:
            candidate_point_counts["control"] = int(
                diagnostics.get("source_control_point_count") or 0
            )
        output_series.append(
            {
                "sample": series.sample,
                "point_count": len(series.points),
                "retained_point_count": len(series.points),
                "source_point_count": source_point_count,
                "candidate_point_counts": candidate_point_counts,
                "excluded_point_count": excluded_point_count,
                "excluded_by_reason": excluded_by_reason,
                "control_exclusions": {
                    "prior_interval": int(
                        diagnostics.get(
                            "excluded_prior_interval_control_point_count"
                        )
                        or 0
                    ),
                    "nonfinite_or_missing_time": int(
                        diagnostics.get(
                            "excluded_nonfinite_or_missing_hold_control_time_count"
                        )
                        or 0
                    ),
                    "nonfinite_or_missing": int(
                        diagnostics.get(
                            "excluded_nonfinite_or_missing_hold_control_count"
                        )
                        or 0
                    ),
                    "unmatched_response": int(
                        diagnostics.get("excluded_unmatched_hold_control_count") or 0
                    ),
                },
                "first_point": list(series.points[0]),
                "last_point": list(series.points[-1]),
                "negative_y_count": negative_count,
            }
        )

    applicable_anchors = [
        item for item in anchor_selections if bool(item.get("applicable"))
    ]
    retain_anchor = (
        all(bool(item["retained"]) for item in applicable_anchors)
        if applicable_anchors
        else None
    )
    x_values = [x for series in series_list for x, _y in series.points]
    y_values = [y for series in series_list for _x, y in series.points]
    x_finite = all(math.isfinite(value) for value in x_values)
    y_finite = all(math.isfinite(value) for value in y_values)
    x_nonpositive = sum(value <= 0.0 for value in x_values if math.isfinite(value))
    y_nonpositive = sum(value <= 0.0 for value in y_values if math.isfinite(value))
    return ScientificTransformContract(
        semantic_family="rheology_stress_relaxation",
        source_columns=tuple(source_columns),
        unit_conversions=tuple(unit_conversions),
        anchor={"scope": "per_series", "selections": anchor_selections},
        normalizer={
            "scope": "per_series",
            "output_metric": "normalized_stress",
            "output_unit": "sigma/sigma0",
            "series": normalizer_series,
        },
        x_coordinate_policy={
            "operation": "preserve_source_coordinate",
            "metric": "time",
            "unit": x_unit,
            "reset_applied": False,
        },
        retain_anchor=retain_anchor,
        axis_compatibility={
            "x": {
                "registered_scale": "log",
                "finite_compatible": x_finite,
                "log_compatible": x_finite and x_nonpositive == 0,
                "nonpositive_count": x_nonpositive,
                "excluded_incompatible_point_count": excluded_log_points,
            },
            "y": {
                "registered_scale": "linear",
                "finite_compatible": y_finite,
                "log_compatible": y_finite and y_nonpositive == 0,
                "nonpositive_count": y_nonpositive,
                "negative_values_retained": negative_output_values,
            },
        },
        output={
            "x_metric": "time",
            "x_unit": x_unit,
            "y_metric": "normalized_stress",
            "y_unit": y_unit,
            "series_order": [series.sample for series in series_list],
            "automatic_visual_ordering": automatic_visual_ordering,
            "series": output_series,
        },
        selected_sources=tuple(str(path) for path in selected_sources),
    )


def _source_column_contract(
    series: CurveSeriesPayload,
    diagnostics: dict[str, Any],
    *,
    sources: list[str],
) -> dict[str, Any]:
    exact = diagnostics.get("transform_source_columns")
    if isinstance(exact, dict):
        response_interval = exact.get("response")
        control_interval = exact.get("control")
        if isinstance(response_interval, dict) and isinstance(control_interval, dict):
            return {
                "sample": series.sample,
                "sources": sources,
                "result_index": exact.get("selected_result_index"),
                "result_label": exact.get("selected_result_label"),
                "interval_index": exact.get("interval_index"),
                "response_header_row_index": response_interval.get("header_row_index"),
                "control_header_row_index": control_interval.get("header_row_index"),
                "x": _role_column(response_interval.get("x"), "coordinate"),
                "response": _role_column(response_interval.get("y"), "response"),
                "control": _role_column(control_interval.get("y"), "control"),
            }

    payload = {
        "sample": series.sample,
        "sources": sources,
        "x": _diagnostic_column_identity(
            diagnostics,
            prefix="x",
            role="coordinate",
            fallback_header=series.x_label,
            fallback_unit=series.x_unit,
        ),
        "response": _diagnostic_column_identity(
            diagnostics,
            prefix="y",
            role="response",
            fallback_header="Shear stress",
            fallback_unit=str(
                diagnostics.get("baseline_response_unit")
                or diagnostics.get("source_y_unit")
                or "Pa"
            ),
        ),
    }
    if diagnostics.get("source_control_header") or diagnostics.get("control_signal"):
        payload["control"] = _diagnostic_column_identity(
            diagnostics,
            prefix="control",
            role="control",
            fallback_header=str(diagnostics.get("control_signal") or "Shear strain"),
            fallback_unit=str(diagnostics.get("control_signal_unit") or "%"),
        )
    return payload


def _role_column(value: object, role: str) -> dict[str, Any]:
    source = dict(value) if isinstance(value, dict) else {}
    return {"role": role, **source}


def _diagnostic_column_identity(
    diagnostics: dict[str, Any],
    *,
    prefix: str,
    role: str,
    fallback_header: str,
    fallback_unit: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": role,
        "header": str(diagnostics.get(f"source_{prefix}_header") or fallback_header),
        "unit": str(diagnostics.get(f"source_{prefix}_unit") or fallback_unit),
    }
    column_index = diagnostics.get(f"source_{prefix}_column_index")
    if isinstance(column_index, int):
        payload["column_index_zero_based"] = column_index
    return payload


def _identity_unit_conversion(
    sample: str, role: str, unit: str
) -> dict[str, Any]:
    return {
        "sample": sample,
        "role": role,
        "source_unit": unit,
        "canonical_unit": unit,
        "display_unit": unit,
        "source_to_canonical": {"factor": 1.0, "offset": 0.0},
        "canonical_to_display": {"factor": 1.0, "offset": 0.0},
    }


def _uniform_series_value(
    series_list: list[CurveSeriesPayload],
    value_of: Callable[[CurveSeriesPayload], str],
    label: str,
) -> str:
    values = {value_of(series) for series in series_list}
    if len(values) != 1:
        raise ValueError(
            f"Stress-relaxation output needs one shared {label}; found "
            f"{', '.join(sorted(values))}."
        )
    return next(iter(values))


def _normalizer_operation(diagnostics: dict[str, Any]) -> str:
    fallback = str(diagnostics.get("normalization_fallback") or "")
    if fallback == "already_normalized_source_preserved":
        return "preserve_source_normalized_response"
    if fallback == "no_control_signal_first_finite_nonzero_response":
        return "divide_by_first_finite_nonzero_response"
    return "divide_by_final_common_interval_first_aligned_response"


def _anchor_selection(
    series: CurveSeriesPayload,
    diagnostics: dict[str, Any],
    normalizer_operation: str,
) -> dict[str, Any]:
    if normalizer_operation == "preserve_source_normalized_response":
        return {
            "sample": series.sample,
            "selector": "none_source_already_normalized",
            "applicable": False,
            "retained": None,
        }
    source_time = diagnostics.get(
        "hold_onset_source_time",
        diagnostics.get("normalization_baseline_time"),
    )
    if source_time is None:
        raise ValueError(
            f"Stress-relaxation series `{series.sample}` has no normalization anchor."
        )
    anchor_point = next(
        (
            point
            for point in series.points
            if math.isclose(
                point[0],
                float(source_time),
                rel_tol=1.0e-12,
                abs_tol=1.0e-12,
            )
        ),
        None,
    )
    payload: dict[str, Any] = {
        "sample": series.sample,
        "selector": normalizer_operation.removeprefix("divide_by_"),
        "applicable": True,
        "source_time": float(source_time),
        "source_time_unit": series.x_unit,
        "retained": anchor_point is not None,
        "output_point": list(anchor_point) if anchor_point is not None else None,
    }
    baseline = diagnostics.get(
        "normalization_baseline_value", diagnostics.get("baseline_response")
    )
    if isinstance(baseline, int | float):
        payload["response_value"] = float(baseline)
        payload["response_unit"] = str(
            diagnostics.get("baseline_response_unit")
            or diagnostics.get("source_y_unit")
            or ""
        )
    control_value = diagnostics.get("hold_onset_control_value")
    if isinstance(control_value, int | float):
        payload["control_value"] = float(control_value)
        payload["control_unit"] = str(diagnostics.get("control_signal_unit") or "")
    return payload


__all__ = ["_diagnostic_source_strings", "_stress_relaxation_contract"]
