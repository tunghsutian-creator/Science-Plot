"""Read-only original Metric IDs, unit facts and confirmation templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from importlib import import_module

import pandas as pd

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.performance_comparison.models import PerformanceComparisonError
from sciplot_core.performance_comparison.selection import (
    performance_selection_schema,
    selection_template,
)
from sciplot_core.performance_comparison.source_tables import (
    _canonical_header_map,
    _read_source_frame,
    _resolve_source,
)
from sciplot_core.performance_comparison.source_values import _REQUIRED_COLUMNS, _text


def _numeric_missing_tokens() -> frozenset[str]:
    # Reuse the installed parser's grammar rather than copying token spellings.
    # Its native module is absent from pandas-stubs; narrow the actual constant
    # at this dependency boundary instead of suppressing a missing stub.
    value: object = import_module("pandas._libs.parsers").STR_NA_VALUES
    if not isinstance(value, set) or not all(isinstance(item, str) for item in value):
        raise TypeError("Pandas numeric missing tokens must be a set of strings.")
    return frozenset(item for item in value if isinstance(item, str))


def read_metadata_table(
    source: str | Path,
) -> tuple[Path, pd.DataFrame, dict[str, str], str]:
    path = _resolve_source(Path(source), allow_missing_unit=True)
    digest = file_sha256(path)
    frame = _read_source_frame(path, exact_numeric=True, allow_missing_unit=True)
    # Preserve original text identifiers, including strings that a general
    # table parser treats as NA. Only numeric column roles use that grammar.
    frame = frame.loc[
        [
            any(_text(cell) for cell in row)
            for row in frame.itertuples(index=False, name=None)
        ]
    ]
    original_columns = _canonical_header_map(frame.columns)
    if any(not isinstance(column, str) for column in original_columns.values()):
        raise PerformanceComparisonError(
            "performance_header_invalid", "Performance table headers must be text."
        )
    columns = {
        key: column
        for key, column in original_columns.items()
        if isinstance(column, str)
    }
    missing = sorted((_REQUIRED_COLUMNS - {"unit"}) - set(columns))
    if missing:
        raise PerformanceComparisonError(
            "performance_columns_missing",
            "Missing performance fields: " + ", ".join(missing),
        )
    numeric_fields = {
        "value",
        "scatter_min",
        "scatter_max",
        "scale_min",
        "scale_max",
        "material_order",
        "radar_order",
    }
    for field in numeric_fields & set(columns):
        column = columns[field]
        frame[column] = frame[column].mask(
            frame[column].isin(_numeric_missing_tokens())
        )
    if frame.empty:
        raise PerformanceComparisonError(
            "performance_table_empty", "Performance table contains no data rows."
        )
    if file_sha256(path) != digest:
        raise PerformanceComparisonError(
            "performance_selection_source_changed",
            "Original table changed while reading metadata.",
        )
    return path, frame, columns, digest


def metric_unit_facts(
    frame: pd.DataFrame, columns: dict[str, str]
) -> list[dict[str, Any]]:
    groups: dict[str, list[int]] = {}
    for index, value in enumerate(frame[columns["metric"]].tolist()):
        metric = _text(value)
        if metric:
            groups.setdefault(metric, []).append(index)
    facts = []
    for metric, indexes in groups.items():
        units = [
            _text(frame[columns["unit"]].iloc[index]) if "unit" in columns else ""
            for index in indexes
        ]
        original_units = list(dict.fromkeys(unit for unit in units if unit))
        facts.append(
            {
                "metric_id": metric,
                "source_row_count": len(indexes),
                "original_units": original_units,
                "missing_unit_count": units.count(""),
                "unit_conflict": len(original_units) > 1,
                "missing_value_count": sum(
                    1
                    for index in indexes
                    if pd.isna(frame[columns["value"]].iloc[index])
                ),
            }
        )
    return facts


def inspect_performance_metadata(source: str | Path) -> dict[str, Any]:
    path, frame, columns, digest = read_metadata_table(source)
    facts = metric_unit_facts(frame, columns)
    return {
        "kind": "sciplot_performance_source_metadata",
        "version": 1,
        "read_only": True,
        "source": str(path),
        "source_sha256": digest,
        "source_row_count": len(frame),
        "metrics": facts,
        "selection_template": selection_template(digest, facts),
        "selection_schema": performance_selection_schema(),
        "text_field_policy": "Original identifiers and Unit text are literal. Only an empty or whitespace Unit is missing.",
        "numeric_missing_tokens": sorted(_numeric_missing_tokens()),
        "next_step": "Select two exact original Metric IDs. Ask the original user for each selected missing unit and record their exact statement; remove unselected unit declarations. Run plan with the completed performance selection.",
    }
