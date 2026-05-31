from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from pathlib import Path

from platformdirs import user_cache_path

from src.data_studio.models import DataStudioGroupState, DataStudioSpecimenState

APP_NAME = "SciPlot"
_APP_AUTHOR = False
_DATA_STUDIO_COMPARISON_CONTEXT_RETENTION = 20


def _cache_root() -> Path:
    return user_cache_path(APP_NAME, appauthor=_APP_AUTHOR, ensure_exists=True)


def managed_data_studio_comparison_contexts_root() -> Path:
    path = _cache_root() / "data_studio_comparison_contexts"
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


def comparison_context_cache_key(
    workbook_paths: Iterable[str | Path],
    *,
    group_states: Iterable[DataStudioGroupState] | None = None,
    specimen_states: Iterable[DataStudioSpecimenState] | None = None,
) -> str:
    resolved_workbook_paths = [Path(path).expanduser() for path in workbook_paths]
    payload = {
        "workbook_paths": [str(path) for path in resolved_workbook_paths],
        "workbook_mtime_ns": {
            str(path): path.stat().st_mtime_ns if path.exists() else None
            for path in resolved_workbook_paths
        },
        "group_states": [
            {
                "workbook_path": str(Path(state.workbook_path).expanduser()),
                "display_name": state.display_name,
                "include_in_compare": state.include_in_compare,
                "sort_order": state.sort_order,
            }
            for state in sorted(
                group_states or (),
                key=lambda item: (
                    item.sort_order,
                    str(Path(item.workbook_path).expanduser()),
                    item.display_name.lower(),
                ),
            )
        ],
        "specimen_states": [
            {
                "workbook_path": str(Path(state.workbook_path).expanduser()),
                "specimen_id": state.specimen_id,
                "included": state.included,
                "selected_as_representative": state.selected_as_representative,
            }
            for state in sorted(
                specimen_states or (),
                key=lambda item: (
                    str(Path(item.workbook_path).expanduser()),
                    item.specimen_id.lower(),
                ),
            )
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def prepare_managed_data_studio_comparison_context_dir(
    workbook_paths: Iterable[str | Path],
    *,
    group_states: Iterable[DataStudioGroupState] | None = None,
    specimen_states: Iterable[DataStudioSpecimenState] | None = None,
) -> tuple[str, Path]:
    root = managed_data_studio_comparison_contexts_root()
    cache_key = comparison_context_cache_key(
        workbook_paths,
        group_states=group_states,
        specimen_states=specimen_states,
    )
    directory = root / cache_key
    directory.mkdir(parents=True, exist_ok=True)
    _prune_directory_children(root, keep=_DATA_STUDIO_COMPARISON_CONTEXT_RETENTION, skip={directory})
    return cache_key, directory


__all__ = [
    "comparison_context_cache_key",
    "managed_data_studio_comparison_contexts_root",
    "prepare_managed_data_studio_comparison_context_dir",
]
