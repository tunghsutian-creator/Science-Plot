"""Read supported spreadsheet and delimited files without assigning headers."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd


ENCODINGS_TO_TRY = (
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "gb18030",
    "latin-1",
)


def _read_delimited(path: Path, **kwargs: Any) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ENCODINGS_TO_TRY:
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except (UnicodeError, pd.errors.ParserError) as exc:
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
        if not text.startswith("\ufffe"):
            return text
    raise ValueError(f"Failed to decode {path}") from last_error


def _read_ragged_delimited(path: Path, *, delimiter: str) -> pd.DataFrame:
    rows = [line.split(delimiter) for line in _decode_text(path).splitlines()]
    width = max((len(row) for row in rows), default=0)
    padded = [row + [None] * (width - len(row)) for row in rows]
    return pd.DataFrame(padded)


def read_raw_table(
    path: str | Path,
    sheet_name: str | int = 0,
    *,
    preserve_na_tokens: bool = False,
) -> pd.DataFrame:
    """Read CSV/TSV/TXT/XLSX without assigning a header row."""

    table_path = Path(path)
    suffix = table_path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(
            table_path,
            header=None,
            sheet_name=sheet_name,
            keep_default_na=not preserve_na_tokens,
        )
    if suffix == ".csv":
        try:
            return _read_delimited(
                table_path,
                header=None,
                sep=None,
                engine="python",
                keep_default_na=not preserve_na_tokens,
            )
        except (ValueError, csv.Error):
            return _read_ragged_delimited(table_path, delimiter="\t")
    if suffix in {".tsv", ".txt"}:
        return _read_delimited(
            table_path,
            header=None,
            sep=None,
            engine="python",
            keep_default_na=not preserve_na_tokens,
        )
    raise ValueError(f"Unsupported file format: {suffix}")


__all__ = ["ENCODINGS_TO_TRY", "read_raw_table"]
