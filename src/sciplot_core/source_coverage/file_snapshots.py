"""Capture and verify race-safe terminal file snapshots."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_locations import source_file_paths
from sciplot_core.project_store.io import directory


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


def stable_file_snapshot(path: Path, *, label: str, expected_sha256: str | None = None) -> dict[str, Any]:
    """Capture exact bytes and file identity, rejecting concurrent source changes."""
    if expected_sha256 is not None and (len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)):
        raise ValueError(f"{label} requires an exact SHA256 source version.")
    literal, resolved = source_file_paths(path, expected_sha256=expected_sha256)
    return _physical_file_snapshot(resolved.expanduser().resolve(), literal=Path(literal),
                                   label=label, expected_sha256=expected_sha256)


def _physical_file_snapshot(path: Path, *, literal: Path, label: str,
                            expected_sha256: str | None = None) -> dict[str, Any]:
    """Capture one already role-resolved file through its exact directory FDs."""
    resolved = path.expanduser().absolute()
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    root = os.open(resolved.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with directory(root, resolved.parts[1:-1]) as parent:
            parent_identity = os.fstat(parent)
            descriptor = os.open(resolved.name, flags, dir_fd=parent)
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
            path_after = os.stat(resolved.name, dir_fd=parent, follow_symlinks=False)
            with directory(root, resolved.parts[1:-1]) as current_parent:
                current_identity = os.fstat(current_parent)
            if (parent_identity.st_dev, parent_identity.st_ino) != (current_identity.st_dev, current_identity.st_ino):
                raise ValueError(f"{label} parent changed while it was captured: {resolved}")
    finally:
        os.close(root)
    identity = _stat_identity(before)
    if _stat_identity(after) != identity or _stat_identity(path_after) != identity:
        raise ValueError(f"{label} changed while it was captured: {resolved}")
    payload = b"".join(chunks)
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != identity["size"]:
        raise ValueError(f"{label} size changed while it was captured: {resolved}")
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError(f"{label} changed from its exact expected source version: {literal}")
    return {
        "path": literal,
        "identity": identity,
        "bytes": payload,
        "sha256": digest,
    }


# Preserve the historical snapshot-current monkeypatch seam.
_stable_file_snapshot = stable_file_snapshot


def _assert_snapshot_current(snapshot: dict[str, Any], *, label: str, expected_sha256: str | None = None) -> None:
    if expected_sha256 is None:
        current = _stable_file_snapshot(Path(snapshot["path"]), label=label)
    else:
        current = _stable_file_snapshot(Path(snapshot["path"]), label=label, expected_sha256=expected_sha256)
    _require_snapshot_identity(snapshot, current, label=label)


def _require_snapshot_identity(snapshot: dict[str, Any], current: dict[str, Any], *, label: str) -> None:
    # Cloud providers can update extended attributes (and thus ctime) without
    # changing the file, its modification time or its contents. Each capture
    # remains race checked; accept ctime-only drift only after a fresh full hash.
    changed = [
        key
        for key, value in current["identity"].items()
        if key != "ctime_ns" and snapshot["identity"].get(key) != value
    ]
    if changed or current["sha256"] != snapshot["sha256"]:
        raise ValueError(
            f"{label} changed during exact-current audit; metadata={changed}, bytes_changed={current['sha256'] != snapshot['sha256']}."
        )


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
