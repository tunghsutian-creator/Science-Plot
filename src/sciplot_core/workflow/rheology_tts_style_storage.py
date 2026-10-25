"""Bound file snapshots and reversible publication for rheology presentation edits."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.source_update_commit import reject_symlink_path


def snapshot(paths: list[Path]) -> dict[str, str]:
    result = {}
    for path in paths:
        reject_symlink_path(path)
        result[str(path.resolve())] = file_sha256(path)
    return result


def check_snapshot(files: dict[str, str], *, label: str) -> None:
    for name, digest in files.items():
        path = Path(name)
        reject_symlink_path(path)
        if not path.is_file() or file_sha256(path) != digest:
            raise ValueError(f"Stale {label}: {path}; inspect a new style preview.")



def publish_files(updates: list[tuple[Path, Path]], backup: Path, *,
                  expected: dict[str, str], candidates: dict[str, str],
                  allowed_roots: tuple[Path, ...]) -> dict[str, str]:
    """Retired compatibility symbol; active writes belong to ProjectCommands."""
    raise RuntimeError("Direct suite publication is retired; submit a complete ProjectMutation through ProjectCommands.")
