"""Read scanner candidate tables while preserving scientific text lexemes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sciplot_core.ingest import normalized_source
from sciplot_core.semantic_sources.table_source_files import (
    is_workbook_source,
    table_source_files,
)
from sciplot_core.source_tables import read_raw_table


def read_raw_table_normalized(path: Path) -> pd.DataFrame:
    """Decode one text table without collapsing NA-shaped source text."""

    with normalized_source(path) as normalized:
        return _structural_empty_cells_as_missing(
            read_raw_table(normalized, preserve_na_tokens=True)
        )


def read_candidate_tables(source: Path) -> list[tuple[str, pd.DataFrame]]:
    """Return non-empty candidate sheets/files without content ranking."""

    tables: list[tuple[str, pd.DataFrame]] = []
    for path in table_source_files(source):
        if is_workbook_source(path):
            with pd.ExcelFile(path) as workbook:
                tables.extend(
                    (
                        f"{path.stem}:{sheet_name}",
                        _structural_empty_cells_as_missing(
                            workbook.parse(
                                sheet_name,
                                header=None,
                                keep_default_na=False,
                            )
                        ).dropna(axis=1, how="all"),
                    )
                    for sheet_name in workbook.sheet_names
                )
        else:
            tables.append(
                (
                    path.stem,
                    read_raw_table_normalized(path).dropna(axis=1, how="all"),
                )
            )
    return [
        (name, _without_outer_empty_rows(table))
        for name, table in tables
        if not _without_outer_empty_rows(table).empty
    ]


def _structural_empty_cells_as_missing(table: pd.DataFrame) -> pd.DataFrame:
    return table.replace(r"^\s*$", pd.NA, regex=True)


def _without_outer_empty_rows(table: pd.DataFrame) -> pd.DataFrame:
    """Keep interior blank rows because they can close a scientific data block."""

    nonempty = table.notna().any(axis=1).to_numpy().nonzero()[0]
    if not len(nonempty):
        return table.iloc[0:0]
    return table.iloc[nonempty[0] : nonempty[-1] + 1]


__all__ = ["read_candidate_tables", "read_raw_table_normalized"]
