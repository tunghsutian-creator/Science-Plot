"""Atomic layout persistence with file identity checks and a nonblocking writer lease."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from sciplot_core.foundation.json_io import atomic_write_json

from .errors import AssemblyError


@dataclass(frozen=True)
class _Snapshot:
    identity: tuple[int, ...]
    digest: str


_OBSERVED: dict[tuple[Path, str], _Snapshot] = {}


def _session_key(target: Path, document: dict[str, Any]) -> tuple[Path, str] | None:
    from .model import _AssemblyDocument

    return (target, document._session_token) if isinstance(document, _AssemblyDocument) else None


def _identity(stat: os.stat_result) -> tuple[int, ...]:
    return (stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _target(path: Path) -> Path:
    result = path.expanduser().absolute()
    if result.is_symlink():
        raise AssemblyError("assembly_file_conflict", "Layout files cannot be symbolic links.")
    return result


def _read(path: Path) -> tuple[dict[str, Any], _Snapshot]:
    from .model import validate_document

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


def save(document: dict[str, Any], path: Path, *, expected_revision: int | None) -> Path:
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise AssemblyError("assembly_invalid", "An expected revision must be a nonnegative integer.")
    target = _target(path)
    lock = target.with_name(f".{target.name}.assembly-lock")
    descriptor: int | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise AssemblyError("assembly_file_busy", "Another writer holds this layout's save lease.") from exc
        before = _check_existing(target, document, expected_revision)
        with tempfile.TemporaryDirectory(prefix=f".{target.name}.assembly-", dir=target.parent) as stage:
            staged = atomic_write_json(Path(stage) / "document.json", document)
            if before is None:
                # A new document is installed without replacing any path created meanwhile.
                try:
                    os.link(staged, target)
                except FileExistsError as exc:
                    raise AssemblyError("assembly_file_conflict", "A layout appeared at the new save destination.") from exc
            else:
                _current, current_snapshot = _read(target)
                if current_snapshot != before:
                    raise AssemblyError("assembly_file_conflict", "The layout changed while the save was prepared.")
                os.replace(staged, target)
        _current, snapshot = _read(target)
        key = _session_key(target, document)
        if key is not None:
            _OBSERVED[key] = snapshot
        return target
    except OSError as exc:
        raise AssemblyError("assembly_file_write", "The layout save could not complete.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
            lock.unlink(missing_ok=True)
