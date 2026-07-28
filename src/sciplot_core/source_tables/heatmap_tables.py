"""Parse long-form and matrix-form heatmap source tables."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sciplot_core.source_tables.models import HeatmapTable
from sciplot_core.source_tables.parsing import (
    coerce_axis_series,
    drop_fully_empty_columns,
    ensure_header_row_content,
    ensure_minimum_rows,
    has_content,
    looks_numeric,
    normalize_cell,
)
from sciplot_core.source_tables.raw_readers import read_raw_table
from sciplot_core.source_tables.text_normalization import (
    canonicalize_token,
    normalize_label,
    normalize_unit,
)


def load_heatmap_table(
    path: str | Path,
    *,
    start_row: int = 3,
    sheet_name: str | int = 0,
) -> HeatmapTable:
    """Read and parse a long-form or matrix-form heatmap table."""

    return load_heatmap_table_from_frame(
        read_raw_table(path, sheet_name=sheet_name),
        start_row=start_row,
    )


def load_heatmap_table_from_frame(
    raw: pd.DataFrame,
    *,
    start_row: int = 3,
) -> HeatmapTable:
    """Parse semantic X/Y/Z rows, falling back to a numeric matrix layout."""

    raw = drop_fully_empty_columns(raw)
    if raw.shape[1] != 3:
        return _load_heatmap_matrix(raw)

    ensure_minimum_rows(raw, start_row + 1, table_name="Heatmap table")
    ensure_header_row_content(
        raw,
        0,
        row_name="role row",
        table_name="Heatmap table",
    )
    ensure_header_row_content(
        raw,
        1,
        row_name="label row",
        table_name="Heatmap table",
    )
    roles = [canonicalize_token(value) for value in raw.iloc[0].tolist()]
    role_index = {
        role: index for index, role in enumerate(roles) if role in {"x", "y", "z"}
    }
    if set(role_index) != {"x", "y", "z"}:
        raise ValueError("Heatmap table role row must contain exactly X, Y and Z.")

    label_row = raw.iloc[1]
    unit_row = raw.iloc[2]
    ordered = raw.iloc[
        start_row:,
        [
            role_index["x"],
            role_index["y"],
            role_index["z"],
        ],
    ].copy()
    ordered.columns = ["x", "y", "z"]
    ordered["z"] = pd.to_numeric(ordered["z"], errors="coerce")
    ordered = ordered.dropna(subset=["z"])
    if ordered.empty:
        raise ValueError("Heatmap table does not contain any numeric Z values.")
    ordered["x"] = coerce_axis_series(ordered["x"])
    ordered["y"] = coerce_axis_series(ordered["y"])
    ordered = ordered[
        ordered["x"].map(has_content) & ordered["y"].map(has_content)
    ].reset_index(drop=True)
    if ordered.empty:
        raise ValueError("Heatmap table does not contain any valid X/Y coordinates.")

    return HeatmapTable(
        x_label=normalize_label(label_row.iloc[role_index["x"]]) or "X",
        y_label=normalize_label(label_row.iloc[role_index["y"]]) or "Y",
        z_label=normalize_label(label_row.iloc[role_index["z"]]) or "Z",
        x_unit=normalize_unit(unit_row.iloc[role_index["x"]]),
        y_unit=normalize_unit(unit_row.iloc[role_index["y"]]),
        z_unit=normalize_unit(unit_row.iloc[role_index["z"]]),
        data=ordered,
    )


def _load_heatmap_matrix(raw: pd.DataFrame) -> HeatmapTable:
    if raw.shape[0] < 2 or raw.shape[1] < 2:
        raise ValueError(
            "Heatmap matrix table must include at least two rows and two columns."
        )
    x_cells = raw.iloc[0, 1:].tolist()
    y_cells = raw.iloc[1:, 0].tolist()
    if not all(looks_numeric(value) for value in x_cells) or not all(
        looks_numeric(value) for value in y_cells
    ):
        raise ValueError(
            "Heatmap matrix table must use numeric X coordinates in row 1 and "
            "numeric Y coordinates in column 1."
        )
    value_block = raw.iloc[1:, 1:].apply(pd.to_numeric, errors="coerce")
    if value_block.dropna(how="all").empty:
        raise ValueError("Heatmap matrix table does not contain numeric Z values.")
    x_values = [float(normalize_cell(value)) for value in x_cells]
    y_values = [float(normalize_cell(value)) for value in y_cells]
    rows: list[dict[str, float]] = []
    for y_index, y_value in enumerate(y_values):
        for x_index, x_value in enumerate(x_values):
            z_value = value_block.iat[y_index, x_index]
            if not pd.isna(z_value):
                rows.append({"x": x_value, "y": y_value, "z": float(z_value)})
    if not rows:
        raise ValueError("Heatmap matrix table does not contain finite X/Y/Z cells.")
    return HeatmapTable(
        x_label="X",
        y_label=normalize_label(raw.iat[0, 0]) or "Y",
        z_label="Z",
        x_unit="",
        y_unit="",
        z_unit="",
        data=pd.DataFrame(rows),
    )


__all__ = ["load_heatmap_table", "load_heatmap_table_from_frame"]
