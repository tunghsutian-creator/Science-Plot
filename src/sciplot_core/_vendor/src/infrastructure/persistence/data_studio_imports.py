from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from platformdirs import user_data_path

from src.text_normalization import slugify_label

APP_NAME = "SciPlot"
_APP_AUTHOR = False
_DATA_STUDIO_IMPORT_RETENTION = 20


def _data_root() -> Path:
    return user_data_path(APP_NAME, appauthor=_APP_AUTHOR, ensure_exists=True)


def managed_data_studio_imports_root() -> Path:
    path = _data_root() / "data_studio_imports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_path(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_dir():
        file_count = sum(1 for child in path.rglob("*") if child.is_file())
        dir_count = sum(1 for child in path.rglob("*") if child.is_dir()) + 1
        shutil.rmtree(path)
        return file_count, dir_count
    path.unlink(missing_ok=True)
    return 1, 0


def _clear_directory(path: Path) -> tuple[int, int]:
    removed_files = 0
    removed_directories = 0
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return removed_files, removed_directories
    for child in path.iterdir():
        files, directories = _remove_path(child)
        removed_files += files
        removed_directories += directories
    path.mkdir(parents=True, exist_ok=True)
    return removed_files, removed_directories


def _prune_directory_children(path: Path, *, keep: int, skip: set[Path] | None = None) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    skip_paths = {item.resolve() for item in (skip or set())}
    children = [child for child in path.iterdir() if child.resolve() not in skip_paths]
    children.sort(key=lambda child: child.stat().st_mtime, reverse=True)
    removed_files = 0
    removed_directories = 0
    for child in children[keep:]:
        files, directories = _remove_path(child)
        removed_files += files
        removed_directories += directories
    return removed_files, removed_directories


def _hash_suffix(*parts: object, length: int = 10) -> str:
    digest = hashlib.sha256("||".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return digest[:length]


def prepare_managed_data_studio_import_dir(input_path: Path) -> Path:
    root = managed_data_studio_imports_root()
    stem = slugify_label(input_path.stem) or "data_studio_import"
    try:
        mtime_ns = input_path.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = 0
    directory = root / f"{stem}_{_hash_suffix(input_path.resolve(), mtime_ns)}"
    _clear_directory(directory)
    _prune_directory_children(root, keep=_DATA_STUDIO_IMPORT_RETENTION, skip={directory})
    return directory


__all__ = [
    "managed_data_studio_imports_root",
    "prepare_managed_data_studio_import_dir",
]
