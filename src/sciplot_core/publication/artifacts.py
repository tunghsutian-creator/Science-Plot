"""Describe publication source and output artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.file_hashing import file_sha256


def _table_shape(path: Path) -> list[int] | None:
    if path.stat().st_size > 20 * 1024 * 1024:
        return None
    try:
        suffix = path.suffix.casefold()
        if suffix in {".xlsx", ".xls"}:
            frame = pd.read_excel(path, sheet_name=0, header=None)
        elif suffix == ".tsv":
            frame = pd.read_csv(path, sep="\t", header=None)
        elif suffix in {".csv", ".txt"}:
            frame = pd.read_csv(path, header=None)
        else:
            return None
    except Exception:
        return None
    return [int(frame.shape[0]), int(frame.shape[1])]


def artifact_record(path: str | Path, *, artifact_id: str, role: str) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {
            "id": artifact_id,
            "role": role,
            "path": str(resolved),
            "exists": False,
            "sha256": None,
        }
    if resolved.is_file():
        return {
            "id": artifact_id,
            "role": role,
            "kind": "file",
            "path": str(resolved),
            "exists": True,
            "size_bytes": resolved.stat().st_size,
            "sha256": file_sha256(resolved),
            "table_shape": _table_shape(resolved),
        }

    digest = hashlib.sha256()
    member_count = 0
    total_bytes = 0
    for member in sorted(path for path in resolved.rglob("*") if path.is_file()):
        relative = member.relative_to(resolved).as_posix()
        member_hash = file_sha256(member)
        digest.update(relative.encode("utf-8"))
        digest.update(member_hash.encode("ascii"))
        member_count += 1
        total_bytes += member.stat().st_size
    return {
        "id": artifact_id,
        "role": role,
        "kind": "directory",
        "path": str(resolved),
        "exists": True,
        "size_bytes": total_bytes,
        "sha256": digest.hexdigest(),
        "member_count": member_count,
        "table_shape": None,
    }
