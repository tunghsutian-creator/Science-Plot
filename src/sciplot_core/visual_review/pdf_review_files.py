"""Finite, no-follow IO for an explicitly selected mutable PDF review copy."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from hashlib import sha256
import os
from pathlib import Path
import stat
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.project_store.io import directory

MAX_PDF_BYTES = 32 * 1024 * 1024


@contextmanager
def _parent(path: Path) -> Iterator[int]:
    root = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with directory(root, path.parts[1:-1]) as parent:
            before = os.fstat(parent)
            yield parent
            with directory(root, path.parts[1:-1]) as current:
                after = os.fstat(current)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise ValueError("PDF review directory changed during IO.")
    finally:
        os.close(root)


def capture_pdf(path: Path, *, expected_sha256: str | None = None, review: bool = False) -> dict[str, Any]:
    path = canonical_path(path)
    with _parent(path) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_PDF_BYTES:
                raise ValueError("PDF review requires a regular PDF of at most 32 MiB.")
            if review and before.st_nlink != 1:
                raise ValueError("A mutable PDF review copy must not share a hard link.")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(MAX_PDF_BYTES + 1)
            after = os.fstat(fd)
            visible = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        finally:
            os.close(fd)
        def identity(s: os.stat_result) -> tuple[int, ...]:
            return (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after) or identity(before) != identity(visible) or len(data) != before.st_size:
            raise ValueError("PDF changed during review capture.")
    digest = sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("The original PDF export changed from its recorded version.")
    return {"bytes": data, "sha256": digest, "size_bytes": len(data)}


def write_review_copy(path: Path, data: bytes) -> None:
    """Never replace a user file; a failed subsequent registration leaves an unbound copy."""
    path = canonical_path(path)
    with _parent(path) as parent:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb", closefd=False) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent)
