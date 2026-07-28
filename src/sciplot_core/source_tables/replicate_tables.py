"""Parse wide replicate tables into named replicate groups."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sciplot_core.source_tables.models import ReplicateGroup
from sciplot_core.source_tables.parsing import (
    drop_fully_empty_columns,
    ensure_header_row_content,
    ensure_minimum_rows,
    has_content,
    normalize_cell,
)
from sciplot_core.source_tables.raw_readers import read_raw_table
from sciplot_core.source_tables.text_normalization import (
    normalize_label,
    normalize_unit,
)


def load_replicate_table(
    path: str | Path,
    *,
    start_row: int = 3,
    sheet_name: str | int = 0,
) -> list[ReplicateGroup]:
    """Read and parse a wide replicate table."""

    return load_replicate_table_from_frame(
        read_raw_table(path, sheet_name=sheet_name),
        start_row=start_row,
    )


def load_replicate_table_from_frame(
    raw: pd.DataFrame,
    *,
    start_row: int = 3,
) -> list[ReplicateGroup]:
    """Parse the shared-label and legacy replicate table layouts."""

    raw = drop_fully_empty_columns(raw)
    ensure_minimum_rows(raw, start_row + 1, table_name="Replicate table")
    ensure_header_row_content(
        raw,
        0,
        row_name="value label row",
        table_name="Replicate table",
    )
    ensure_header_row_content(
        raw,
        1,
        row_name="group row",
        table_name="Replicate table",
    )
    ensure_header_row_content(
        raw,
        2,
        row_name="unit row",
        table_name="Replicate table",
    )
    if raw.shape[1] == 0:
        raise ValueError("Replicate table does not contain any usable columns.")

    value_row = raw.iloc[0]
    first_row_values = [normalize_cell(value) for value in value_row.tolist()]
    use_shared_label_layout = len([value for value in first_row_values if value]) <= 1
    if use_shared_label_layout:
        shared_label = normalize_label(first_row_values[0])
        if not shared_label:
            raise ValueError(
                "Replicate table is missing the shared y-axis label in cell A1."
            )
        group_row = raw.iloc[1]
        unit_row = raw.iloc[2]
    else:
        shared_label = ""
        unit_row = raw.iloc[1]
        group_row = raw.iloc[2]

    data_rows = raw.iloc[start_row:].reset_index(drop=True)
    groups: list[ReplicateGroup] = []
    for column in range(raw.shape[1]):
        group = normalize_cell(group_row.iloc[column]) or f"Group_{column + 1}"
        value_label = shared_label or normalize_label(value_row.iloc[column]) or "Value"
        value_unit = normalize_unit(unit_row.iloc[column])
        raw_values = data_rows.iloc[:, column]
        values = (
            pd.to_numeric(raw_values, errors="coerce").dropna().reset_index(drop=True)
        )
        if values.empty and any(has_content(value) for value in raw_values.tolist()):
            raise ValueError(
                f"Replicate table column {column + 1} contains no numeric "
                "replicate values."
            )
        if values.empty:
            continue
        groups.append(
            ReplicateGroup(
                group=group,
                value_label=value_label,
                value_unit=value_unit,
                data=values,
            )
        )
    if not groups:
        raise ValueError("No valid replicate columns found in the table.")
    return groups


__all__ = ["load_replicate_table", "load_replicate_table_from_frame"]
