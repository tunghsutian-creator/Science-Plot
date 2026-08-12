"""Resolve table-source files without reading or ranking their contents."""

from __future__ import annotations

from pathlib import Path


_TABLE_SOURCE_SUFFIXES = frozenset(
    {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".xlsm"}
)
_WORKBOOK_SOURCE_SUFFIXES = frozenset({".xlsx", ".xls", ".xlsm"})


def table_source_files(source: Path) -> tuple[Path, ...]:
    """Return scanner-supported files in deterministic recursive order."""

    if not source.is_dir():
        return (source,)
    return tuple(
        path
        for path in sorted(source.rglob("*"))
        if path.is_file() and path.suffix.casefold() in _TABLE_SOURCE_SUFFIXES
    )


def is_workbook_source(source: Path) -> bool:
    return source.suffix.casefold() in _WORKBOOK_SOURCE_SUFFIXES


def resolve_single_table_source(source: Path, *, context: str) -> Path:
    """Resolve a file directly or require exactly one supported directory member."""

    resolved = source.expanduser().resolve()
    if resolved.is_file():
        return resolved
    candidates = table_source_files(resolved) if resolved.is_dir() else ()
    if len(candidates) != 1:
        raise ValueError(
            f"{context} requires exactly one supported source file in "
            f"{resolved}; found {len(candidates)}."
        )
    return candidates[0].resolve()
