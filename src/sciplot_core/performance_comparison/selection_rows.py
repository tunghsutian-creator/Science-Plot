"""Normalize an explicit Metric subset without altering the original long table."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.performance_comparison.field_validation import _normalized_role
from sciplot_core.performance_comparison.metadata import (
    metric_unit_facts,
    read_metadata_table,
)
from sciplot_core.performance_comparison.models import PerformanceComparisonError
from sciplot_core.performance_comparison.selection import parse_performance_selection
from sciplot_core.performance_comparison.source_values import _REQUIRED_COLUMNS, _text
from sciplot_core.source_tables.parsing import DECIMAL_ROUND_TRIP_ENCODING, coerce_legacy_numeric_series, coerce_numeric_series


def normalize_selected_rows(
    source: str | Path, selection: Any, *, source_numeric_encoding: str = DECIMAL_ROUND_TRIP_ENCODING,
    compatibility_fused_digits: bool | None = True,
) -> tuple[Path, pd.DataFrame, dict[str, int], dict[str, int], int]:
    chosen = parse_performance_selection(selection)
    path, frame, columns, digest = read_metadata_table(source)
    if chosen["source_sha256"] != digest:
        raise PerformanceComparisonError(
            "performance_selection_source_changed",
            "Performance selection is bound to different original source bytes; inspect the current table again.",
        )
    facts = {item["metric_id"]: item for item in metric_unit_facts(frame, columns)}
    selected = (chosen["x_metric"], chosen["y_metric"])
    declarations = {item["metric_id"]: item for item in chosen["unit_declarations"]}
    units = {}
    unknown = [metric for metric in selected if metric not in facts]
    if unknown:
        raise PerformanceComparisonError(
            "performance_metric_unknown",
            f"Selected original Metric IDs do not exist: {unknown}; no substitute or ratio is inferred.",
        )
    for metric in selected:
        fact = facts[metric]
        if fact["unit_conflict"]:
            raise PerformanceComparisonError(
                "performance_metric_unit_conflict",
                f"Metric {metric!r} has conflicting original units: {fact['original_units']}.",
            )
        declaration = declarations.get(metric)
        if fact["missing_unit_count"] and declaration is None:
            raise PerformanceComparisonError(
                "performance_metric_unit_confirmation_required",
                f"Metric {metric!r} has missing units. Ask the original user for this Metric's unit and exact statement, bound to source_sha256={digest} and Metric ID={metric!r}.",
            )
        original = fact["original_units"]
        if declaration is not None and (
            not fact["missing_unit_count"]
            or original
            and declaration["unit"] != original[0]
        ):
            raise PerformanceComparisonError(
                "performance_metric_unit_conflict",
                f"Metric {metric!r}: a declaration may fill missing units only and cannot replace an existing unit.",
            )
        units[metric] = declaration["unit"] if declaration is not None else original[0]
    numeric = (
        coerce_legacy_numeric_series(frame[columns["value"]])
        if frame.attrs.get("sciplot_legacy_numeric_parser") is True
        else coerce_numeric_series(frame[columns["value"]], encoding=source_numeric_encoding,
                                   compatibility_fused_digits=compatibility_fused_digits)
    )
    rows: list[dict[str, Any]] = []
    materials: dict[str, int] = {}
    metric_order: dict[str, int] = {}
    observations: dict[str, dict[str, Any]] = {}
    numeric_fields = {
        "scatter_min",
        "scatter_max",
        "material_order",
        "radar_order",
        "scale_min",
        "scale_max",
    }
    for position, (index, row) in enumerate(frame.iterrows()):
        metric = _text(row[columns["metric"]])
        if metric not in selected:
            continue
        row_number = int(str(index)) + 2
        material = _text(row[columns["material"]])
        if not material:
            raise PerformanceComparisonError(
                "performance_required_value_missing",
                f"Row {row_number}: Material must be non-empty.",
            )
        role = _normalized_role(row[columns["role"]], row_number=row_number)
        value = float(numeric.iloc[position])
        if (math.isnan(value) and _text(row[columns["value"]])) or math.isinf(value):
            raise PerformanceComparisonError(
                "performance_numeric_value_invalid",
                f"Row {row_number}: selected Value must be numeric or an original missing cell.",
            )
        materials.setdefault(material, len(materials))
        metric_order.setdefault(metric, len(metric_order))
        rows.append(
            {
                "material": material,
                "role": role,
                "metric": metric,
                "value": value,
                "unit": units[metric],
                "_source_row": row_number,
                **{
                    field: row[column]
                    if field in numeric_fields
                    else _text(row[column])
                    for field, column in columns.items()
                    if field not in _REQUIRED_COLUMNS
                    and field not in {"scatter_axis", "radar_order"}
                },
                "scatter_axis": "x" if metric == selected[0] else "y",
            }
        )
        observation = observations.setdefault(
            material,
            {
                "material": material,
                "role": role,
                "x_value": None,
                "y_value": None,
                "x_source_rows": [],
                "y_source_rows": [],
            },
        )
        axis = "x" if metric == selected[0] else "y"
        observation[f"{axis}_source_rows"].append(row_number)
        observation[f"{axis}_value"] = value if math.isfinite(value) else None
    for observation in observations.values():
        observation["valid_pair"] = (
            observation["x_value"] is not None and observation["y_value"] is not None
        )
    normalized = pd.DataFrame(rows)
    normalized.attrs.update(
        {
            "performance_selection": chosen,
            "source_observations": list(observations.values()),
            "excluded_metrics": [metric for metric in facts if metric not in selected],
            "literal_metric_labels": [
                metric
                for metric in selected
                if not any(
                    row["metric"] == metric and _text(row.get("display_label"))
                    for row in rows
                )
            ],
        }
    )
    if file_sha256(path) != digest:
        raise PerformanceComparisonError(
            "performance_selection_source_changed",
            "Original table changed during Metric selection.",
        )
    return path, normalized, materials, metric_order, len(frame)
