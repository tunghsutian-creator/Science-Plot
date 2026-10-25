"""Descriptor-bound store IO, immutable blobs, and trusted resource roots."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from threading import get_ident
import time
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.json_io import write_json_object
from sciplot_core.foundation.writer_lease import DirectoryWriterLease, WriterLeaseBusy, exclusive_directory_lease
from sciplot_core.foundation.project_session_lease import ProjectSessionBusy, external_project_session

from .errors import ProjectConflict, ProjectRecoveryRequired, ProjectStoreError

STORE = ".sciplot_store"
_ACTIVE: ContextVar[tuple[StoreIO, int, int] | None] = ContextVar("project_store_owned_io", default=None)


def owned_io(root: Path) -> StoreIO | None:
    active = _ACTIVE.get()
    if active is None:
        return None
    io, process, thread = active
    if process != os.getpid() or thread != get_ident() or io.root != root or io.fd < 0:
        return None
    io.verify_roots()
    return io


@contextmanager
def _leases(root: Path, locations: Mapping[str, Path], *, blocking: bool) -> Iterator[dict[Path, DirectoryWriterLease]]:
    while True:
        stack = ExitStack()
        try:
            stack.enter_context(external_project_session(root))
            leases = {path: stack.enter_context(exclusive_directory_lease(path))
                      for path in sorted({root, *locations.values()}, key=str)}
            break
        except (ProjectSessionBusy, WriterLeaseBusy):
            stack.close()
            if not blocking:
                raise
            # Legacy manifest edit scopes retain their documented blocking
            # read-modify-write admission. No native work has been admitted.
            time.sleep(0.01)
        except BaseException:
            stack.close()
            raise
    try:
        yield leases
    finally:
        stack.close()


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


def member_names(fd: int, prefix: str = "", *, exclude: tuple[str, ...] = ()) -> set[str]:
    result = set()
    for name in os.listdir(fd):
        if name == STORE or not prefix and name in exclude:
            continue
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            with directory(fd, (name,)) as child:
                result.update(member_names(child, prefix + name + "/"))
        elif stat.S_ISREG(info.st_mode):
            result.add(prefix + name)
        else:
            raise ProjectConflict("The logical namespace has symbolic or special outside members.")
    return result


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_file(fd: int, name: str, *, owned: bool = False) -> tuple[bytes, int]:
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(opened, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ProjectStoreError("Project members must be ordinary files.")
        if owned and before.st_nlink != 1:
            raise ProjectConflict("A declared project resource is hard-linked outside its owned projection.")
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
    if type(mode) is not int or not 0 <= mode <= 0o777:
        raise ProjectStoreError("Project outputs require explicit ordinary permission bits.")
    temporary = ".sciplot-write-" + uuid4().hex
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                         mode, dir_fd=fd)
    try:
        os.fchmod(descriptor, mode)
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
    def __init__(self, root: Path, locations: Mapping[str, Path],
                 location_members: Mapping[str, tuple[str, ...] | None] | None = None,
                 namespace_backups: Mapping[str, Path] | None = None) -> None:
        self.root = root
        self.locations = dict(locations)
        self.location_members = {key: (location_members or {}).get(key) for key in locations}
        self.namespace_backups = dict(namespace_backups or {})
        self.root_fds: dict[str, int] = {}
        self.fd = -1

    @contextmanager
    def locked(self, *, blocking: bool = False) -> Iterator[StoreIO]:
        active = _ACTIVE.get()
        if active is not None:
            owned, process, thread = active
            if process == os.getpid() and thread == get_ident() and owned.root == self.root and owned.fd >= 0:
                if (owned.locations != self.locations or owned.location_members != self.location_members
                        or owned.namespace_backups != self.namespace_backups):
                    raise ProjectStoreError("An owned project transaction cannot expand its resource roots.")
                owned.verify_roots()
                yield owned
                return
            if process != os.getpid() or thread != get_ident():
                _ACTIVE.set(None)
        with _leases(self.root, self.locations, blocking=blocking) as leases:
            lease = leases[self.root]
            try:
                self.root_fds[""] = os.dup(lease.fd)
                for key, path in self.locations.items():
                    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key):
                        raise ProjectStoreError("Invalid trusted resource-root ID.")
                    self.root_fds[key] = os.dup(leases[path].fd)
                with directory(lease.fd, (STORE,), create=True) as store_fd:
                    self.fd = store_fd
                    token = _ACTIVE.set((self, os.getpid(), get_ident()))
                    try:
                        yield self
                        self.verify_roots()
                        for held in leases.values():
                            held.verify()
                    finally:
                        _ACTIVE.reset(token)
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
        elif components[0] == ".sciplot_resources":
            raise ProjectStoreError("Use the registered resource-root ID, not its private physical view alias.")
        if not components or key not in self.root_fds:
            raise ProjectRecoveryRequired("The project needs its explicitly trusted resource-root mapping.")
        permitted = self.location_members.get(key)
        if key and permitted is not None and "/".join(components) not in permitted:
            raise ProjectStoreError("The logical member is outside its exact trusted file capability.")
        return self.root_fds[key], components

    def physical(self, logical: str, *, owned: bool = True) -> tuple[bytes, int] | None:
        fd, components = self.split(logical)
        try:
            with directory(fd, components[:-1]) as parent:
                value = read_file(parent, components[-1], owned=owned)
                if owned and os.stat(components[-1], dir_fd=parent, follow_symlinks=False).st_nlink != 1:
                    raise ProjectConflict("A declared project resource is hard-linked outside its owned projection.")
                return value
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
                if not prefix and name == ".sciplot_resources":
                    if not any(path.is_relative_to(self.root / name) for path in self.locations.values()):
                        raise ProjectStoreError("An unregistered directory occupies the reserved resource-view namespace.")
                    continue
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                logical = prefix + name
                if stat.S_ISDIR(info.st_mode):
                    with directory(fd, (name,)) as child:
                        walk(child, logical + "/")
                elif stat.S_ISREG(info.st_mode):
                    data, mode = read_file(fd, name)
                    if not 0 <= mode <= 0o777:
                        raise ProjectStoreError("Legacy project import refuses special permission bits.")
                    files[logical] = {**self.put(data), "mode": mode}
                else:
                    raise ProjectStoreError("Portable project import refuses symlink or special members.")

        for key, fd in self.root_fds.items():
            permitted = self.location_members.get(key)
            if key and permitted is not None:
                for relative in permitted:
                    logical = f"@{key}/{relative}"
                    value = self.physical(logical)
                    if value is not None:
                        data, mode = value
                        files[logical] = {**self.put(data), "mode": mode}
            else:
                walk(fd, f"@{key}/" if key else "")
        return files
