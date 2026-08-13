"""Build the source-bound transform contract for GPC/SEC RI traces."""

from __future__ import annotations

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
from sciplot_core.source_tables import slugify_label


def build_gpc_transform_contract(
    series_list: list[CurveSeriesPayload],
    *,
    rule: SemanticRule,
    selected_sources: tuple[Path, ...],
    explicit_series_order_applied: bool,
) -> ScientificTransformContract:
    x_metric = slugify_label(rule.x_axis.canonical_label)
    y_metric = slugify_label(rule.y_axis.canonical_label)
    source_columns: list[dict[str, Any]] = []
    conversions: list[dict[str, Any]] = []
    output_series: list[dict[str, Any]] = []
    for series in series_list:
        diagnostics = dict(series.diagnostics or {})
        source_columns.append(_source_columns(series, diagnostics))
        source_x_unit = str(
            diagnostics.get("source_x_unit_detection_value") or series.x_unit
        )
        source_y_unit = str(
            diagnostics.get("source_y_unit_detection_value") or series.y_unit
        )
        for role, source_unit, canonical_unit in (
            ("x", source_x_unit, rule.x_axis.canonical_unit),
            ("response", source_y_unit, rule.y_axis.canonical_unit),
        ):
            conversions.append(
                {
                    "sample": series.sample,
                    "role": role,
                    "source_unit": source_unit,
                    "canonical_unit": canonical_unit,
                    "display_unit": canonical_unit,
                    "source_to_canonical": {"factor": 1.0, "offset": 0.0},
                    "canonical_to_display": {"factor": 1.0, "offset": 0.0},
                }
            )
        exclusions = gpc_exclusions(diagnostics)
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
    x_values = [x for series in series_list for x, _y in series.points]
    y_values = [y for series in series_list for _x, y in series.points]
    return ScientificTransformContract(
        semantic_family=rule.semantic_family,
        source_columns=tuple(source_columns),
        unit_conversions=tuple(conversions),
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
        "source_collection_point_count": diagnostics.get(
            "source_collection_point_count"
        ),
        "x": _column("coordinate", "x", diagnostics),
        "response": _column("response", "y", diagnostics),
    }


def _column(
    role: str,
    prefix: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    detection: dict[str, Any] = {
        "method": str(diagnostics[f"source_{prefix}_unit_detection"]),
        "row_index_zero_based": int(
            diagnostics[f"source_{prefix}_unit_detection_row_index"]
        ),
        "value": str(diagnostics[f"source_{prefix}_unit_detection_value"]),
    }
    detection_table = diagnostics.get(f"source_{prefix}_unit_detection_table")
    if detection_table:
        detection["source_table"] = str(detection_table)
    return {
        "role": role,
        "header": str(diagnostics[f"source_{prefix}_header"]),
        "unit": str(diagnostics[f"source_{prefix}_unit_detection_value"]),
        "column_index_zero_based": int(
            diagnostics[f"source_{prefix}_column_index"]
        ),
        "unit_detection": detection,
    }


def gpc_exclusions(diagnostics: dict[str, Any]) -> dict[str, int]:
    return transform_exclusion_counts(diagnostics)


__all__ = ["build_gpc_transform_contract", "gpc_exclusions"]
