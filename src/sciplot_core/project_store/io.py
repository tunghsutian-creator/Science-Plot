"""Descriptor-bound store IO, immutable blobs, and trusted resource roots."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.json_io import write_json_object
from sciplot_core.foundation.writer_lease import exclusive_directory_lease
from sciplot_core.foundation.project_session_lease import external_project_session

from .errors import ProjectConflict, ProjectRecoveryRequired, ProjectStoreError

STORE = ".sciplot_store"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def parts(value: str) -> tuple[str, ...]:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or "\\" in value or any(item in {"", ".", ".."} for item in value.split("/"))
            or value == STORE or value.startswith(STORE + "/")):
        raise ProjectStoreError("Expected a confined project-relative file name.")
    return path.parts


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_file(fd: int, name: str) -> tuple[bytes, int]:
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(opened, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ProjectStoreError("Project members must be ordinary files.")
        data = handle.read()
        after = os.fstat(handle.fileno())
    current = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if _identity(before) != _identity(after) or _identity(after) != _identity(current):
        raise ProjectConflict("A project member changed while being captured.")
    return data, stat.S_IMODE(after.st_mode)


@contextmanager
def directory(fd: int, components: tuple[str, ...], *, create: bool = False) -> Iterator[int]:
    current = os.dup(fd)
    try:
        for name in components:
            if create:
                try:
                    os.mkdir(name, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
            following = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = following
        yield current
    finally:
        os.close(current)


def install(fd: int, name: str, data: bytes, *, mode: int = 0o600, exclusive: bool = False) -> None:
    temporary = ".sciplot-write-" + uuid4().hex
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                         mode, dir_fd=fd)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive:
            os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        else:
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


class StoreIO:
    def __init__(self, root: Path, locations: Mapping[str, Path]) -> None:
        self.root = root
        self.locations = dict(locations)
        self.root_fds: dict[str, int] = {}
        self.fd = -1

    @contextmanager
    def locked(self) -> Iterator[StoreIO]:
        with external_project_session(self.root), exclusive_directory_lease(self.root) as lease:
            try:
                self.root_fds[""] = os.dup(lease.fd)
                for key, path in self.locations.items():
                    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key):
                        raise ProjectStoreError("Invalid trusted resource-root ID.")
                    self.root_fds[key] = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                with directory(lease.fd, (STORE,), create=True) as store_fd:
                    self.fd = store_fd
                    yield self
                    self.verify_roots()
                    lease.verify()
            finally:
                for descriptor in self.root_fds.values():
                    os.close(descriptor)
                self.root_fds.clear()
                self.fd = -1

    def verify_roots(self) -> None:
        for key, fd in self.root_fds.items():
            path = self.locations[key] if key else self.root
            current, opened = path.lstat(), os.fstat(fd)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise ProjectRecoveryRequired("A trusted resource root changed its directory identity.")

    def split(self, logical: str) -> tuple[int, tuple[str, ...]]:
        components = parts(logical)
        key = components[0][1:] if components[0].startswith("@") else ""
        if key:
            components = components[1:]
        if not components or key not in self.root_fds:
            raise ProjectRecoveryRequired("The project needs its explicitly trusted resource-root mapping.")
        return self.root_fds[key], components

    def physical(self, logical: str) -> tuple[bytes, int] | None:
        fd, components = self.split(logical)
        try:
            with directory(fd, components[:-1]) as parent:
                return read_file(parent, components[-1])
        except FileNotFoundError:
            return None

    def read(self, name: str) -> dict[str, Any] | None:
        components = parts(name)
        try:
            with directory(self.fd, components[:-1]) as parent:
                data, _mode = read_file(parent, components[-1])
        except FileNotFoundError:
            return None
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ProjectStoreError("Project store metadata must be an object.")
        return payload

    def write(self, name: str, payload: dict[str, Any], *, exclusive: bool = False) -> None:
        components = parts(name)
        with directory(self.fd, components[:-1], create=True) as parent:
            temporary = ".sciplot-json-" + uuid4().hex
            opened = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
            try:
                with os.fdopen(opened, "w", encoding="utf-8") as handle:
                    write_json_object(handle, payload)
                if exclusive:
                    os.link(temporary, components[-1], src_dir_fd=parent, dst_dir_fd=parent,
                            follow_symlinks=False)
                else:
                    os.replace(temporary, components[-1], src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def put(self, data: bytes) -> dict[str, Any]:
        key = sha(data)
        with directory(self.fd, ("objects", key[:2]), create=True) as parent:
            try:
                install(parent, key, data, exclusive=True)
            except FileExistsError:
                current, _mode = read_file(parent, key)
                if current != data:
                    raise ProjectConflict("An immutable project object has conflicting bytes.") from None
        return {"sha256": key, "size": len(data)}

    def get(self, entry: Mapping[str, Any]) -> bytes:
        key = entry["sha256"]
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ProjectStoreError("Invalid project content identity.")
        with directory(self.fd, ("objects", key[:2])) as parent:
            data, _mode = read_file(parent, key)
        if sha(data) != key or len(data) != entry["size"]:
            raise ProjectConflict("An immutable project object no longer matches its identity.")
        return data

    def scan(self) -> dict[str, dict[str, Any]]:
        files: dict[str, dict[str, Any]] = {}

        def walk(fd: int, prefix: str) -> None:
            for name in sorted(os.listdir(fd)):
                if name == STORE or name.startswith(".sciplot-write-"):
                    continue
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                logical = prefix + name
                if stat.S_ISDIR(info.st_mode):
                    with directory(fd, (name,)) as child:
                        walk(child, logical + "/")
                elif stat.S_ISREG(info.st_mode):
                    data, mode = read_file(fd, name)
                    files[logical] = {**self.put(data), "mode": mode}
                else:
                    raise ProjectStoreError("Portable project import refuses symlink or special members.")

        for key, fd in self.root_fds.items():
            walk(fd, f"@{key}/" if key else "")
        return files
