"""Normalize tidy performance rows while preserving first-seen source order."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.performance_comparison.models import PerformanceComparisonError
from sciplot_core.performance_comparison.field_validation import (
    _normalized_role,
)
from sciplot_core.performance_comparison.source_tables import (
    _canonical_header_map,
    _read_source_frame,
    _resolve_source,
)
from sciplot_core.performance_comparison.source_values import (
    _REQUIRED_COLUMNS,
    _finite_float,
    _text,
)


def normalize_performance_rows(
    source: str | Path,
) -> tuple[Path, pd.DataFrame, dict[str, int], dict[str, int], int]:
    """Read required columns and return normalized rows plus stable orders."""

    source_path = _resolve_source(Path(source))
    frame = _read_source_frame(source_path).dropna(how="all").reset_index(drop=True)
    columns = _canonical_header_map(frame.columns)
    missing = sorted(_REQUIRED_COLUMNS - set(columns))
    if missing:
        raise PerformanceComparisonError(
            "performance_columns_missing",
            "Performance comparison table is missing required fields: "
            + ", ".join(missing),
        )
    if frame.empty:
        raise PerformanceComparisonError(
            "performance_table_empty",
            "Performance comparison table contains no data rows.",
        )

    normalized_rows: list[dict[str, Any]] = []
    material_order: dict[str, int] = {}
    metric_order: dict[str, int] = {}
    numeric_optional_fields = {
        "scatter_min",
        "scatter_max",
        "scale_min",
        "scale_max",
        "material_order",
        "radar_order",
    }
    for index, row in frame.iterrows():
        row_number = int(index) + 2
        material_id = _text(row[columns["material"]])
        metric_id = _text(row[columns["metric"]])
        unit = _text(row[columns["unit"]])
        if not material_id or not metric_id or not unit:
            raise PerformanceComparisonError(
                "performance_required_value_missing",
                f"Row {row_number}: Material, Metric, and Unit must be non-empty.",
            )
        role = _normalized_role(row[columns["role"]], row_number=row_number)
        value = _finite_float(
            row[columns["value"]],
            field="Value",
            row_number=row_number,
        )
        material_order.setdefault(material_id, len(material_order))
        metric_order.setdefault(metric_id, len(metric_order))
        normalized_rows.append(
            {
                "material": material_id,
                "role": role,
                "metric": metric_id,
                "value": value,
                "unit": unit,
                "_source_row": row_number,
                **{
                    field: (
                        row[column]
                        if field in numeric_optional_fields
                        else _text(row[column])
                    )
                    for field, column in columns.items()
                    if field not in _REQUIRED_COLUMNS
                },
            }
        )
    return (
        source_path,
        pd.DataFrame(normalized_rows),
        material_order,
        metric_order,
        len(normalized_rows),
    )
