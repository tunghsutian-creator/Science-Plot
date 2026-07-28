"""Read raw tables and normalize missing, decimal, numeric, and condition values."""

from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_files import decode_text
from sciplot_core.mapping_contract import (
    DataColumnMapping,
    DataMappingProposal,
    DataSourceReference,
)

from sciplot_core.data_mapping.contracts import (
    _MISSING_STRINGS,
    _NUMERIC_COLUMN_ROLES,
    _DECIMAL_COMMA_NUMBER,
)


@dataclass
class _RawTable:
    source: DataSourceReference
    path: Path
    headers: tuple[str, ...]
    frame: pd.DataFrame


def _detect_delimiter(text: str, reference: DataSourceReference) -> str:
    if reference.delimiter != "auto":
        return reference.delimiter
    lines = [line for line in text.splitlines()[:40] if line.strip()]
    sample = "\n".join(lines)
    counts = {
        "\t": sample.count("\t"),
        ";": sample.count(";"),
        ",": sample.count(","),
        "|": sample.count("|"),
    }
    delimiter, count = max(counts.items(), key=lambda item: (item[1], item[0]))
    if count <= 0:
        raise ValueError(
            f"Could not determine a delimiter for {reference.relative_path}."
        )
    if reference.decimal == "," and counts[";"] > 0:
        return ";"
    return delimiter


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _normalize_missing(value: object) -> object:
    text = _cell_text(value)
    if text.casefold() in _MISSING_STRINGS:
        return pd.NA
    return value


def _normalize_decimal_comma(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if _DECIMAL_COMMA_NUMBER.fullmatch(text) is None:
        return value
    return text.replace(",", ".")


def _read_raw_table(
    reference: DataSourceReference,
    path: Path,
) -> _RawTable:
    suffix = path.suffix.casefold()
    if suffix in {".xlsx", ".xls"}:
        sheet = reference.sheet if reference.sheet is not None else 0
        raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    else:
        if reference.sheet is not None:
            raise ValueError(
                f"Text source {reference.relative_path} cannot select an Excel sheet."
            )
        text = decode_text(path)
        delimiter = _detect_delimiter(text, reference)
        raw = pd.read_csv(
            StringIO(text),
            sep=delimiter,
            header=None,
            dtype=object,
            keep_default_na=False,
            na_filter=False,
            engine="python",
        )
    if raw.empty:
        raise ValueError(f"Data mapping source is empty: {reference.relative_path}")
    raw = raw.dropna(axis=1, how="all")
    header_row = reference.header_row
    if header_row is None:
        headers = tuple(f"column_{index}" for index in range(raw.shape[1]))
        frame = raw.reset_index(drop=True)
    else:
        if header_row >= raw.shape[0]:
            raise ValueError(
                f"header_row is outside {reference.relative_path}: {header_row}"
            )
        headers = tuple(
            _cell_text(value) or f"column_{index}"
            for index, value in enumerate(raw.iloc[header_row].tolist())
        )
        frame = raw.iloc[header_row + 1 :].reset_index(drop=True)
    frame = frame.map(_normalize_missing)
    return _RawTable(
        source=reference,
        path=path,
        headers=headers,
        frame=frame,
    )


def _column_mappings_for_source(
    proposal: DataMappingProposal,
    source_id: str,
) -> tuple[DataColumnMapping, ...]:
    return tuple(
        mapping for mapping in proposal.columns if mapping.source_id == source_id
    )


def _map_columns(
    raw: _RawTable,
    mappings: tuple[DataColumnMapping, ...],
) -> pd.DataFrame:
    selected: dict[str, pd.Series] = {}
    for mapping in mappings:
        if mapping.source_column_index >= raw.frame.shape[1]:
            raise ValueError(
                f"{raw.source.source_id} column index "
                f"{mapping.source_column_index} is outside the source table."
            )
        actual_header = raw.headers[mapping.source_column_index]
        if (
            mapping.expected_header is not None
            and actual_header != mapping.expected_header
        ):
            raise ValueError(
                f"{raw.source.source_id} column {mapping.source_column_index} "
                f"header changed: expected {mapping.expected_header!r}, "
                f"found {actual_header!r}."
            )
        series = raw.frame.iloc[:, mapping.source_column_index].copy()
        if raw.source.decimal == "," and mapping.role in _NUMERIC_COLUMN_ROLES:
            series = series.map(_normalize_decimal_comma)
        if mapping.required and series.notna().sum() == 0:
            raise ValueError(
                f"Required mapped column {mapping.output_column!r} contains no values."
            )
        selected[mapping.output_column] = series
    return pd.DataFrame(selected)


def _require_columns(
    frame: pd.DataFrame,
    columns: list[str] | tuple[str, ...],
    *,
    operation: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{operation} references unknown columns: {', '.join(missing)}"
        )


def _numeric_series(
    frame: pd.DataFrame,
    column: str,
    *,
    operation: str,
) -> pd.Series:
    _require_columns(frame, [column], operation=operation)
    source = frame[column]
    numeric = pd.to_numeric(source, errors="coerce")
    invalid = source.notna() & numeric.isna()
    if invalid.any():
        rows = [int(index) for index in source.index[invalid].tolist()[:8]]
        raise ValueError(
            f"{operation} found non-numeric values in {column!r} at rows {rows}."
        )
    return numeric.astype(float)


def _deterministic_sort_key(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    invalid = series.notna() & numeric.isna()
    return series if invalid.any() else numeric


def _condition_mask(frame: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    column = str(condition["column"])
    _require_columns(frame, [column], operation="exclude where")
    operator = str(condition["operator"])
    series = frame[column]
    if operator == "is_missing":
        return series.isna()
    if operator == "not_missing":
        return series.notna()
    value = condition["value"]
    if operator == "eq":
        return series == value
    if operator == "ne":
        return series != value
    if operator == "in":
        return series.isin(value)
    if operator == "not_in":
        return ~series.isin(value)
    numeric = _numeric_series(frame, column, operation=f"exclude {operator}")
    scalar = float(value)
    if operator == "lt":
        return numeric < scalar
    if operator == "lte":
        return numeric <= scalar
    if operator == "gt":
        return numeric > scalar
    if operator == "gte":
        return numeric >= scalar
    raise ValueError(f"Unsupported exclusion operator: {operator}")
