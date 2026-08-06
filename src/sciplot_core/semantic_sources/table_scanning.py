"""Read candidate tables and discover paired curve columns and metadata."""

from __future__ import annotations

import re
from pathlib import Path
import pandas as pd
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)
from sciplot_core.ingest import normalized_source
from sciplot_core.materials_rules.unit_formatting import (
    format_unit_label,
)

from sciplot_core.source_tables import (
    read_raw_table,
)

from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)


def _sample_from_interval_metadata(raw: pd.DataFrame, fallback: str) -> str:
    for row_index in range(min(12, raw.shape[0])):
        row = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        if row and _token(row[0]) == "test" and len(row) > 1 and row[1]:
            return row[1]
    return fallback


def _rheology_test_sections(
    raw: pd.DataFrame,
    *,
    fallback: str,
) -> list[tuple[str, pd.DataFrame]]:
    """Split a concatenated instrument export into authoritative test blocks.

    Anton Paar text exports can contain several complete ``Test:`` sections in
    one file.  A filename is only a container label in that format; the test
    metadata inside each block owns sample identity.
    """

    starts = [
        row_index
        for row_index in range(raw.shape[0])
        if raw.shape[1] and _token(raw.iat[row_index, 0]) == "test"
    ]
    if not starts:
        return [(fallback, raw.reset_index(drop=True))]
    sections: list[tuple[str, pd.DataFrame]] = []
    for index, start in enumerate(starts):
        stop = starts[index + 1] if index + 1 < len(starts) else raw.shape[0]
        block = raw.iloc[start:stop].reset_index(drop=True).dropna(how="all")
        sample = _sample_from_interval_metadata(block, fallback)
        sections.append((sample, block))
    return sections


def _find_column(headers: list[str], candidates: tuple[str, ...]) -> int:
    for index, header in enumerate(headers):
        token = _token(header)
        if any(candidate in token for candidate in candidates):
            return index
    raise ValueError(f"Could not find any expected column: {', '.join(candidates)}")


def _unit_for(units: list[str], index: int, fallback: str) -> str:
    if index < len(units):
        unit = _clean_text(units[index]).strip("[]() ")
        if unit:
            return format_unit_label(unit)
    return format_unit_label(fallback)


def _float(value: object, *, decimal_comma: bool = False) -> float | None:
    text = (
        _clean_text(value).replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    )
    if not text:
        return None
    if decimal_comma:
        if "," in text and "." in text:
            text = text.replace(".", "")
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _read_raw_table_normalized(path: Path) -> pd.DataFrame:
    with normalized_source(path) as normalized:
        return read_raw_table(normalized)


def _table_uses_decimal_comma(raw: pd.DataFrame, *, start_row: int = 0) -> bool:
    comma_decimal = 0
    point_decimal = 0
    stop = min(raw.shape[0], start_row + 240)
    for row_index in range(start_row, stop):
        for value in raw.iloc[row_index].tolist():
            text = _clean_text(value)
            if re.search(r"[+-]?\d+,\d+(?:[Ee][+-]?\d+)?", text):
                comma_decimal += 1
            if re.search(r"[+-]?\d+\.\d+(?:[Ee][+-]?\d+)?", text):
                point_decimal += 1
    return comma_decimal >= 3 and comma_decimal > point_decimal * 2


def _read_candidate_tables(source: Path) -> list[tuple[str, pd.DataFrame]]:
    if source.is_dir():
        paths = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file()
            and path.suffix.lower()
            in {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".xlsm"}
        ]
    else:
        paths = [source]
    tables: list[tuple[str, pd.DataFrame]] = []
    for path in paths:
        if path.suffix.lower() in {".xlsx", ".xls", ".xlsm"}:
            workbook = pd.ExcelFile(path)
            tables.extend(
                (
                    f"{path.stem}:{sheet_name}",
                    pd.read_excel(path, sheet_name=sheet_name, header=None).dropna(
                        axis=1, how="all"
                    ),
                )
                for sheet_name in workbook.sheet_names
            )
        else:
            tables.append(
                (path.stem, _read_raw_table_normalized(path).dropna(axis=1, how="all"))
            )
    return [
        (name, table.dropna(how="all"))
        for name, table in tables
        if not table.dropna(how="all").empty
    ]


def _axis_match(value: object, aliases: tuple[str, ...]) -> bool:
    text = _clean_text(value).casefold()
    token = _token(value)
    for alias in aliases:
        alias_text = alias.casefold()
        alias_token = _token(alias)
        if alias_text and (text == alias_text or alias_text in text):
            return True
        if not alias_token:
            continue
        if token == alias_token or alias_token in token:
            return True
    return False


def _looks_like_unit(value: object) -> bool:
    raw = _clean_text(value)
    if raw == "PA":
        return False
    if "%" in raw:
        return True
    token = _token(value)
    if not token:
        return False
    return token in {
        "c",
        "degc",
        "s",
        "sec",
        "min",
        "h",
        "pa",
        "kpa",
        "mpa",
        "gpa",
        "cm1",
        "nm1",
        "au",
        "abs",
        "百分比",
        "kjm2",
        "kjm²",
        "jm",
        "j",
    } or token in {"", "1"}


def _unit_row_score(raw: pd.DataFrame, row_index: int, columns: tuple[int, ...]) -> int:
    if row_index >= raw.shape[0]:
        return -1
    return sum(1 for column in columns if _looks_like_unit(raw.iat[row_index, column]))


