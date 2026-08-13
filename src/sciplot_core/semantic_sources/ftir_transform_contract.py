"""Build the evidence-bearing FTIR scientific-transform contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.scientific_transform import (
    ScientificTransformContract,
)
from sciplot_core.semantic_sources.transform_contract_values import (
    transform_axis_compatibility,
)


FTIR_X_LABEL = "Wavenumber"
FTIR_X_UNIT = "cm^-1"
FTIR_X_METRIC = "wavenumber"
FTIR_Y_METRIC = "spectral_response"
FTIR_Y_LABELS = {
    "transmittance": "Transmittance",
    "absorbance": "Absorbance",
    "unknown": "Spectral response",
}


def build_ftir_transform_contract(
    series_list: list[CurveSeriesPayload],
    *,
    selected_sources: tuple[Path, ...],
    explicit_series_order_applied: bool,
) -> ScientificTransformContract:
    """Describe source columns, untouched rows, and FTIR response identity."""

    mode = str((series_list[0].diagnostics or {})["ftir_response_mode"])
    y_unit = series_list[0].y_unit
    x_values = [x for series in series_list for x, _y in series.points]
    y_values = [y for series in series_list for _x, y in series.points]
    return ScientificTransformContract(
        semantic_family="ftir_spectrum",
        source_columns=tuple(_source_columns(series) for series in series_list),
        unit_conversions=tuple(
            record for series in series_list for record in _unit_records(series)
        ),
        anchor={"scope": "none", "selections": []},
        normalizer={
            "scope": "none",
            "operation": "none",
            "output_metric": FTIR_Y_METRIC,
            "output_unit": y_unit,
        },
        x_coordinate_policy={
            "operation": "preserve_source_coordinate_and_order",
            "metric": FTIR_X_METRIC,
            "unit": FTIR_X_UNIT,
            "source_row_order_preserved": True,
            "sorting_applied": False,
            "interpolation_applied": False,
        },
        retain_anchor=None,
        axis_compatibility={
            "x": transform_axis_compatibility(
                x_values, scale="linear", require_values=True
            ),
            "y": transform_axis_compatibility(
                y_values, scale="linear", require_values=True
            ),
        },
        output={
            "x_metric": FTIR_X_METRIC,
            "x_label": FTIR_X_LABEL,
            "x_unit": FTIR_X_UNIT,
            "y_metric": FTIR_Y_METRIC,
            "y_label": series_list[0].y_label,
            "y_unit": y_unit,
            "response_mode": mode,
            "series_order": [series.sample for series in series_list],
            "explicit_series_order_applied": explicit_series_order_applied,
            "series": [_series_evidence(series) for series in series_list],
        },
        selected_sources=tuple(str(path) for path in selected_sources),
    )


def _source_columns(series: CurveSeriesPayload) -> dict[str, Any]:
    data = dict(series.diagnostics or {})
    return {
        "sample": series.sample,
        "sources": [str(data["source_file"])],
        "source_table": str(data["source_table"]),
        "header_row_index": data["source_header_row_index"],
        "data_start_row_index": int(data["source_data_start_row_index"]),
        "x": {
            **_column("coordinate", "x", data),
            "authority": "selected_rule_axis_contract",
        },
        "response": {
            **_column("response", "y", data),
            "response_mode": data["ftir_response_mode"],
            "response_mode_detection": data["ftir_response_mode_detection"],
        },
    }


def _column(role: str, axis: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": role,
        "header": str(data[f"source_{axis}_header"]),
        "unit": str(data[f"source_{axis}_unit"]),
        "column_index_zero_based": int(data[f"source_{axis}_column_index"]),
        "unit_detection": {
            "method": str(data[f"source_{axis}_unit_detection"]),
            "row_index_zero_based": data[f"source_{axis}_unit_detection_row_index"],
            "value": str(data[f"source_{axis}_unit_detection_value"]),
        },
    }


def _unit_records(
    series: CurveSeriesPayload,
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = dict(series.diagnostics or {})
    source_x_unit = str(data["source_x_unit"])
    return (
        {
            "sample": series.sample,
            "role": "x",
            "source_unit": source_x_unit,
            "output_unit": FTIR_X_UNIT,
            "source_unit_declared": bool(source_x_unit),
            "authority": "selected_rule_axis_contract",
            "operation": "identity_no_numeric_conversion",
        },
        {
            "sample": series.sample,
            "role": "response",
            "source_unit": series.y_unit,
            "output_unit": series.y_unit,
            "source_unit_declared": bool(series.y_unit),
            "authority": (
                "explicit_source_declaration" if series.y_unit else "undeclared"
            ),
            "operation": "identity_no_numeric_conversion",
        },
    )


def _series_evidence(series: CurveSeriesPayload) -> dict[str, Any]:
    data = dict(series.diagnostics or {})
    candidate = int(data["candidate_row_count"])
    retained = int(data["retained_point_count"])
    exclusions = {
        "empty_pair": int(data["excluded_empty_pair_count"]),
        "partial_or_nonnumeric": int(data["excluded_partial_or_nonnumeric_pair_count"]),
        "nonfinite": int(data["excluded_nonfinite_pair_count"]),
    }
    return {
        "sample": series.sample,
        "source": str(data["source_file"]),
        "response_mode": data["ftir_response_mode"],
        "x_label": series.x_label,
        "x_unit": series.x_unit,
        "y_label": series.y_label,
        "y_unit": series.y_unit,
        "candidate_row_count": candidate,
        "point_count": len(series.points),
        "retained_point_count": retained,
        "excluded_point_count": candidate - retained,
        "excluded_by_reason": exclusions,
        "first_point": list(series.points[0]),
        "last_point": list(series.points[-1]),
    }


__all__ = [
    "FTIR_X_LABEL",
    "FTIR_X_UNIT",
    "FTIR_Y_LABELS",
    "build_ftir_transform_contract",
]
