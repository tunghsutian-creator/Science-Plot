from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.text_normalization import canonicalize_token, normalize_label, normalize_unit

ENCODINGS_TO_TRY = (
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "gb18030",
    "latin-1",
)


@dataclass
class CurveSeries:
    sample: str
    x_label: str
    y_label: str
    x_unit: str
    y_unit: str
    data: pd.DataFrame


@dataclass
class ReplicateGroup:
    group: str
    value_label: str
    value_unit: str
    data: pd.Series


@dataclass
class HeatmapTable:
    x_label: str
    y_label: str
    z_label: str
    x_unit: str
    y_unit: str
    z_unit: str
    data: pd.DataFrame


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _has_content(value: Any) -> bool:
    return _normalize_text(value) != ""


def _row_has_content(row: pd.Series) -> bool:
    return any(_has_content(value) for value in row.tolist())


def _drop_fully_empty_columns(raw: pd.DataFrame) -> pd.DataFrame:
    keep_columns = [index for index in raw.columns if _row_has_content(raw[index])]
    if not keep_columns:
        return raw.iloc[:, 0:0].copy()
    return raw.loc[:, keep_columns].copy()


def _ensure_minimum_rows(raw: pd.DataFrame, minimum_rows: int, *, table_name: str) -> None:
    if raw.shape[0] < minimum_rows:
        raise ValueError(f"{table_name} must include at least {minimum_rows} rows.")


def _ensure_header_row_content(raw: pd.DataFrame, row_index: int, *, row_name: str, table_name: str) -> None:
    if not _row_has_content(raw.iloc[row_index]):
        raise ValueError(f"{table_name} is missing a valid {row_name}.")


def _series_pair_has_any_data(pair: pd.DataFrame) -> bool:
    mapped = pair.map(_has_content) if hasattr(pair, "map") else pair.applymap(_has_content)
    return bool(mapped.to_numpy().any())


def _coerce_numeric_pair(pair: pd.DataFrame, *, column_numbers: tuple[int, int], table_name: str) -> pd.DataFrame:
    numeric_pair = pair.apply(pd.to_numeric, errors="coerce")
    has_x_values = numeric_pair.iloc[:, 0].notna().any()
    has_y_values = numeric_pair.iloc[:, 1].notna().any()
    if has_x_values != has_y_values:
        raise ValueError(
            f"{table_name} columns {column_numbers[0]} and {column_numbers[1]} must contain matching X/Y numeric data."
        )
    if not has_x_values and not has_y_values:
        if _series_pair_has_any_data(pair):
            raise ValueError(
                f"{table_name} columns {column_numbers[0]} and {column_numbers[1]} "
                "contain non-numeric values in the data region."
            )
        return numeric_pair.iloc[0:0].copy()
    numeric_pair.columns = ["x", "y"]
    numeric_pair = numeric_pair.dropna(how="all").dropna(subset=["x", "y"])
    if numeric_pair.empty:
        raise ValueError(
            f"{table_name} columns {column_numbers[0]} and {column_numbers[1]} contain incomplete X/Y rows."
        )
    return numeric_pair.reset_index(drop=True)


