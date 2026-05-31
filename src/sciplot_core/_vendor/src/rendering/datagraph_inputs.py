from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from src.text_normalization import canonicalize_token

TABLE_FIGURE_MAX_ROWS = 12
TABLE_FIGURE_MAX_COLS = 8
THETA_UNIT_TOKENS = {"rad", "radian", "radians", "degree", "degrees", "deg"}


def series_looks_polar(series_list: Sequence[Any]) -> bool:
    if not series_list:
        return False
    first = series_list[0]
    x_label = canonicalize_token(getattr(first, "x_label", ""))
    y_label = canonicalize_token(getattr(first, "y_label", ""))
    x_unit = canonicalize_token(getattr(first, "x_unit", ""))
    return (
        x_label in {"theta", "angle", "azimuth"}
        and y_label in {"radius", "radial distance", "r"}
        and (not x_unit or x_unit in THETA_UNIT_TOKENS)
    )


def theta_values_for_plot(values: pd.Series, *, unit: str) -> np.ndarray:
    numeric_values = values.to_numpy(dtype=float)
    if canonicalize_token(unit) in {"degree", "degrees", "deg"}:
        return np.deg2rad(numeric_values)
    return numeric_values


def table_figure_size_error(raw: pd.DataFrame) -> str | None:
    if raw.shape[0] <= TABLE_FIGURE_MAX_ROWS and raw.shape[1] <= TABLE_FIGURE_MAX_COLS:
        return None
    return (
        "Table figure is limited to a small table "
        f"({TABLE_FIGURE_MAX_ROWS} rows x {TABLE_FIGURE_MAX_COLS} columns)."
    )


__all__ = [
    "TABLE_FIGURE_MAX_COLS",
    "TABLE_FIGURE_MAX_ROWS",
    "series_looks_polar",
    "table_figure_size_error",
    "theta_values_for_plot",
]
