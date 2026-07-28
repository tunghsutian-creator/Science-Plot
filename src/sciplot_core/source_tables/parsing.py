"""Provide validation and coercion primitives for structured source tables."""

from __future__ import annotations

from typing import Any

import pandas as pd


def normalize_cell(value: Any) -> str:
    if value is None or isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def has_content(value: Any) -> bool:
    return normalize_cell(value) != ""


def row_has_content(row: pd.Series) -> bool:
    return any(has_content(value) for value in row.tolist())


def drop_fully_empty_columns(raw: pd.DataFrame) -> pd.DataFrame:
    keep_columns = [index for index in raw.columns if row_has_content(raw[index])]
    if not keep_columns:
        return raw.iloc[:, 0:0].copy()
    return raw.loc[:, keep_columns].copy()


def ensure_minimum_rows(
    raw: pd.DataFrame,
    minimum_rows: int,
    *,
    table_name: str,
) -> None:
    if raw.shape[0] < minimum_rows:
        raise ValueError(f"{table_name} must include at least {minimum_rows} rows.")


def ensure_header_row_content(
    raw: pd.DataFrame,
    row_index: int,
    *,
    row_name: str,
    table_name: str,
) -> None:
    if not row_has_content(raw.iloc[row_index]):
        raise ValueError(f"{table_name} is missing a valid {row_name}.")


def coerce_numeric_pair(
    pair: pd.DataFrame,
    *,
    column_numbers: tuple[int, int],
    table_name: str,
) -> pd.DataFrame:
    numeric_pair = pair.apply(pd.to_numeric, errors="coerce")
    has_x_values = numeric_pair.iloc[:, 0].notna().any()
    has_y_values = numeric_pair.iloc[:, 1].notna().any()
    if has_x_values != has_y_values:
        raise ValueError(
            f"{table_name} columns {column_numbers[0]} and {column_numbers[1]} "
            "must contain matching X/Y numeric data."
        )
    if not has_x_values and not has_y_values:
        mapped = (
            pair.map(has_content)
            if hasattr(pair, "map")
            else pair.applymap(has_content)
        )
        if bool(mapped.to_numpy().any()):
            raise ValueError(
                f"{table_name} columns {column_numbers[0]} and {column_numbers[1]} "
                "contain non-numeric values in the data region."
            )
        return numeric_pair.iloc[0:0].copy()
    numeric_pair.columns = ["x", "y"]
    numeric_pair = numeric_pair.dropna(how="all").dropna(subset=["x", "y"])
    if numeric_pair.empty:
        raise ValueError(
            f"{table_name} columns {column_numbers[0]} and {column_numbers[1]} "
            "contain incomplete X/Y rows."
        )
    return numeric_pair.reset_index(drop=True)


def coerce_axis_series(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        return numeric
    return values.map(normalize_cell)


def looks_numeric(value: Any) -> bool:
    try:
        float(normalize_cell(value))
    except ValueError:
        return False
    return True


__all__ = [
    "coerce_axis_series",
    "coerce_numeric_pair",
    "drop_fully_empty_columns",
    "ensure_header_row_content",
    "ensure_minimum_rows",
    "has_content",
    "looks_numeric",
    "normalize_cell",
    "row_has_content",
]
