"""Create collision-safe mapped output names, files, hashes, and stable identifiers."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
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


def _write_mapped_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        float_format="%.15g",
    )


def _mapped_csv_sha256(frame: pd.DataFrame) -> str:
    text = frame.to_csv(
        None,
        index=False,
        lineterminator="\n",
        float_format="%.15g",
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
