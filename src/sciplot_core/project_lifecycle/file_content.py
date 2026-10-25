"""Filesystem-only immutable content IO, retaining atomic-create and full snapshots."""
from collections.abc import Callable
import os
from pathlib import Path
import tempfile
from typing import Any

from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot as _stable_file_snapshot
from .paths import canonical_path


def read_snapshot(path: Path) -> dict[str, Any]:
    canonical_path(path)
    return _stable_file_snapshot(path, label="Scientific content")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish(path: Path, payload: bytes, verify_existing: Callable[[], None]) -> None:
    canonical_path(path)
    if path.exists():
        verify_existing()
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".content-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic create-if-absent: never replace an existing (possibly corrupt)
        # blob, including a concurrent writer's already published identical one.
        try:
            os.link(temporary, path)
        except FileExistsError:
            verify_existing()
        temporary.unlink()
        temporary = None
        _fsync_directory(path.parent)
        _fsync_directory(path.parent.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
