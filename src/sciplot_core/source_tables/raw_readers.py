"""Read supported spreadsheet and delimited files without assigning headers."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
from sciplot_core.foundation.text_decoding import decode_text_file


def _read_delimited(path: Path, **kwargs: Any) -> pd.DataFrame:
    kwargs.setdefault("skip_blank_lines", False)
    try:
        return pd.read_csv(StringIO(decode_text_file(path)), **kwargs)
    except (csv.Error, pd.errors.ParserError) as exc:
        raise ValueError(f"Failed to parse {path}") from exc


def _read_ragged_delimited(path: Path, *, delimiter: str) -> pd.DataFrame:
    rows = list(csv.reader(StringIO(decode_text_file(path)), delimiter=delimiter))
    width = max((len(row) for row in rows), default=0)
    padded = [row + [None] * (width - len(row)) for row in rows]
    return pd.DataFrame(padded)


def _read_csv(path: Path, *, preserve_na_tokens: bool) -> pd.DataFrame:
    """Read ordinary or ragged CSV without trusting one misleading prefix row.

    Instrument exports may prepend variable-width metadata before a regular
    comma-delimited measurement table.  ``sep=None`` can then infer a delimiter
    from the metadata and return the entire source as one text column without
    raising. Quote-aware ragged comma and tab parses are deterministic fallbacks
    when that happens; genuinely one-column CSV files remain one column.
    """

    try:
        inferred = _read_delimited(
            path,
            header=None,
            sep=None,
            engine="python",
            keep_default_na=not preserve_na_tokens,
        )
    except (ValueError, csv.Error):
        inferred = None
    if inferred is not None and inferred.shape[1] != 1:
        return inferred
    comma = _read_ragged_delimited(path, delimiter=",")
    tab = _read_ragged_delimited(path, delimiter="\t")
    ragged = max((comma, tab), key=lambda frame: frame.shape[1])
    if ragged.shape[1] > 1:
        return ragged
    return inferred if inferred is not None else ragged


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
    if suffix in {".csv", ".txt"}:
        return _read_csv(table_path, preserve_na_tokens=preserve_na_tokens)
    if suffix == ".tsv":
        return _read_delimited(
            table_path,
            header=None,
            sep="\t",
            keep_default_na=not preserve_na_tokens,
        )
    raise ValueError(f"Unsupported file format: {suffix}")


__all__ = ["read_raw_table"]
