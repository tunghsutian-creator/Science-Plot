"""Write user-facing plotted-data CSV exports."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.path_names import slug
from sciplot_core.plot_data.source_tables import (
    data_source as _data_source,
    load_source_table as _load_source_table,
    sample_hint as _sample_hint,
)
from sciplot_core.plot_data.spec_tables import (
    read_json as _read_json,
    spec_paths as _spec_paths,
    spec_to_table as _spec_to_table,
    unit_from_label as _unit_from_label,
)


def build_plot_data_exports(
    manifest: dict[str, Any], *, destination: Path
) -> list[dict[str, Any]]:
    """Write the user-facing four-row CSV for the current plotted data.

    The delivery surface intentionally contains data only, never analysis
    metrics, raw archives, manifests, or renderer diagnostics.  A persisted
    processed source is preferred because it is the exact table selected for
    the plot.  When a source table is unavailable, the saved Veusz spec is the
    next-best deterministic source and preserves the plotted series values.
    """

    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    project_name = _project_name(manifest)

    source = _data_source(manifest)
    source_table = _load_source_table(source) if source is not None else None
    if source_table is not None and not source_table.empty:
        output = destination / f"{project_name}_plot_data.csv"
        _write_four_row_csv(
            source_table, output, sample_hint=_sample_hint(manifest, source)
        )
        return [_data_record(output, source=source, source_kind="processed_source")]

    records: list[dict[str, Any]] = []
    for index, spec_path in enumerate(_spec_paths(manifest), start=1):
        spec = _read_json(spec_path)
        table = _spec_to_table(spec, manifest=manifest, spec_path=spec_path)
        if table is None or table.empty:
            continue
        stem = project_name if index == 1 else f"{project_name}_{index:02d}"
        output = destination / f"{stem}_plot_data.csv"
        _write_table_csv(table, output)
        records.append(_data_record(output, source=spec_path, source_kind="veusz_spec"))
    return records


def _project_name(manifest: dict[str, Any]) -> str:
    output = manifest.get("output")
    if isinstance(output, str) and output.strip():
        return slug(Path(output).name)
    return slug(str(manifest.get("project") or "sciplot"))


def _write_four_row_csv(table: pd.DataFrame, output: Path, *, sample_hint: str) -> None:
    normalized = table.copy()
    if not _looks_like_four_row_table(normalized):
        names = (
            [str(value).strip() for value in normalized.iloc[0].tolist()]
            if not normalized.empty
            else []
        )
        units = [_unit_from_label(value) for value in names]
        comments = [sample_hint] * len(names)
        normalized = pd.DataFrame(
            [names, units, comments, *normalized.iloc[1:].values.tolist()]
        )
    _write_table_csv(normalized, output)


def _looks_like_four_row_table(table: pd.DataFrame) -> bool:
    if table.shape[0] < 4 or table.shape[1] < 1:
        return False
    data = table.iloc[3:].apply(pd.to_numeric, errors="coerce")
    numeric_count = int(data.notna().sum().sum())
    if numeric_count < 2:
        return False
    first_rows = table.iloc[:3].fillna("").astype(str)
    return bool(first_rows.iloc[0].str.strip().any()) and bool(
        first_rows.iloc[2].str.strip().any()
    )


def _write_table_csv(table: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = table.fillna("").astype(object).values.tolist()
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        for row in rows:
            writer.writerow([_format_cell(value) for value in row])


def _format_cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return format(value, ".15g")
    return value


def _data_record(
    path: Path, *, source: Path | None, source_kind: str
) -> dict[str, Any]:
    return {
        "path": str(path),
        "relative_path": str(Path("data") / path.name),
        "format": "csv",
        "source": str(source) if source is not None else None,
        "source_kind": source_kind,
        "exists": path.exists(),
        "sha256": existing_file_sha256(path),
    }


__all__ = ["build_plot_data_exports"]