def _coerce_axis_series(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        return numeric
    return values.map(_normalize_text)


def _looks_numeric(value: Any) -> bool:
    try:
        float(_normalize_text(value))
    except ValueError:
        return False
    return True


def _read_delimited(path: Path, **kwargs: Any) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ENCODINGS_TO_TRY:
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeError as exc:
            last_error = exc
        except pd.errors.ParserError as exc:
            last_error = exc
    raise ValueError(f"Failed to decode or parse {path}") from last_error


def _decode_text(path: Path) -> str:
    last_error: Exception | None = None
    payload = path.read_bytes()
    for encoding in ENCODINGS_TO_TRY:
        try:
            text = payload.decode(encoding)
        except UnicodeError as exc:
            last_error = exc
            continue
        if text.startswith("\ufffe"):
            continue
        return text
    raise ValueError(f"Failed to decode {path}") from last_error


def _read_ragged_delimited(path: Path, *, delimiter: str) -> pd.DataFrame:
    rows = [line.split(delimiter) for line in _decode_text(path).splitlines()]
    width = max((len(row) for row in rows), default=0)
    padded = [row + [None] * (width - len(row)) for row in rows]
    return pd.DataFrame(padded)


def read_raw_table(path: str | Path, sheet_name: str | int = 0) -> pd.DataFrame:
    """Read CSV/TSV/TXT/XLSX without assigning a header row."""
    table_path = Path(path)
    suffix = table_path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(table_path, header=None, sheet_name=sheet_name)
    if suffix == ".csv":
        try:
            return _read_delimited(table_path, header=None, sep=None, engine="python")
        except (ValueError, csv.Error):
            return _read_ragged_delimited(table_path, delimiter="\t")
    if suffix in {".tsv", ".txt"}:
        return _read_delimited(table_path, header=None, sep=None, engine="python")
    raise ValueError(f"Unsupported file format: {suffix}")


def load_curve_table(
    path: str | Path,
    *,
    start_row: int = 3,
    sheet_name: str | int = 0,
) -> list[CurveSeries]:
    return load_curve_table_from_frame(
        read_raw_table(path, sheet_name=sheet_name),
        start_row=start_row,
    )


def load_curve_table_from_frame(
    raw: pd.DataFrame,
    *,
    start_row: int = 3,
) -> list[CurveSeries]:
    """
    Load a paired X/Y curve table.

    Row 1: axis labels in X/Y pairs
    Row 2: units
    Row 3: sample names repeated twice per series
    Row 4+: numeric data
    """
    raw = _drop_fully_empty_columns(raw)
    _ensure_minimum_rows(raw, start_row + 1, table_name="Curve table")
    _ensure_header_row_content(raw, 0, row_name="axis label row", table_name="Curve table")
    _ensure_header_row_content(raw, 1, row_name="unit row", table_name="Curve table")
    _ensure_header_row_content(raw, 2, row_name="sample row", table_name="Curve table")
    if raw.shape[1] == 0:
        raise ValueError("Curve table does not contain any usable columns.")
    if raw.shape[1] % 2 != 0:
        raise ValueError("Curve table must contain an even number of columns arranged in X/Y pairs.")

    axis_row = raw.iloc[0]
    unit_row = raw.iloc[1]
    sample_row = raw.iloc[2]
    data_rows = raw.iloc[start_row:].reset_index(drop=True)

    series_list: list[CurveSeries] = []
    for col in range(0, raw.shape[1], 2):
        x_label = normalize_label(_normalize_text(axis_row.iloc[col]))
        y_label = normalize_label(_normalize_text(axis_row.iloc[col + 1]))
        x_unit = normalize_unit(_normalize_text(unit_row.iloc[col]))
        y_unit = normalize_unit(_normalize_text(unit_row.iloc[col + 1]))
        sample_x = _normalize_text(sample_row.iloc[col])
        sample_y = _normalize_text(sample_row.iloc[col + 1])

        if sample_x and sample_y and sample_x != sample_y:
            raise ValueError(
                f"Sample names in columns {col + 1} and {col + 2} must match, got {sample_x!r} and {sample_y!r}."
            )
        if not x_label or not y_label:
            raise ValueError(
                f"Curve table columns {col + 1} and {col + 2} are missing axis labels in row 1."
            )

        sample_name = sample_x or sample_y or f"Sample_{col // 2 + 1}"
        pair = data_rows.iloc[:, [col, col + 1]].copy()
        pair = _coerce_numeric_pair(
            pair,
            column_numbers=(col + 1, col + 2),
            table_name="Curve table",
        )
        if pair.empty:
            continue

        series_list.append(
            CurveSeries(
                sample=sample_name,
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


def load_replicate_table(
    path: str | Path,
    *,
    start_row: int = 3,
    sheet_name: str | int = 0,
) -> list[ReplicateGroup]:
    return load_replicate_table_from_frame(
        read_raw_table(path, sheet_name=sheet_name),
        start_row=start_row,
    )


def load_replicate_table_from_frame(
    raw: pd.DataFrame,
    *,
    start_row: int = 3,
) -> list[ReplicateGroup]:
    """
    Load a wide replicate table for boxplots or bar charts.

    Supported formats:

    New format
    Row 1: shared value label in A1
    Row 2: group or sample name per column
    Row 3: value unit per column
    Row 4+: replicate values

    Legacy format
    Row 1: value label per column
    Row 2: value unit per column
    Row 3: group or sample name per column
    Row 4+: replicate values
    """
    raw = _drop_fully_empty_columns(raw)
    _ensure_minimum_rows(raw, start_row + 1, table_name="Replicate table")
    _ensure_header_row_content(raw, 0, row_name="value label row", table_name="Replicate table")
    _ensure_header_row_content(raw, 1, row_name="group row", table_name="Replicate table")
    _ensure_header_row_content(raw, 2, row_name="unit row", table_name="Replicate table")
    if raw.shape[1] == 0:
        raise ValueError("Replicate table does not contain any usable columns.")

    value_row = raw.iloc[0]
    first_row_values = [_normalize_text(value) for value in value_row.tolist()]
    non_empty_first_row = [value for value in first_row_values if value]
    use_shared_label_layout = len(non_empty_first_row) <= 1

    if use_shared_label_layout:
        shared_label = normalize_label(first_row_values[0])
        if not shared_label:
            raise ValueError("Replicate table is missing the shared y-axis label in cell A1.")
        group_row = raw.iloc[1]
        unit_row = raw.iloc[2]
    else:
        shared_label = ""
        unit_row = raw.iloc[1]
        group_row = raw.iloc[2]

    data_rows = raw.iloc[start_row:].reset_index(drop=True)

    groups: list[ReplicateGroup] = []
    for col in range(raw.shape[1]):
        group = _normalize_text(group_row.iloc[col]) or f"Group_{col + 1}"
        value_label = shared_label or normalize_label(_normalize_text(value_row.iloc[col])) or "Value"
        value_unit = normalize_unit(_normalize_text(unit_row.iloc[col]))

        raw_values = data_rows.iloc[:, col]
        values = pd.to_numeric(raw_values, errors="coerce").dropna().reset_index(drop=True)
        if values.empty and any(_has_content(value) for value in raw_values.tolist()):
            raise ValueError(f"Replicate table column {col + 1} contains no numeric replicate values.")
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


def load_heatmap_table(
    path: str | Path,
    *,
    start_row: int = 3,
    sheet_name: str | int = 0,
) -> HeatmapTable:
    return load_heatmap_table_from_frame(
        read_raw_table(path, sheet_name=sheet_name),
        start_row=start_row,
    )


def load_heatmap_table_from_frame(
    raw: pd.DataFrame,
    *,
    start_row: int = 3,
) -> HeatmapTable:
    """
    Load an XYZ long-table heatmap input.

    Row 1: semantic roles X, Y, Z
    Row 2: display labels
    Row 3: units
    Row 4+: data rows

    Matrix form is also accepted for DataGraph-style scalar fields:
    Row 1: empty/corner label followed by X coordinates
    Column 1: Y coordinates
    Cells: Z values
    """
    raw = _drop_fully_empty_columns(raw)
    if raw.shape[1] != 3:
        return _load_heatmap_matrix(raw)

    _ensure_minimum_rows(raw, start_row + 1, table_name="Heatmap table")
    _ensure_header_row_content(raw, 0, row_name="role row", table_name="Heatmap table")
    _ensure_header_row_content(raw, 1, row_name="label row", table_name="Heatmap table")

    roles = [canonicalize_token(_normalize_text(value)) for value in raw.iloc[0].tolist()]
    role_index: dict[str, int] = {}
    for index, role in enumerate(roles):
        if role in {"x", "y", "z"}:
            role_index[role] = index
    if set(role_index) != {"x", "y", "z"}:
        raise ValueError("Heatmap table role row must contain exactly X, Y and Z.")

    label_row = raw.iloc[1]
    unit_row = raw.iloc[2]
    data_rows = raw.iloc[start_row:].reset_index(drop=True)
    data_columns = ["x", "y", "z"]
    ordered = data_rows.iloc[:, [role_index["x"], role_index["y"], role_index["z"]]].copy()
    ordered.columns = data_columns

    ordered["z"] = pd.to_numeric(ordered["z"], errors="coerce")
    ordered = ordered.dropna(subset=["z"])
    if ordered.empty:
        raise ValueError("Heatmap table does not contain any numeric Z values.")

    ordered["x"] = _coerce_axis_series(ordered["x"])
    ordered["y"] = _coerce_axis_series(ordered["y"])
    ordered = ordered[ordered["x"].map(_has_content) & ordered["y"].map(_has_content)].reset_index(drop=True)
    if ordered.empty:
        raise ValueError("Heatmap table does not contain any valid X/Y coordinates.")

    return HeatmapTable(
        x_label=normalize_label(_normalize_text(label_row.iloc[role_index["x"]])) or "X",
        y_label=normalize_label(_normalize_text(label_row.iloc[role_index["y"]])) or "Y",
        z_label=normalize_label(_normalize_text(label_row.iloc[role_index["z"]])) or "Z",
        x_unit=normalize_unit(_normalize_text(unit_row.iloc[role_index["x"]])),
        y_unit=normalize_unit(_normalize_text(unit_row.iloc[role_index["y"]])),
        z_unit=normalize_unit(_normalize_text(unit_row.iloc[role_index["z"]])),
        data=ordered,
    )


def _load_heatmap_matrix(raw: pd.DataFrame) -> HeatmapTable:
    if raw.shape[0] < 2 or raw.shape[1] < 2:
        raise ValueError("Heatmap matrix table must include at least two rows and two columns.")
    x_cells = raw.iloc[0, 1:].tolist()
    y_cells = raw.iloc[1:, 0].tolist()
    if not all(_looks_numeric(value) for value in x_cells) or not all(_looks_numeric(value) for value in y_cells):
        raise ValueError(
            "Heatmap matrix table must use numeric X coordinates in row 1 and numeric Y coordinates in column 1."
        )
    value_block = raw.iloc[1:, 1:].apply(pd.to_numeric, errors="coerce")
    if value_block.dropna(how="all").empty:
        raise ValueError("Heatmap matrix table does not contain numeric Z values.")
    x_values = [float(_normalize_text(value)) for value in x_cells]
    y_values = [float(_normalize_text(value)) for value in y_cells]
    rows: list[dict[str, float]] = []
    for y_index, y_value in enumerate(y_values):
        for x_index, x_value in enumerate(x_values):
            z_value = value_block.iat[y_index, x_index]
            if pd.isna(z_value):
                continue
            rows.append({"x": x_value, "y": y_value, "z": float(z_value)})
    if not rows:
        raise ValueError("Heatmap matrix table does not contain finite X/Y/Z cells.")
    corner = _normalize_text(raw.iat[0, 0])
    return HeatmapTable(
        x_label="X",
        y_label=normalize_label(corner) or "Y",
        z_label="Z",
        x_unit="",
        y_unit="",
        z_unit="",
        data=pd.DataFrame(rows),
    )
