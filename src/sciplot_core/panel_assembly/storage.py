"""CAS layout persistence under a nonblocking kernel directory writer lease.

The permanent v2 fence only excludes older O_EXCL writers. It never owns the
lease, so a terminated v2 writer needs no lock-file reclamation. Unknown older
markers cannot prove an inactive owner and require explicit recovery or Save As.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any

from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.writer_lease import (
    DirectoryWriterLease,
    WriterLeaseBusy,
    WriterLeaseChanged,
    exclusive_directory_lease,
)

from .document import _AssemblyDocument, validate_document
from .errors import AssemblyError


@dataclass(frozen=True)
class _Snapshot:
    identity: tuple[int, ...]
    digest: str


_OBSERVED: dict[tuple[Path, str], _Snapshot] = {}
# A permanent compatibility fence, never the owner of a v2 writer lease.
# Atomic publication makes every crash state either absent or this exact value.
_LEASE_FENCE = b"SciPlot panel writer lease v2: kernel directory flock\n"


def _session_key(target: Path, document: dict[str, Any]) -> tuple[Path, str] | None:
    return (target, document._session_token) if isinstance(document, _AssemblyDocument) else None


def _identity(stat: os.stat_result) -> tuple[int, ...]:
    return (stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _target(path: Path) -> Path:
    result = path.expanduser().absolute()
    if result.is_symlink():
        raise AssemblyError("assembly_file_conflict", "Layout files cannot be symbolic links.")
    return result.parent.resolve() / result.name


def _read(path: Path) -> tuple[dict[str, Any], _Snapshot]:
    try:
        before = path.lstat()
        if not path.is_file() or path.is_symlink():
            raise AssemblyError("assembly_file_conflict", "The layout path must be an ordinary file.")
        payload = path.read_bytes()
        after = path.lstat()
        if _identity(before) != _identity(after):
            raise AssemblyError("assembly_file_conflict", "The layout changed while being read.")
        document = validate_document(json.loads(payload))
        return document, _Snapshot(_identity(after), hashlib.sha256(payload).hexdigest())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssemblyError("assembly_file_invalid", "The layout file could not be read as a valid document.") from exc


def load(path: Path) -> dict[str, Any]:
    target = _target(path)
    document, snapshot = _read(target)
    key = _session_key(target, document)
    assert key is not None
    _OBSERVED[key] = snapshot
    return document


def _check_existing(target: Path, document: dict[str, Any], expected_revision: int | None) -> _Snapshot | None:
    if not target.exists():
        if expected_revision is not None:
            raise AssemblyError("assembly_file_conflict", "The expected layout file is missing.")
        return None
    if expected_revision is None:
        raise AssemblyError("assembly_file_conflict", "Replacing a layout requires its expected saved revision.")
    key = _session_key(target, document)
    if key is None or key not in _OBSERVED:
        raise AssemblyError("assembly_file_conflict", "Reopen the layout to bind this editing session before saving.")
    current, snapshot = _read(target)
    if current["revision"] != expected_revision or _OBSERVED[key] != snapshot:
        raise AssemblyError("assembly_file_conflict", "The saved layout changed; reopen it before saving.")
    if document["revision"] <= current["revision"] and document != current:
        raise AssemblyError("assembly_file_conflict", "A changed layout must advance the saved revision.")
    return snapshot


def _fence_snapshot(lease: DirectoryWriterLease, name: str) -> _Snapshot:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=lease.fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise AssemblyError("assembly_file_conflict", "The layout's compatibility fence is not an ordinary file.") from exc
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise AssemblyError("assembly_file_conflict", "The layout's compatibility fence is not an ordinary file.")
        payload = handle.read(len(_LEASE_FENCE) + 1)
        after = os.fstat(handle.fileno())
    if payload != _LEASE_FENCE:
        raise AssemblyError(
            "assembly_file_busy",
            "An unrecognized legacy save lock exists. Its owner cannot be proven inactive. "
            "Close older SciPlot writers and recover the lock explicitly, or use Save As; "
            "the existing layout has not been changed.",
        )
    current = os.stat(name, dir_fd=lease.fd, follow_symlinks=False)
    if _identity(before) != _identity(after) or _identity(after) != _identity(current):
        raise AssemblyError("assembly_file_conflict", "The layout's compatibility fence changed.")
    return _Snapshot(_identity(after), hashlib.sha256(payload).hexdigest())


@contextmanager
def _save_stage(lease: DirectoryWriterLease, target: Path) -> Iterator[tuple[Path, int]]:
    """Keep cleanup and publication attached to the directory we actually own."""
    name = f".{target.name}.assembly-{secrets.token_hex(16)}"
    os.mkdir(name, mode=0o700, dir_fd=lease.fd)
    descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=lease.fd)
    opened = os.fstat(descriptor)
    try:
        yield target.parent / name, descriptor
    finally:
        try:
            os.unlink("document.json", dir_fd=descriptor)
        except FileNotFoundError:
            pass
        os.close(descriptor)
        try:
            current = os.stat(name, dir_fd=lease.fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
                os.rmdir(name, dir_fd=lease.fd)
        except FileNotFoundError:
            pass


def _ensure_fence(lease: DirectoryWriterLease, target: Path, name: str) -> _Snapshot:
    try:
        return _fence_snapshot(lease, name)
    except FileNotFoundError:
        pass
    # Stage complete bytes before the exclusive link. An old writer can win
    # this race, in which case its unknown marker is preserved and refused.
    with _save_stage(lease, target) as (stage, stage_fd):
        descriptor = os.open("document.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                             0o600, dir_fd=stage_fd)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_LEASE_FENCE)
            handle.flush()
            os.fsync(handle.fileno())
        lease.verify()
        try:
            os.link("document.json", name, src_dir_fd=stage_fd, dst_dir_fd=lease.fd,
                    follow_symlinks=False)
        except FileExistsError:
            pass
    return _fence_snapshot(lease, name)


def save(document: dict[str, Any], path: Path, *, expected_revision: int | None) -> Path:
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise AssemblyError("assembly_invalid", "An expected revision must be a nonnegative integer.")
    target = _target(path)
    fence_name = f".{target.name}.assembly-lock"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_directory_lease(target.parent) as lease:
            fence = _ensure_fence(lease, target, fence_name)
            before = _check_existing(target, document, expected_revision)
            with _save_stage(lease, target) as (stage, stage_fd):
                staged = atomic_write_json(stage / "document.json", document)
                lease.verify()
                stage_stat = os.stat(stage.name, dir_fd=lease.fd, follow_symlinks=False)
                if (stage_stat.st_dev, stage_stat.st_ino) != (os.fstat(stage_fd).st_dev, os.fstat(stage_fd).st_ino):
                    raise AssemblyError("assembly_file_conflict", "The layout save stage changed.")
                try:
                    current_fence = _fence_snapshot(lease, fence_name)
                except FileNotFoundError as exc:
                    raise AssemblyError("assembly_file_conflict", "The layout's compatibility fence disappeared.") from exc
                if current_fence != fence:
                    raise AssemblyError("assembly_file_conflict", "The layout's compatibility fence changed.")
                if before is None:
                    # Exclusive link never replaces a destination created meanwhile.
                    try:
                        os.link(staged.name, target.name, src_dir_fd=stage_fd,
                                dst_dir_fd=lease.fd, follow_symlinks=False)
                    except FileExistsError as exc:
                        raise AssemblyError("assembly_file_conflict", "A layout appeared at the new save destination.") from exc
                else:
                    _current, current_snapshot = _read(target)
                    if current_snapshot != before:
                        raise AssemblyError("assembly_file_conflict", "The layout changed while the save was prepared.")
                    lease.verify()
                    os.replace(staged.name, target.name, src_dir_fd=stage_fd, dst_dir_fd=lease.fd)
            lease.verify()
            _current, snapshot = _read(target)
            lease.verify()
            key = _session_key(target, document)
            if key is not None:
                _OBSERVED[key] = snapshot
            return target
    except WriterLeaseBusy as exc:
        raise AssemblyError("assembly_file_busy", "Another writer holds this directory's save lease.") from exc
    except WriterLeaseChanged as exc:
        raise AssemblyError("assembly_file_conflict", "The layout's parent directory changed during save.") from exc
    except OSError as exc:
        raise AssemblyError("assembly_file_write", "The layout save could not complete.") from exc
