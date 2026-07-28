"""Capture and verify race-safe terminal file snapshots."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_hashing import canonical_json_sha256


def _canonical_sha256(value: object) -> str:
    return canonical_json_sha256(value, allow_nan=False)


def _stat_identity(value: os.stat_result) -> dict[str, int]:
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "mode": int(value.st_mode),
        "links": int(value.st_nlink),
        "size": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _stable_file_snapshot(path: Path, *, label: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(resolved, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{label} is not a regular file: {resolved}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    path_after = os.stat(resolved, follow_symlinks=False)
    identity = _stat_identity(before)
    if _stat_identity(after) != identity or _stat_identity(path_after) != identity:
        raise ValueError(f"{label} changed while it was captured: {resolved}")
    payload = b"".join(chunks)
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != identity["size"]:
        raise ValueError(f"{label} size changed while it was captured: {resolved}")
    return {
        "path": resolved,
        "identity": identity,
        "bytes": payload,
        "sha256": digest,
    }


def _assert_snapshot_current(snapshot: dict[str, Any], *, label: str) -> None:
    current = _stable_file_snapshot(Path(snapshot["path"]), label=label)
    if (
        current["identity"] != snapshot["identity"]
        or current["sha256"] != snapshot["sha256"]
    ):
        raise ValueError(f"{label} changed during exact-current audit.")


def _write_private_snapshot(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o400,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
