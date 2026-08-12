"""Materialize confirmed intake groups into project-local source evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sciplot_core.foundation.path_names import safe_filename, slug, unique_path

from ..models import IntakeGroupInput


def materialize_intake_groups(
    *,
    project_dir: Path,
    groups: list[IntakeGroupInput],
) -> tuple[Path, Path, list[dict[str, Any]]]:
    """Write raw/source copies and return their manifest representation."""
    raw_dir = project_dir / "raw"
    source_dir = project_dir / "source"
    runs_dir = project_dir / "runs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    manifest_groups: list[dict[str, Any]] = []
    for group in groups:
        sample = group.sample.strip()
        sample_dir = raw_dir / slug(sample)
        sample_dir.mkdir(parents=True, exist_ok=True)
        group_files: list[dict[str, Any]] = []
        for incoming in group.files:
            raw_path = unique_path(sample_dir, safe_filename(incoming.name))
            raw_path.write_bytes(incoming.content)
            source_name = safe_filename(f"{sample}__{raw_path.name}")
            source_path = unique_path(source_dir, source_name)
            source_path.write_bytes(incoming.content)
            group_files.append(
                {
                    "original_name": incoming.name,
                    "raw_path": str(raw_path),
                    "source_path": str(source_path),
                    "size_bytes": len(incoming.content),
                    "sha256": hashlib.sha256(incoming.content).hexdigest(),
                }
            )
        manifest_groups.append({"sample": sample, "files": group_files})

    return source_dir, runs_dir, manifest_groups
