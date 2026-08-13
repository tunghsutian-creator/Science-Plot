"""Resolve DMA temperature series and bind their scientific contract."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
    DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
    DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
    DMA_TEMPERATURE_X_METRIC,
    DMA_TEMPERATURE_Y_METRIC,
)
from sciplot_core.semantic_sources.dma_sources import (
    _read_dma_temperature_series_list,
)
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
    ScientificTransformContract,
)
from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _series_order_map,
)
from sciplot_core.semantic_sources.transform_contract_values import (
    transform_axis_compatibility,
    transform_exclusion_counts,
)


def resolve_dma_temperature_transform(
    source: Path,
    *,
    series_order: object = None,
) -> ResolvedScientificTransform:
    """Read once, retain finite measured rows, and expose one reviewable contract."""

    source = source.expanduser().resolve()
    series_list = _read_dma_temperature_series_list(source)
    explicit_order = bool(_series_order_map(series_order))
    if explicit_order:
        series_list = _order_curve_series(series_list, series_order)
    _validate_dma_series(series_list)
    selected_sources = _selected_sources(series_list)
    contract = _dma_temperature_contract(
        series_list,
        selected_sources=selected_sources,
        explicit_series_order_applied=explicit_order,
    )
    return ResolvedScientificTransform(
        series=tuple(series_list),
        contract=contract,
        selected_sources=selected_sources,
    )


def _validate_dma_series(series_list: list[CurveSeriesPayload]) -> None:
    samples = [series.sample for series in series_list]
    if not samples or any(not sample for sample in samples) or len(samples) != len(
        set(samples)
    ):
        raise ValueError("DMA temperature series need non-empty unique sample labels.")
    for series in series_list:
        diagnostics = dict(series.diagnostics or {})
        points = tuple(series.points)
        if (
            not points
            or series.x_unit != DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT
            or series.y_unit != DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT
            or not all(
                math.isfinite(x_value) and math.isfinite(y_value)
                for x_value, y_value in points
            )
        ):
            raise ValueError(
                f"DMA temperature series {series.sample!r} is not a finite °C/MPa set."
            )
        candidate = int(diagnostics.get("candidate_row_count") or 0)
        retained = int(diagnostics.get("retained_point_count") or 0)
        exclusions = transform_exclusion_counts(diagnostics)
        if retained != len(points) or candidate != retained + sum(exclusions.values()):
            raise ValueError(
                f"DMA temperature row evidence is incomplete for {series.sample!r}."
            )
        if exclusions["nonfinite"]:
            raise ValueError(
                f"DMA temperature source contains nonfinite values for {series.sample!r}."
            )


def _selected_sources(
    series_list: list[CurveSeriesPayload],
) -> tuple[Path, ...]:
    selected: list[Path] = []
    for series in series_list:
        value = str((series.diagnostics or {}).get("source_file") or "")
        path = Path(value).expanduser().resolve()
        if not value:
            raise ValueError("DMA scientific-transform evidence requires source paths.")
        if path not in selected:
            selected.append(path)
    if not selected:
        raise ValueError("DMA scientific-transform evidence has no selected source.")
    return tuple(selected)


def _dma_temperature_contract(
    series_list: list[CurveSeriesPayload],
    *,
    selected_sources: tuple[Path, ...],
    explicit_series_order_applied: bool,
) -> ScientificTransformContract:
    source_columns: list[dict[str, Any]] = []
    unit_conversions: list[dict[str, Any]] = []
    output_series: list[dict[str, Any]] = []
    for series in series_list:
        diagnostics = dict(series.diagnostics or {})
        source_columns.append(_source_columns(series, diagnostics))
        unit_conversions.extend(_unit_conversions(series, diagnostics))
        exclusions = transform_exclusion_counts(diagnostics)
        candidate = int(diagnostics["candidate_row_count"])
        output_series.append(
            {
                "sample": series.sample,
                "candidate_row_count": candidate,
                "point_count": len(series.points),
                "retained_point_count": len(series.points),
                "excluded_point_count": candidate - len(series.points),
                "excluded_by_reason": exclusions,
                "first_point": list(series.points[0]),
                "last_point": list(series.points[-1]),
                "negative_y_count": sum(y < 0.0 for _x, y in series.points),
            }
        )

    x_values = [x for series in series_list for x, _y in series.points]
    y_values = [y for series in series_list for _x, y in series.points]
    return ScientificTransformContract(
        semantic_family="dma_temperature_sweep",
        source_columns=tuple(source_columns),
        unit_conversions=tuple(unit_conversions),
        anchor={"scope": "none", "selections": []},
        normalizer={
            "scope": "none",
            "operation": "none",
            "output_metric": DMA_TEMPERATURE_Y_METRIC,
            "output_unit": DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
        },
        x_coordinate_policy={
            "operation": "preserve_source_coordinate_and_order",
            "metric": DMA_TEMPERATURE_X_METRIC,
            "unit": DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
            "source_row_order_preserved": True,
            "sorting_applied": False,
            "interpolation_applied": False,
        },
        retain_anchor=None,
        axis_compatibility={
            "x": transform_axis_compatibility(x_values, scale="linear"),
            "y": transform_axis_compatibility(y_values, scale="linear"),
        },
        output={
            "x_metric": DMA_TEMPERATURE_X_METRIC,
            "x_unit": DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
            "y_metric": DMA_TEMPERATURE_Y_METRIC,
            "y_unit": DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
            "series_order": [series.sample for series in series_list],
            "explicit_series_order_applied": explicit_series_order_applied,
            "series": output_series,
        },
        selected_sources=tuple(str(path) for path in selected_sources),
    )


def _source_columns(
    series: CurveSeriesPayload,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    source = str(diagnostics.get("source_file") or "")
    return {
        "sample": series.sample,
        "sources": [source],
        "header_row_index": int(diagnostics["source_header_row_index"]),
        "x": _column("coordinate", "x", diagnostics),
        "response": _column("response", "y", diagnostics),
    }


def _column(
    role: str,
    prefix: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "role": role,
        "header": str(diagnostics[f"source_{prefix}_header"]),
        "unit": str(diagnostics[f"source_{prefix}_unit"]),
        "column_index_zero_based": int(
            diagnostics[f"source_{prefix}_column_index"]
        ),
        "unit_detection": {
            "method": str(diagnostics[f"source_{prefix}_unit_detection"]),
            "row_index_zero_based": int(
                diagnostics[f"source_{prefix}_unit_detection_row_index"]
            ),
            "value": str(diagnostics[f"source_{prefix}_unit_detection_value"]),
        },
    }


def _unit_conversions(
    series: CurveSeriesPayload,
    diagnostics: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        {
            "sample": series.sample,
            "role": "x",
            "source_unit": str(diagnostics["source_x_unit"]),
            "canonical_unit": DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
            "display_unit": DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
            "source_to_canonical": {
                "factor": float(diagnostics["source_x_to_display_factor"]),
                "offset": float(diagnostics["source_x_to_display_offset"]),
            },
            "canonical_to_display": {"factor": 1.0, "offset": 0.0},
        },
        {
            "sample": series.sample,
            "role": "response",
            "source_unit": str(diagnostics["source_y_unit"]),
            "canonical_unit": DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
            "display_unit": DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
            "source_to_canonical": {
                "factor": float(diagnostics["source_to_canonical_factor"]),
                "offset": 0.0,
            },
            "canonical_to_display": {
                "factor": float(diagnostics["canonical_to_display_factor"]),
                "offset": 0.0,
            },
        },
    )


__all__ = ["resolve_dma_temperature_transform"]
