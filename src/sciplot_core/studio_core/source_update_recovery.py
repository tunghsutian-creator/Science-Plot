"""Restore a byte-proven baseline after interrupted top-level replacements."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json


def installation_identity(record: dict[str, Any]) -> str:
    return canonical_json_sha256({key: record[key] for key in (
        "project", "review", "archive", "base_files", "archived_files", "result_files", "replacement_names",
    )}, allow_nan=False)


def restore_interrupted_update(
    project: Path, record: dict[str, Any], outcome: Path, *,
    inventory: Callable[[Path], dict[str, str]], check_path: Callable[[Path], None],
) -> bool:
    """No unknown bytes are removed; a second interruption is resumable too."""
    if record.get("version") != 2 or record.get("status") not in {"pending", "recovering"}:
        return False
    if record.get("installation_sha256") != installation_identity(record):
        raise ValueError("Source-update installation evidence changed; preserve its archive.")
    names = record["replacement_names"]
    if (not isinstance(names, list) or len(names) != len(set(names))
            or any(not isinstance(name, str) or Path(name).name != name
                   or name in {".", "..", "runs", "delivery"} for name in names)):
        raise ValueError("Invalid source-update replacement paths.")
    archive = Path(record["archive"])
    saved = archive.with_name(archive.name + ".interrupted")
    for path in (project, archive, saved):
        check_path(path)
    current = inventory(project)
    archived = inventory(archive) if archive.exists() else {}
    preserved = inventory(saved) if saved.exists() else {}
    base, result = record["base_files"], record["result_files"]

    def part(files: dict[str, str], name: str) -> dict[str, str]:
        return {key: digest for key, digest in files.items() if key.split("/", 1)[0] == name}

    def outside(files: dict[str, str]) -> dict[str, str]:
        return {key: digest for key, digest in files.items() if key.split("/", 1)[0] not in names}

    if outside(current) != outside(base) or outside(archived) or outside(preserved):
        return False
    actions = []
    for name in names:
        old, new = part(base, name), part(result, name)
        active, prior, kept = part(current, name), part(archived, name), part(preserved, name)
        if kept and kept != new:
            return False
        if active == old and not prior:
            actions.append((name, False, False))
        elif active == new and prior == old and not kept:
            actions.append((name, True, bool(old)))
        elif not active and prior == old:
            actions.append((name, False, bool(old)))
        else:
            return False
    # Classify the complete installation before the first mutation.
    record["status"] = "recovering"
    atomic_write_json(outcome, record)
    saved.mkdir(exist_ok=True)
    for name, preserve_new, restore_old in reversed(actions):
        if preserve_new and (project / name).exists():
            os.replace(project / name, saved / name)
        if restore_old:
            os.replace(archive / name, project / name)
    if inventory(project) != base:
        raise ValueError("Interrupted source-update rollback did not restore its exact baseline.")
    record.update(status="rolled_back", recovery={
        "status": "baseline_restored", "preserved_candidate": str(saved),
        "base_sha256": canonical_json_sha256(base, allow_nan=False),
    })
    # Keep the recovered intent even when a later retry installs a new candidate.
    atomic_write_json(archive.with_name(archive.name + ".rollback.json"), record)
    atomic_write_json(outcome, record)
    return True
