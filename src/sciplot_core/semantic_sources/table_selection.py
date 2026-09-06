"""Bind an explicit worksheet confirmation to the exact current workbook."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.semantic_sources.table_source_files import resolve_single_table_source


def confirmed_source_sheet(source: Path, confirmations: object) -> str | None:
    """Old preview metadata is not an instruction to drop other worksheets."""

    if not isinstance(confirmations, list | tuple):
        return None
    selections = [
        item for item in confirmations
        if isinstance(item, dict) and item.get("sheet_selected") is True
    ]
    if not selections:
        return None
    path = resolve_single_table_source(source, context="Confirmed worksheet")
    digest = file_sha256(path)
    matched = [item for item in selections if item.get("source_sha256") == digest]
    if not matched:
        raise ValueError("Worksheet confirmation no longer matches the source bytes; inspect the current file again.")
    names = [item.get("sheet") for item in matched]
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("Explicit worksheet confirmation requires a worksheet name.")
    sheets = set(names)
    if len(sheets) != 1:
        raise ValueError("Conflicting worksheet confirmations; select one worksheet explicitly.")
    sheet = next(iter(sheets))
    if not isinstance(sheet, str) or not sheet:
        raise ValueError("Explicit worksheet confirmation requires a worksheet name.")
    if path.suffix.lower() not in {".xls", ".xlsx"}:
        raise ValueError("Worksheet selection requires an Excel workbook.")
    return sheet
