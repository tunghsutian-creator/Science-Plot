"""Private, owner-bound socket paths and lifecycle locks."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from typing import Any, Iterator


class TransportError(ValueError):
    def __init__(self, reason_code: str, message: str, *, repair: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.repair = repair


def default_socket() -> Path:
    configured = os.environ.get("SCIPLOT_ENGINE_SOCKET")
    if configured:
        return Path(configured).expanduser().absolute()
    checkout = hashlib.sha256(str(Path(__file__).resolve().parents[2]).encode()).hexdigest()[:6]
    return Path(tempfile.gettempdir()) / f"sp-{os.getuid()}-{checkout}-{runtime_fingerprint()[:10]}" / "engine.sock"


@lru_cache(maxsize=1)
def runtime_fingerprint() -> str:
    """Bind a daemon to one immutable code build; never hot-reload running work."""
    package = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    files = sorted(path for path in package.rglob("*") if path.is_file()
                   and not any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(package).parts)
                   and path.suffix not in {".pyc", ".pyo"})
    for path in files:
        digest.update(str(path.relative_to(package)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    configuration = package.parents[1] / "pyproject.toml"
    if configuration.is_file():
        digest.update(configuration.read_bytes())
    digest.update(str(Path(sys.executable).resolve()).encode())
    return digest.hexdigest()


def prepare_socket(path: Path | None) -> Path:
    result = (path if path is not None else default_socket()).expanduser().absolute()
    if len(os.fsencode(result)) > 100:
        raise TransportError("socket_path_too_long", "Use a shorter local socket path (at most 100 UTF-8 bytes).")
    result.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = result.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise TransportError("unsafe_socket_directory", "The socket directory must be a private directory owned by this user (mode 0700).")
    return result


def owner_path(socket_path: Path) -> Path:
    return socket_path.with_name(socket_path.name + ".owner.json")


def _private_file(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise TransportError("unsafe_socket_owner", "Socket ownership evidence must be a private regular file owned by this user.")


def read_owner(socket_path: Path) -> dict[str, Any]:
    metadata = owner_path(socket_path)
    _private_file(metadata)
    value = json.loads(metadata.read_text(encoding="utf-8"))
    info = socket_path.lstat()
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
            or not isinstance(value, dict) or value.get("device") != info.st_dev
            or value.get("inode") != info.st_ino or not isinstance(value.get("pid"), int)
            or not isinstance(value.get("instance_id"), str)):
        raise TransportError("socket_owner_mismatch", "Socket identity does not match its recorded local server; no files were removed.")
    return value


def write_owner(socket_path: Path, instance_id: str) -> dict[str, Any]:
    info = socket_path.lstat()
    value = {"pid": os.getpid(), "instance_id": instance_id, "device": info.st_dev,
             "inode": info.st_ino, "protocol_version": 1}
    fd, temporary = tempfile.mkstemp(prefix=".owner-", dir=socket_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, owner_path(socket_path))
    finally:
        Path(temporary).unlink(missing_ok=True)
    return value


def remove_owned_socket(socket_path: Path, instance_id: str) -> None:
    try:
        owner = read_owner(socket_path)
    except FileNotFoundError:
        return
    if owner["instance_id"] != instance_id:
        raise TransportError("socket_owner_mismatch", "A different server owns the socket; it was preserved.")
    socket_path.unlink()
    owner_path(socket_path).unlink()


@contextmanager
def lifecycle_lock(socket_path: Path, name: str, *, timeout: float = 15.0) -> Iterator[None]:
    path = socket_path.with_name(socket_path.name + f".{name}.lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    locked = False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise TransportError("unsafe_socket_lock", "Engine lifecycle lock must be private and owned by this user.")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise TransportError("engine_busy", "Another local engine operation holds the lifecycle lock; retry this same request.") from exc
                time.sleep(0.05)
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
