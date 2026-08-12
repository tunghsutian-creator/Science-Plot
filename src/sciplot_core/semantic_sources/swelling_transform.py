"""Resolve swelling data into the shared source-bound transform contract."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
    ScientificTransformContract,
)
from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _series_order_map,
)
from sciplot_core.semantic_sources.swelling_sources import (
    _read_swelling_series_list,
)
from sciplot_core.semantic_sources.table_source_files import (
    resolve_single_table_source,
)


def resolve_swelling_scientific_transform(
    source: Path,
    *,
    series_order: object = None,
) -> ResolvedScientificTransform:
    """Read one authoritative swelling table once and preserve its curve rows."""

    resolved_source = resolve_single_table_source(
        source,
        context="swelling transform",
    )
    series_list = _read_swelling_series_list(resolved_source)
    if not series_list:
        raise ValueError(
            f"No finite labeled time/swelling-ratio curves found in {resolved_source}."
        )
    _validate_series(series_list)
    requested_order = _series_order_map(series_order)
    explicit_order = bool(requested_order)
    if explicit_order:
        unknown = tuple(
            sample for sample in requested_order if sample not in {item.sample for item in series_list}
        )
        if unknown:
            raise ValueError(
                "Swelling series_order contains unknown source identities: "
                f"{', '.join(unknown)}."
            )
        series_list = _order_curve_series(series_list, series_order)
    selected_sources = (resolved_source,)
    return ResolvedScientificTransform(
        series=tuple(series_list),
        contract=_build_swelling_contract(
            series_list,
            selected_sources=selected_sources,
            explicit_series_order_applied=explicit_order,
        ),
        selected_sources=selected_sources,
    )


def _validate_series(series_list: list[CurveSeriesPayload]) -> None:
    samples = [series.sample for series in series_list]
    if len(samples) != len(set(samples)):
        raise ValueError("Swelling source-derived series identities are not unique.")
    for series in series_list:
        if not series.sample or not series.points:
            raise ValueError("Swelling source emitted an unidentified empty curve.")
        if (
            series.x_label != "Time"
            or series.x_unit != "h"
            or series.y_label != "Swelling ratio"
            or series.y_unit != "1"
        ):
            raise RuntimeError("Swelling transform axis identity is inconsistent.")
        if not all(
            math.isfinite(x_value) and math.isfinite(y_value)
            for x_value, y_value in series.points
        ):
            raise RuntimeError(
                f"Swelling series {series.sample!r} contains nonfinite values."
            )
        _validate_selection_closure(series)


def _validate_selection_closure(series: CurveSeriesPayload) -> None:
    block = dict((series.diagnostics or {}).get("source_block") or {})
    retained = int(block.get("retained_point_count") or 0)
    if retained != len(series.points):
        raise RuntimeError(
            f"Swelling retained-row evidence does not match {series.sample!r}."
        )
    excluded = sum(
        int(block.get(key) or 0)
        for key in (
            "excluded_disconnected_point_count",
            "excluded_partial_pair_count",
            "excluded_nonnumeric_pair_count",
            "excluded_nonfinite_pair_count",
        )
    )
    if int(block.get("candidate_pair_row_count") or 0) != retained + excluded:
        raise RuntimeError(
            f"Swelling source selection evidence is incomplete for {series.sample!r}."
        )
    if int(block.get("excluded_nonfinite_pair_count") or 0):
        raise ValueError(
            f"Swelling source contains nonfinite values for {series.sample!r}."
        )


def _build_swelling_contract(
    series_list: list[CurveSeriesPayload],
    *,
    selected_sources: tuple[Path, ...],
    explicit_series_order_applied: bool,
) -> ScientificTransformContract:
    x_values = [x for series in series_list for x, _y in series.points]
    y_values = [y for series in series_list for _x, y in series.points]
    return ScientificTransformContract(
        semantic_family="swelling_curve",
        source_columns=tuple(_source_columns(series) for series in series_list),
        unit_conversions=tuple(
            record for series in series_list for record in _unit_records(series)
        ),
        anchor={"scope": "none", "selections": []},
        normalizer={
            "scope": "none",
            "operation": "none",
            "output_metric": "swelling_ratio",
            "output_unit": "1",
        },
        x_coordinate_policy={
            "operation": (
                "convert_explicit_time_unit_and_preserve_source_row_order"
            ),
            "metric": "time",
            "unit": "h",
            "source_row_order_preserved": True,
            "sorting_applied": False,
            "interpolation_applied": False,
        },
        retain_anchor=None,
        axis_compatibility={
            "x": _axis_compatibility(x_values),
            "y": _axis_compatibility(y_values),
        },
        output={
            "x_metric": "time",
            "x_label": "Time",
            "x_unit": "h",
            "y_metric": "swelling_ratio",
            "y_label": "Swelling ratio",
            "y_unit": "1",
            "series_order": [series.sample for series in series_list],
            "explicit_series_order_applied": explicit_series_order_applied,
            "series": [_series_evidence(series) for series in series_list],
        },
        selected_sources=tuple(str(path) for path in selected_sources),
    )


def _source_columns(series: CurveSeriesPayload) -> dict[str, Any]:
    diagnostics = dict(series.diagnostics or {})
    columns = dict(diagnostics["source_columns"])
    indices = dict(diagnostics["source_column_indices"])
    block = dict(diagnostics["source_block"])
    return {
        "sample": series.sample,
        "sources": [str(diagnostics["source_file"])],
        "source_table": str(diagnostics["source_table"]),
        "header_row_index": int(diagnostics["source_header_row_index"]),
        "retained_source_row_span": [
            block["source_data_row_start"],
            block["source_data_row_end"],
        ],
        "identity": dict(diagnostics["source_identity"]),
        "x": {
            "role": "coordinate",
            "header": str(columns["x"]),
            "unit": str(diagnostics["time_conversion"]["source_unit"]),
            "column_index_zero_based": int(indices["x"]),
        },
        "response": {
            "role": "response",
            "header": str(columns["y"]),
            "unit": str(diagnostics["response_unit_evidence"]["source_unit"]),
            "column_index_zero_based": int(indices["y"]),
            "unit_detection": dict(diagnostics["response_unit_evidence"]),
        },
    }


def _unit_records(series: CurveSeriesPayload) -> tuple[dict[str, Any], dict[str, Any]]:
    diagnostics = dict(series.diagnostics or {})
    conversion = dict(diagnostics["time_conversion"])
    response = dict(diagnostics["response_unit_evidence"])
    return (
        {
            "sample": series.sample,
            "role": "x",
            "source_unit": conversion["source_unit"],
            "canonical_unit": conversion["canonical_unit"],
            "operation": "multiply_by_explicit_time_unit_factor",
            "factor": float(conversion["factor"]),
            "offset": 0.0,
        },
        {
            "sample": series.sample,
            "role": "response",
            "source_unit": response["source_unit"],
            "canonical_unit": response["canonical_unit"],
            "operation": "identity_no_numeric_conversion",
            "factor": 1.0,
            "offset": 0.0,
            "authority": response["method"],
        },
    )


def _series_evidence(series: CurveSeriesPayload) -> dict[str, Any]:
    diagnostics = dict(series.diagnostics or {})
    block = dict(diagnostics["source_block"])
    return {
        "sample": series.sample,
        "point_count": len(series.points),
        "first_point": list(series.points[0]),
        "last_point": list(series.points[-1]),
        "source_selection": block,
    }


def _axis_compatibility(values: list[float]) -> dict[str, Any]:
    finite = bool(values) and all(math.isfinite(value) for value in values)
    nonpositive = sum(value <= 0.0 for value in values if math.isfinite(value))
    return {
        "registered_scale": "linear",
        "finite_compatible": finite,
        "log_compatible": finite and nonpositive == 0,
        "nonpositive_count": nonpositive,
    }


__all__ = ["resolve_swelling_scientific_transform"]
