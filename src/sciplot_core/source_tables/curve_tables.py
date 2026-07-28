"""Parse paired X/Y curve tables into named curve series."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sciplot_core.source_tables.models import CurveSeries
from sciplot_core.source_tables.parsing import (
    coerce_numeric_pair,
    drop_fully_empty_columns,
    ensure_header_row_content,
    ensure_minimum_rows,
    normalize_cell,
)
from sciplot_core.source_tables.raw_readers import read_raw_table
from sciplot_core.source_tables.text_normalization import (
    normalize_label,
    normalize_unit,
)


def load_curve_table(
    path: str | Path,
    *,
    start_row: int = 3,
    sheet_name: str | int = 0,
) -> list[CurveSeries]:
    """Read and parse a paired X/Y curve table."""

    return load_curve_table_from_frame(
        read_raw_table(path, sheet_name=sheet_name),
        start_row=start_row,
    )


def load_curve_table_from_frame(
    raw: pd.DataFrame,
    *,
    start_row: int = 3,
) -> list[CurveSeries]:
    """Parse labels, units, sample names, and numeric X/Y pairs."""

    raw = drop_fully_empty_columns(raw)
    ensure_minimum_rows(raw, start_row + 1, table_name="Curve table")
    ensure_header_row_content(
        raw,
        0,
        row_name="axis label row",
        table_name="Curve table",
    )
    ensure_header_row_content(
        raw,
        1,
        row_name="unit row",
        table_name="Curve table",
    )
    ensure_header_row_content(
        raw,
        2,
        row_name="sample row",
        table_name="Curve table",
    )
    if raw.shape[1] == 0:
        raise ValueError("Curve table does not contain any usable columns.")
    if raw.shape[1] % 2 != 0:
        raise ValueError(
            "Curve table must contain an even number of columns arranged in X/Y pairs."
        )

    axis_row = raw.iloc[0]
    unit_row = raw.iloc[1]
    sample_row = raw.iloc[2]
    data_rows = raw.iloc[start_row:].reset_index(drop=True)
    series_list: list[CurveSeries] = []
    for column in range(0, raw.shape[1], 2):
        x_label = normalize_label(axis_row.iloc[column])
        y_label = normalize_label(axis_row.iloc[column + 1])
        x_unit = normalize_unit(unit_row.iloc[column])
        y_unit = normalize_unit(unit_row.iloc[column + 1])
        sample_x = normalize_cell(sample_row.iloc[column])
        sample_y = normalize_cell(sample_row.iloc[column + 1])
        if sample_x and sample_y and sample_x != sample_y:
            raise ValueError(
                f"Sample names in columns {column + 1} and {column + 2} must "
                f"match, got {sample_x!r} and {sample_y!r}."
            )
        if not x_label or not y_label:
            raise ValueError(
                f"Curve table columns {column + 1} and {column + 2} are missing "
                "axis labels in row 1."
            )
        pair = coerce_numeric_pair(
            data_rows.iloc[:, [column, column + 1]].copy(),
            column_numbers=(column + 1, column + 2),
            table_name="Curve table",
        )
        if pair.empty:
            continue
        series_list.append(
            CurveSeries(
                sample=sample_x or sample_y or f"Sample_{column // 2 + 1}",
                x_label=x_label or "X",
                y_label=y_label or "Y",
                x_unit=x_unit,
                y_unit=y_unit,
                data=pair.reset_index(drop=True),
            )
        )
    if not series_list:
        raise ValueError("No valid X/Y series found in the curve table.")
    return series_list


__all__ = ["load_curve_table", "load_curve_table_from_frame"]
