"""Resolve and load the processed source table selected for a plot."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.foundation.text_files import decode_text


TABLE_SUFFIXES = {".csv", ".tsv", ".txt", ".tab", ".dat", ".xlsx", ".xls"}


def data_source(manifest: dict[str, Any]) -> Path | None:
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    values: list[object] = [
        result.get("processed_source"),
        result.get("data_snapshot_source"),
        manifest.get("processed_source"),
        manifest.get("input"),
    ]
    request = (
        manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    )
    values.append(request.get("input"))
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if candidate.exists():
            return candidate.resolve()
    return None


def load_source_table(source: Path | None) -> pd.DataFrame | None:
    if source is None:
        return None
    if source.is_dir():
        files = sorted(
            path
            for path in source.rglob("*")
            if path.is_file() and path.suffix.casefold() in TABLE_SUFFIXES
        )
        if len(files) != 1:
            preferred = [
                path
                for path in files
                if any(
                    token in path.stem.casefold()
                    for token in ("comparison", "plotting", "prepared", "processed")
                )
            ]
            if len(preferred) != 1:
                return None
            files = preferred
        source = files[0] if files else None
    if source is None or not source.exists() or not source.is_file():
        return None
    suffix = source.suffix.casefold()
    try:
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(source, sheet_name=0, header=None)
        text = decode_text(source)
        for index, line in enumerate(text.splitlines()):
            if "Interval data:" in line:
                header = line.split("Interval data:", maxsplit=1)[1].lstrip("\t, ")
                return pd.read_csv(
                    StringIO("\n".join([header, *text.splitlines()[index + 1 :]])),
                    sep="\t",
                    header=None,
                    engine="python",
                )
        tab_count = text.count("\t")
        comma_count = text.count(",")
        separator = (
            "\t"
            if suffix in {".tsv", ".tab", ".dat"} or tab_count > comma_count
            else ","
        )
        return pd.read_csv(StringIO(text), sep=separator, header=None, engine="python")
    except (OSError, ValueError, TypeError, pd.errors.ParserError):
        return None


def sample_hint(manifest: dict[str, Any], source: Path | None) -> str:
    semantic = (
        manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
    )
    samples = (
        semantic.get("samples") if isinstance(semantic.get("samples"), list) else []
    )
    names = [
        str(item.get("name"))
        for item in samples
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    if len(names) == 1:
        return names[0]
    if source is not None and source.is_file():
        return source.stem
    if (
        source is not None
        and source.is_dir()
        and source.name not in {"source", "processed", "studio"}
    ):
        return source.name
    return ""