def _sample_from_row(
    raw: pd.DataFrame, row_index: int | None, *, start: int, stop: int, fallback: str
) -> str:
    if row_index is None or row_index >= raw.shape[0]:
        return fallback
    for column in range(start, min(stop, raw.shape[1])):
        value = _clean_text(raw.iat[row_index, column])
        if (
            value
            and (not _looks_like_unit(value) or len(_token(value)) > 5)
            and not _axis_match(value, ("time", "strain", "stress", "σ"))
        ):
            return value
    return fallback


def _scan_curve_series_table(
    raw: pd.DataFrame,
    *,
    x_aliases: tuple[str, ...],
    y_aliases: tuple[str, ...],
    x_label: str,
    y_label: str,
    default_x_unit: str,
    default_y_unit: str,
    sample_prefix: str,
) -> list[CurveSeriesPayload]:
    best: list[CurveSeriesPayload] = []
    for header_index in range(max(0, raw.shape[0] - 2)):
        row_values = raw.iloc[header_index].tolist()
        pairs: list[tuple[int, int]] = []
        for x_index, value in enumerate(row_values[:-1]):
            if not _axis_match(value, x_aliases):
                continue
            search_stop = min(x_index + 5, raw.shape[1])
            for y_index in range(x_index + 1, search_stop):
                if _axis_match(row_values[y_index], y_aliases):
                    pairs.append((x_index, y_index))
                    break
        if not pairs:
            continue
        columns = tuple(column for pair in pairs for column in pair)
        first_extra = header_index + 1
        second_extra = header_index + 2
        first_unit_score = _unit_row_score(raw, first_extra, columns)
        second_unit_score = _unit_row_score(raw, second_extra, columns)
        unit_index = (
            first_extra if first_unit_score >= second_unit_score else second_extra
        )
        sample_index = second_extra if unit_index == first_extra else first_extra
        if max(first_unit_score, second_unit_score) <= 0:
            unit_index = -1
            first_row_is_numeric_data = any(
                _float(raw.iat[first_extra, x_index]) is not None
                and _float(raw.iat[first_extra, y_index]) is not None
                for x_index, y_index in pairs
                if first_extra < raw.shape[0]
            )
            preceding_sample_index = header_index - 1
            preceding_row_has_samples = header_index > 0 and all(
                any(
                    (label := _clean_text(raw.iat[preceding_sample_index, column]))
                    and _float(label) is None
                    and (not _looks_like_unit(label) or len(_token(label)) > 5)
                    and not _axis_match(label, (*x_aliases, *y_aliases))
                    for column in range(x_index, min(y_index + 1, raw.shape[1]))
                )
                for x_index, y_index in pairs
            )
            if first_row_is_numeric_data:
                sample_index = (
                    preceding_sample_index if preceding_row_has_samples else None
                )
            else:
                sample_index = header_index + 1
            data_start = (
                header_index + 1 if first_row_is_numeric_data else header_index + 2
            )
        else:
            data_start = max(header_index + 1, unit_index + 1, sample_index + 1)
        candidate_series: list[CurveSeriesPayload] = []
        for series_index, (x_index, y_index) in enumerate(pairs, start=1):
            points: list[tuple[float, float]] = []
            for row_index in range(data_start, raw.shape[0]):
                x_value = _float(raw.iat[row_index, x_index])
                y_value = _float(raw.iat[row_index, y_index])
                if x_value is not None and y_value is not None:
                    points.append((x_value, y_value))
            if not points:
                continue
            x_unit = default_x_unit
            y_unit = default_y_unit
            if unit_index >= 0:
                x_unit = _clean_text(raw.iat[unit_index, x_index]).strip("[]") or x_unit
                y_unit = _clean_text(raw.iat[unit_index, y_index]).strip("[]") or y_unit
            sample = _sample_from_row(
                raw,
                sample_index,
                start=x_index,
                stop=min(y_index + 3, raw.shape[1]),
                fallback=f"{sample_prefix} {series_index}",
            )
            candidate_series.append(
                CurveSeriesPayload(
                    sample=sample,
                    x_label=x_label,
                    x_unit=x_unit,
                    y_label=y_label,
                    y_unit=y_unit,
                    points=tuple(points),
                    diagnostics={
                        "source_x_header": _clean_text(row_values[x_index]),
                        "source_y_header": _clean_text(row_values[y_index]),
                        "source_x_unit": x_unit,
                        "source_y_unit": y_unit,
                    },
                )
            )
        if sum(len(series.points) for series in candidate_series) > sum(
            len(series.points) for series in best
        ):
            best = candidate_series
    return best


def _scan_curve_series_source(
    source: Path,
    *,
    x_aliases: tuple[str, ...],
    y_aliases: tuple[str, ...],
    x_label: str,
    y_label: str,
    default_x_unit: str,
    default_y_unit: str,
    sample_prefix: str,
) -> list[CurveSeriesPayload]:
    best: list[CurveSeriesPayload] = []
    for sheet_name, raw in _read_candidate_tables(source):
        series = _scan_curve_series_table(
            raw,
            x_aliases=x_aliases,
            y_aliases=y_aliases,
            x_label=x_label,
            y_label=y_label,
            default_x_unit=default_x_unit,
            default_y_unit=default_y_unit,
            sample_prefix=sheet_name or sample_prefix,
        )
        if sum(len(item.points) for item in series) > sum(
            len(item.points) for item in best
        ):
            best = [
                CurveSeriesPayload(
                    sample=item.sample,
                    x_label=item.x_label,
                    x_unit=item.x_unit,
                    y_label=item.y_label,
                    y_unit=item.y_unit,
                    points=item.points,
                    diagnostics={
                        **(item.diagnostics or {}),
                        "source_table": sheet_name,
                    },
                )
                for item in series
            ]
    return best
