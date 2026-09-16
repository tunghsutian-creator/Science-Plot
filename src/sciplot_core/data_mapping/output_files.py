"""Create collision-safe mapped output names, files, hashes, and stable identifiers."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
import csv
from io import StringIO
from itertools import zip_longest
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.path_names import safe_filename
from sciplot_core.mapping_contract import (
    DataMappingProposal,
    DataSourceReference,
)


def _safe_output_name(
    reference: DataSourceReference,
    proposal: DataMappingProposal,
    *,
    used: set[str],
) -> str:
    label = (
        proposal.sample_labels.get(reference.source_id)
        or Path(reference.relative_path).stem
        or reference.source_id
    )
    candidate = safe_filename(f"{label}.csv")
    candidate_key = _filename_collision_key(candidate)
    if candidate_key not in used:
        used.add(candidate_key)
        return candidate
    stem = Path(candidate).stem
    fallback = safe_filename(f"{stem}__{reference.source_id}.csv")
    index = 2
    while _filename_collision_key(fallback) in used:
        fallback = safe_filename(f"{stem}__{reference.source_id}_{index}.csv")
        index += 1
    used.add(_filename_collision_key(fallback))
    return fallback


def _filename_collision_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _write_mapped_csv(path: Path, frame: pd.DataFrame, *, full_precision: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        float_format=None if full_precision else "%.15g",
    )


def _mapped_csv_sha256(frame: pd.DataFrame, *, full_precision: bool = False) -> str:
    text = frame.to_csv(
        None,
        index=False,
        lineterminator="\n",
        float_format=None if full_precision else "%.15g",
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def paired_table_text(proposal: DataMappingProposal, frames: dict[str, pd.DataFrame]) -> str:
    """Compose selected pairs as the existing three-metadata-row adapter contract."""
    headers, units, labels, series = [], [], [], []
    for reference in proposal.sources:
        columns = [column for column in proposal.columns if column.source_id == reference.source_id]
        if [column.role for column in columns] != ["x", "y"]:
            raise ValueError("Explicit table choice requires one ordered x/y pair per source view.")
        frame = frames[reference.source_id]
        for column in columns:
            unit = proposal.unit_overrides[column.output_column]
            header = column.output_column
            if header.endswith(f" ({unit})"):
                header = header[:-(len(unit) + 3)]
            headers.append(header)
            units.append(unit)
            labels.append(proposal.sample_labels[reference.source_id])
            series.append(frame[column.output_column].tolist())
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows([headers, units, labels])
    # Rectangular serialization only: both cells of a finished XY pair stay
    # empty. Each source frame and its point count remain independently exact.
    writer.writerows(zip_longest(*series, fillvalue=""))
    return buffer.getvalue()


def _rebase_paths(value: Any, *, source: Path, target: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _rebase_paths(item, source=source, target=target)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rebase_paths(item, source=source, target=target) for item in value]
    if isinstance(value, str):
        prefix = str(source)
        if value == prefix:
            return str(target)
        if value.startswith(prefix + os.sep):
            return str(target) + value[len(prefix) :]
    return value


def _stable_id(prefix: str, value: str, used: set[str]) -> str:
    token = re.sub(r"[^0-9A-Za-z]+", "_", str(value).strip().casefold()).strip("_")
    base = f"{prefix}_{token or 'item'}"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate
