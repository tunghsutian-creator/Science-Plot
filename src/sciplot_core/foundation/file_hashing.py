from __future__ import annotations

import hashlib
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def existing_file_sha256(path: Path) -> str | None:
    return file_sha256(path) if path.is_file() else None


__all__ = ["existing_file_sha256", "file_sha256"]
