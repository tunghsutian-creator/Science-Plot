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


def reserve_unique_directory(directory: Path, dirname: str) -> Path:
    """Atomically reserve one unique top-level directory.

    Unlike :func:`unique_path`, the returned path already exists and is owned
    by the caller. Concurrent callers therefore cannot select the same name.
    """

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / dirname
    stem = path.stem
    suffix = path.suffix
    index = 1
    while True:
        candidate = path if index == 1 else directory / f"{stem}_{index}{suffix}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            index += 1
        else:
            return candidate


def reserve_unique_file(directory: Path, filename: str) -> Path:
    """Atomically reserve one unique top-level file."""

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    stem = path.stem
    suffix = path.suffix
    index = 1
    while True:
        candidate = path if index == 1 else directory / f"{stem}_{index}{suffix}"
        try:
            candidate.touch(exist_ok=False)
        except FileExistsError:
            index += 1
        else:
            return candidate


__all__ = [
    "reserve_unique_directory",
    "reserve_unique_file",
    "safe_filename",
    "slug",
    "unique_path",
]
