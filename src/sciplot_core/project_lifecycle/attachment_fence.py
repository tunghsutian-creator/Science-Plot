"""Atomic old-namespace refusal; original history survives the one directory swap."""
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterator

from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.project_session_lease import external_project_session
from sciplot_core.foundation.writer_lease import DirectoryWriterLease, exclusive_directory_lease
from sciplot_core.project_store.io import read_file
from .attachment_index import OWNER
from .errors import EngineError


@contextmanager
def transfer_lease(root: Path) -> Iterator[DirectoryWriterLease]:
    # This is the original writer's EX policy plus the shared stable parent
    # inode lease, not another semantic/native transaction journal.
    with external_project_session(root), exclusive_directory_lease(root.parent) as parent:
        yield parent
        parent.verify()


def _exchange(parent: int, original: str, prepared: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        rename = library.renameatx_np
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
    else:
        raise EngineError("semantic_attachment_fence_unavailable", "Atomic namespace exchange is unavailable on this platform.")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(original), parent, os.fsencode(prepared), 2):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), original)


def refusal(marker: dict[str, Any], original_head_sha256: str) -> dict[str, Any]:
    return {"kind": "sciplot_attached_semantic_redirect", "version": 1,
            "project_id": marker["project_id"], "attachment_id": marker["attachment_id"],
            "original_head_sha256": original_head_sha256}


def control_json(path: Path) -> dict[str, Any] | None:
    try:
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            data, _mode = read_file(descriptor, path.name)
        finally:
            os.close(descriptor)
        value = json.loads(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def is_fenced(root: Path, marker: dict[str, Any], original_head_sha256: str) -> bool:
    return control_json(root / "head.json") == refusal(marker, original_head_sha256)


def prepare_shell(root: Path, marker: dict[str, Any], original_head_sha256: str) -> dict[str, Any]:
    # An interrupted shell preparation has no old/current semantic head. Its
    # random private name is never discovered or cleaned by another transfer.
    backup = Path(tempfile.mkdtemp(prefix=".sciplot_semantic_history_", dir=root.parent))
    result = {**marker, "history_root": str(backup)}
    atomic_write_json(backup / OWNER, {**result, "role": "redirect"})
    atomic_write_json(backup / "head.json", refusal(result, original_head_sha256))
    descriptor = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return result


def fence(root: Path, marker: dict[str, Any], *, original_head_sha256: str,
          verify_original: Any, parent: DirectoryWriterLease) -> None:
    """Caller holds the old EX lease; no crash point leaves an absent old root."""
    backup = Path(marker["history_root"])
    if backup.parent != root.parent or backup == root:
        raise EngineError("semantic_attachment_owner_conflict", "The registered history location is not this exact namespace transfer.")
    if is_fenced(root, marker, original_head_sha256):
        if (control_json(root / OWNER) != {**marker, "role": "redirect"}
                or control_json(backup / OWNER) != {**marker, "role": "history"}):
            raise EngineError("semantic_attachment_owner_conflict", "The original alias and history fences differ from their sealed transfer.")
        verify_original(backup)
        return
    expected_shell = {**marker, "role": "redirect"}
    if backup.exists():
        if (backup.is_symlink() or control_json(backup / OWNER) != expected_shell
                or not is_fenced(backup, marker, original_head_sha256)
                or {item.name for item in backup.iterdir()} != {OWNER, "head.json"}):
            raise EngineError("semantic_attachment_history_conflict", "The exact history destination is occupied by unrelated state.")
    else:
        raise EngineError("semantic_attachment_history_conflict", "The staged refusal shell is missing; preserve the original namespace.")
    # A marker in the original inode also fences the registered historical
    # backup for all new readers/writers after the exchange.
    atomic_write_json(root / OWNER, {**marker, "role": "history"})
    verify_original(root)
    parent.verify()
    descriptor = parent.fd
    if descriptor is None:
        raise EngineError("semantic_attachment_fence_unavailable", "The transfer parent lease is closed.")
    original_fd = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
    prepared_fd = os.open(backup.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
    try:
        original = os.stat(root.name, dir_fd=descriptor, follow_symlinks=False)
        prepared = os.stat(backup.name, dir_fd=descriptor, follow_symlinks=False)
        if (original.st_ino, original.st_dev) == (prepared.st_ino, prepared.st_dev):
            raise EngineError("semantic_attachment_history_conflict", "The original and refusal shell must be distinct directory inodes.")
        verify_original(root)
        if (os.fstat(original_fd).st_ino, os.fstat(original_fd).st_dev) != (original.st_ino, original.st_dev):
            raise EngineError("semantic_attachment_import_changed", "The original namespace directory identity changed before exchange.")
        if (os.fstat(prepared_fd).st_ino, os.fstat(prepared_fd).st_dev) != (prepared.st_ino, prepared.st_dev):
            raise EngineError("semantic_attachment_history_conflict", "The refusal shell directory identity changed before exchange.")
        _exchange(descriptor, root.name, backup.name)
        os.fsync(descriptor)
    finally:
        os.close(original_fd)
        os.close(prepared_fd)
    parent.verify()
    if not is_fenced(root, marker, original_head_sha256):
        raise EngineError("semantic_attachment_owner_conflict", "The atomic old namespace refusal could not be verified.")
    verify_original(backup)
