"""Original table catalogs, cells and byte-bound observation snapshots.

Catalog membership is physical source fact. A declared observation scope limits
cell reads, without changing original table ordinals or scientific row domains.
"""

from pathlib import Path

from sciplot_core.foundation.source_locations import resolve_source_path
from typing import Any

import pandas as pd

from sciplot_core.data_mapping.raw_tables import _original_text, _read_raw_table
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract import DataSourceReference
from sciplot_core.source_tables.raw_readers import read_sheet_names


def read_original_table(source: Path, sheet: str | None, digest: str) -> pd.DataFrame:
    """Read original cells; callers retain source-snapshot and digest validation."""
    return _read_raw_table(DataSourceReference(
        "source", source.name, digest, sheet=sheet, header_row=None,
    ), source, preserve_cells=True).frame


def original_rows(frame: pd.DataFrame, indices: list[int]) -> list[dict[str, Any]]:
    return [{"row_index": row, "cells": [_original_text(value) for value in frame.iloc[row]]}
            for row in sorted(set(indices)) if 0 <= row < len(frame)]


def source_table_catalog(source: Path, *, expected_sha256: str | None = None) -> dict[str, Any] | None:
    """List every physical table without reading its measurement cells."""
    source = source.expanduser().resolve()
    if not resolve_source_path(source, expected_sha256=expected_sha256).is_file() or source.suffix.casefold() not in {".csv", ".tsv", ".xlsx", ".xls", ".xlsm"}:
        return None
    before = file_sha256(resolve_source_path(source, expected_sha256=expected_sha256))
    if expected_sha256 is not None and before != expected_sha256:
        raise ValueError("The original table changed from its exact declared byte version.")
    sheets: list[str | None] = [None]
    if source.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}:
        sheets = list(read_sheet_names(source, expected_sha256=before))
    if file_sha256(resolve_source_path(source, expected_sha256=before)) != before:
        raise ValueError("Table-choice source changed while reading.")
    return {"source": str(source), "file_sha256": before,
            "tables": [{"table_id": f"table:{index}", "sheet": sheet} for index, sheet in enumerate(sheets)]}


def source_table_snapshot(source: Path, *, rule_id: str | None = None,
                          sheets: list[str | None] | None = None,
                          expected_sha256: str | None = None) -> dict[str, Any] | None:
    """Observe declared sheets; omission preserves historical full snapshots."""
    catalog = (source_table_catalog(source) if expected_sha256 is None else
               source_table_catalog(source, expected_sha256=expected_sha256))
    if catalog is None:
        return None
    source = Path(catalog["source"])
    before = catalog["file_sha256"]
    if sheets is not None and (not sheets or any(sheet not in [item["sheet"] for item in catalog["tables"]] for sheet in sheets)):
        raise ValueError("Select exact original worksheet names (null for CSV/TSV); observation scope must be nonempty.")
    tables: list[dict[str, Any]] = []
    for item in catalog["tables"]:
        sheet = item["sheet"]
        if sheets is not None and sheet not in sheets:
            continue
        try:
            frame = read_original_table(source, sheet, before)
        except ValueError as exc:
            if "empty" not in str(exc):
                raise
            table = {"sheet": sheet, "row_count": 0, "column_count": 0, "rows": []}
        else:
            table = {"sheet": sheet, "row_count": len(frame), "column_count": frame.shape[1],
                     "rows": original_rows(frame.iloc[:, :64], list(range(min(32, len(frame))))),
                     "preview_truncated": len(frame) > 32 or frame.shape[1] > 64}
        if sheets is not None:
            table["table_id"] = item["table_id"]
        tables.append(table)
    if file_sha256(resolve_source_path(source, expected_sha256=before)) != before:
        raise ValueError("Table-choice source changed while reading.")
    return {"kind": "sciplot_table_choice", "version": 1, "source": str(source),
            "file_sha256": before, "rule_id": rule_id, "tables": tables,
            **({"catalog": catalog["tables"], "observed_sheets": [table["sheet"] for table in tables]} if sheets is not None else {}),
            "indices": "zero_based; data_end_row is exclusive"}


def table_position(table: dict[str, Any], fallback: int) -> int:
    """Recover an observed table's original ordinal, including scoped views."""
    return int(table["table_id"].removeprefix("table:")) if "table_id" in table else fallback
