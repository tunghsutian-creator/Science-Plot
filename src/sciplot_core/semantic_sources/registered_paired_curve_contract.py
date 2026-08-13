"""Build and validate evidence for one registered paired-curve transform."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.scientific_transform import (
    ScientificTransformContract,
)
from sciplot_core.semantic_sources.transform_contract_values import (
    transform_axis_compatibility,
    transform_exclusion_counts,
)
from sciplot_core.source_tables import slugify_canonical_label


def validate_registered_paired_curve_row_evidence(
    series: CurveSeriesPayload,
    diagnostics: dict[str, Any],
    *,
    rule_id: str,
) -> None:
    candidate = int(diagnostics.get("candidate_row_count") or 0)
    retained = int(diagnostics.get("retained_point_count") or 0)
    exclusions = _exclusions(diagnostics)
    if retained != len(series.points) or candidate != retained + sum(
        exclusions.values()
    ):
        raise ValueError(
            f"{rule_id} row evidence is incomplete for {series.sample!r}."
        )
    if exclusions["nonfinite"]:
        raise ValueError(
            f"{rule_id} source contains nonfinite values for {series.sample!r}."
        )
    if not all(
        math.isfinite(x_value) and math.isfinite(y_value)
        for x_value, y_value in series.points
    ):
        raise ValueError(f"{rule_id} series {series.sample!r} is not finite.")


def build_registered_paired_curve_contract(
    series_list: list[CurveSeriesPayload],
    *,
    rule: SemanticRule,
    selected_sources: tuple[Path, ...],
    explicit_series_order_applied: bool,
) -> ScientificTransformContract:
    source_columns: list[dict[str, Any]] = []
    unit_conversions: list[dict[str, Any]] = []
    output_series: list[dict[str, Any]] = []
    for series in series_list:
        diagnostics = dict(series.diagnostics or {})
        source_columns.append(_source_columns(series, diagnostics))
        unit_conversions.extend(
            _unit_conversions(
                series,
                diagnostics,
                x_unit=rule.x_axis.canonical_unit,
                y_unit=rule.y_axis.canonical_unit,
            )
        )
        exclusions = _exclusions(diagnostics)
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
            }
        )
    x_metric = slugify_canonical_label(rule.x_axis.canonical_label)
    y_metric = slugify_canonical_label(rule.y_axis.canonical_label)
    x_values = [x for series in series_list for x, _y in series.points]
    y_values = [y for series in series_list for _x, y in series.points]
    return ScientificTransformContract(
        semantic_family=rule.semantic_family,
        source_columns=tuple(source_columns),
        unit_conversions=tuple(unit_conversions),
        anchor={"scope": "none", "selections": []},
        normalizer={
            "scope": "none",
            "operation": "none",
            "output_metric": y_metric,
            "output_unit": rule.y_axis.canonical_unit,
        },
        x_coordinate_policy={
            "operation": "preserve_source_coordinate_and_order",
            "metric": x_metric,
            "unit": rule.x_axis.canonical_unit,
            "source_row_order_preserved": True,
            "sorting_applied": False,
            "interpolation_applied": False,
        },
        retain_anchor=None,
        axis_compatibility={
            "x": transform_axis_compatibility(x_values, scale=rule.x_axis.scale),
            "y": transform_axis_compatibility(y_values, scale=rule.y_axis.scale),
        },
        output={
            "x_metric": x_metric,
            "x_unit": rule.x_axis.canonical_unit,
            "y_metric": y_metric,
            "y_unit": rule.y_axis.canonical_unit,
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
    return {
        "sample": series.sample,
        "sources": [str(diagnostics["source_file"])],
        "source_table": str(diagnostics["source_table"]),
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
        "unit": str(diagnostics[f"source_{prefix}_unit_detection_value"]),
        "column_index_zero_based": int(diagnostics[f"source_{prefix}_column_index"]),
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
    *,
    x_unit: str,
    y_unit: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        _identity_conversion(
            sample=series.sample,
            role="x",
            source_unit=str(diagnostics["source_x_unit_detection_value"]),
            canonical_unit=x_unit,
        ),
        _identity_conversion(
            sample=series.sample,
            role="response",
            source_unit=str(diagnostics["source_y_unit_detection_value"]),
            canonical_unit=y_unit,
        ),
    )


def _identity_conversion(
    *,
    sample: str,
    role: str,
    source_unit: str,
    canonical_unit: str,
) -> dict[str, Any]:
    identity = {"factor": 1.0, "offset": 0.0}
    return {
        "sample": sample,
        "role": role,
        "source_unit": source_unit,
        "canonical_unit": canonical_unit,
        "display_unit": canonical_unit,
        "source_to_canonical": dict(identity),
        "canonical_to_display": dict(identity),
    }


def _exclusions(diagnostics: dict[str, Any]) -> dict[str, int]:
    exclusions = transform_exclusion_counts(diagnostics)
    for reason, key in (
        ("nonpositive_log_x", "excluded_nonpositive_log_x_count"),
        ("nonpositive_log_y", "excluded_nonpositive_log_y_count"),
    ):
        if key in diagnostics:
            exclusions[reason] = int(diagnostics.get(key) or 0)
    return exclusions
__all__ = [
    "build_registered_paired_curve_contract",
    "validate_registered_paired_curve_row_evidence",
]
