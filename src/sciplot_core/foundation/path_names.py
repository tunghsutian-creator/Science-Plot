from __future__ import annotations

import re
from pathlib import Path


def slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value).strip("._-")
    return cleaned[:80] or "sciplot_project"


def safe_filename(value: str) -> str:
    name = Path(value).name
    cleaned = re.sub(r"[/:\\]+", "_", name).strip() or "file"
    return cleaned[:120]


def unique_path(directory: Path, filename: str) -> Path:
    path = directory / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


__all__ = ["safe_filename", "slug", "unique_path"]
