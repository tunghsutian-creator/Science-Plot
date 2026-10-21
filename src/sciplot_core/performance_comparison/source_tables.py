"""Resolve, read, and identify performance-comparison tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_files import decode_text
from sciplot_core.performance_comparison.models import (
    PerformanceComparisonError,
)

from sciplot_core.performance_comparison.source_values import (
    _HEADER_ALIASES,
    _REQUIRED_COLUMNS,
    _token,
)


def _resolve_source(source: Path, *, allow_missing_unit: bool = False) -> Path:
    resolved = source.expanduser().resolve()
    if resolved.is_file():
        return resolved
    if not resolved.is_dir():
        raise FileNotFoundError(f"Performance comparison source not found: {resolved}")
    candidates = [
        path
        for path in sorted(resolved.rglob("*"))
        if path.is_file()
        and path.suffix.casefold() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
    ]
    matching = [
        path
        for path in candidates
        if _source_has_required_headers(path, allow_missing_unit=allow_missing_unit)
    ]
    if len(matching) != 1:
        raise PerformanceComparisonError(
            "performance_source_ambiguous",
            "Performance comparison directories need exactly one tidy table "
            f"with the required headers; found {len(matching)}.",
        )
    return matching[0]


def _read_text_table(path: Path, *, exact_numeric: bool = False) -> pd.DataFrame:
    text = decode_text(path)
    tab_count = text.count("\t")
    comma_count = text.count(",")
    separator: str | None
    if path.suffix.casefold() == ".tsv" or tab_count > comma_count:
        separator = "\t"
    elif path.suffix.casefold() == ".csv" or comma_count:
        separator = ","
    else:
        separator = None
    from io import StringIO

    if exact_numeric:
        return pd.read_csv(
            StringIO(text),
            sep=separator,
            engine="python",
            dtype=object,
            skip_blank_lines=False,
            keep_default_na=False,
        )
    return pd.read_csv(StringIO(text), sep=separator, engine="python")


def _read_source_frame(
    path: Path, *, exact_numeric: bool = False, allow_missing_unit: bool = False
) -> pd.DataFrame:
    if path.suffix.casefold() in {".xlsx", ".xls"}:
        sheets = (
            pd.read_excel(path, sheet_name=None, dtype=object, keep_default_na=False)
            if exact_numeric
            else pd.read_excel(path, sheet_name=None)
        )
        matching = [
            frame
            for frame in sheets.values()
            if _required_headers_present(
                frame.columns, allow_missing_unit=allow_missing_unit
            )
        ]
        if len(matching) != 1:
            raise PerformanceComparisonError(
                "performance_workbook_sheet_ambiguous",
                "Performance comparison workbooks need exactly one sheet with "
                f"the required headers; found {len(matching)}.",
            )
        return matching[0]
    return _read_text_table(path, exact_numeric=exact_numeric)


def _canonical_header_map(columns: Any) -> dict[str, object]:
    resolved: dict[str, object] = {}
    for column in columns:
        token = _token(column)
        matches = [
            field for field, aliases in _HEADER_ALIASES.items() if token in aliases
        ]
        if len(matches) > 1:
            raise PerformanceComparisonError(
                "performance_header_ambiguous",
                f"Column {column!r} matches multiple performance fields: {matches}.",
            )
        if not matches:
            continue
        field = matches[0]
        if field in resolved:
            raise PerformanceComparisonError(
                "performance_header_duplicate",
                f"Multiple columns map to the performance field {field!r}.",
            )
        resolved[field] = column
    return resolved


def _required_headers_present(
    columns: Any, *, allow_missing_unit: bool = False
) -> bool:
    try:
        required = (
            _REQUIRED_COLUMNS - {"unit"} if allow_missing_unit else _REQUIRED_COLUMNS
        )
        return required <= set(_canonical_header_map(columns))
    except PerformanceComparisonError:
        return False


def _source_has_required_headers(
    path: Path, *, allow_missing_unit: bool = False
) -> bool:
    try:
        if path.suffix.casefold() in {".xlsx", ".xls"}:
            sheets = pd.read_excel(path, sheet_name=None, nrows=1)
            return (
                sum(
                    _required_headers_present(
                        frame.columns, allow_missing_unit=allow_missing_unit
                    )
                    for frame in sheets.values()
                )
                == 1
            )
        return _required_headers_present(
            _read_text_table(path).columns, allow_missing_unit=allow_missing_unit
        )
    except Exception:
        return False


def is_performance_comparison_source(source: str | Path) -> bool:
    """Return whether a path has the explicit tidy comparison header contract."""

    path = Path(source).expanduser()
    if path.is_file():
        return _source_has_required_headers(path)
    if not path.is_dir():
        return False
    matches = [
        item
        for item in sorted(path.rglob("*"))
        if item.is_file()
        and item.suffix.casefold() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
        and _source_has_required_headers(item)
    ]
    return len(matches) == 1
