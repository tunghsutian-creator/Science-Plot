"""Two structural directory resources private to one complete head read.

These descriptors attest no bytes, graph or permission. Unprovable metadata or
permission checks discard every held descriptor and use the original opener.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from threading import get_ident
from typing import Protocol

from sciplot_core.foundation.descriptor_names import descriptor_name

from .errors import ProjectConflict

DirectoryOpener = Callable[[int, tuple[str, ...]], AbstractContextManager[int]]
FileReader = Callable[[int, str], tuple[bytes, int]]


class ReadIO(Protocol):
    root: Path
    fd: int
    lease_epoch: int
    validation_epoch: int
    root_fds: dict[str, int]
    locations: dict[str, Path]
    location_members: dict[str, tuple[str, ...] | None]
    namespace_backups: dict[str, Path]
    _read_directories: DirectoryReads | None

    def verify_roots(self) -> dict[str, tuple[os.stat_result, os.stat_result]]: ...


class _Unprovable(Exception):
    """Only the original fresh open may decide this request."""


class _Changed(Exception):
    """A positively observed scope or namespace change cannot be refreshed."""


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_ctime_ns)


def _credentials() -> tuple[int, int, int, int, tuple[int, ...]]:
    return os.getuid(), os.geteuid(), os.getgid(), os.getegid(), tuple(os.getgroups())


def _permission(parent: int, name: str) -> bool:
    return os.access(name, os.R_OK, dir_fd=parent, effective_ids=True, follow_symlinks=False)


@dataclass(frozen=True)
class _Held:
    fd: int
    identity: tuple[int, ...]


class DirectoryReads:
    def __init__(self, io: ReadIO, store_name: str) -> None:
        self.io, self.store_name = io, store_name
        self.binding = (io.fd, io.lease_epoch, io.validation_epoch, io.root, dict(io.root_fds),
                        dict(io.locations), dict(io.location_members), dict(io.namespace_backups),
                        os.getpid(), get_ident(), _credentials())
        self.held: dict[str, _Held] = {}
        self.failed = False
        self.reusable = all(os.access in support for support in (
            os.supports_dir_fd, os.supports_effective_ids, os.supports_follow_symlinks))
        self.root_identity: tuple[int, ...] | None = None
        self.store_identity: tuple[int, ...] | None = None
        self.root_name: str | None = None

    def close(self) -> None:
        held, self.held = self.held, {}
        for item in held.values():
            try:
                os.close(item.fd)
            except OSError:
                pass

    def invalidate(self) -> None:
        self.failed = True
        self.close()

    def disable(self) -> None:
        self.reusable = False
        self.close()

    def _scope(self) -> None:
        io = self.io
        current = (io.fd, io.lease_epoch, io.validation_epoch, io.root, dict(io.root_fds),
                   dict(io.locations), dict(io.location_members), dict(io.namespace_backups),
                   os.getpid(), get_ident(), _credentials())
        if self.failed or io.fd < 0 or current != self.binding:
            raise ProjectConflict("Directory reads cannot cross their IO, lease, mutation, owner or capability boundary.")

    def _anchors(self) -> None:
        self._scope()
        io = self.io
        try:
            named_root, root = io.verify_roots()[""]
            name = descriptor_name(io.root_fds[""])
            current = Path(name)
            if not current.is_absolute() or str(current) != name or name.endswith(" (deleted)"):
                raise _Unprovable
            # A canonical path can retain the caller's case on a
            # case-insensitive filesystem while the kernel reports disk case.
            # Prove the original no-alias rule once, then observe the same
            # live kernel name afresh. A changed name re-enters that rule;
            # it is not by itself identity or permission authority.
            if (self.root_name is None or name != self.root_name) and io.root.resolve(strict=True) != io.root:
                raise _Changed("The current project namespace acquired an ancestor alias.")
            store = os.fstat(io.fd)
            named_store = os.stat(self.store_name, dir_fd=io.root_fds[""], follow_symlinks=False)
        except (OSError, RuntimeError) as exc:
            raise _Unprovable from exc
        if (not all(stat.S_ISDIR(item.st_mode) for item in (root, named_root, store, named_store))
                or _identity(root) != _identity(named_root) or _identity(store) != _identity(named_store)):
            raise _Changed("The named project/store directory differs from its held descriptor.")
        if self.root_identity is None:
            self.root_identity, self.store_identity = _identity(root), _identity(store)
            self.root_name = name
        elif self.root_identity != _identity(root) or self.store_identity != _identity(store):
            raise _Changed("The project/store directory identity or permissions changed during validation.")

    def _named(self, name: str, held: _Held) -> None:
        self._anchors()
        try:
            before = os.stat(name, dir_fd=self.io.fd, follow_symlinks=False)
            opened = os.fstat(held.fd)
            allowed = _permission(self.io.fd, name)
            after = os.stat(name, dir_fd=self.io.fd, follow_symlinks=False)
            final = os.fstat(held.fd)
        except (OSError, NotImplementedError) as exc:
            raise _Unprovable from exc
        if not allowed:
            raise _Unprovable
        if (not all(stat.S_ISDIR(item.st_mode) for item in (before, opened, after, final))
                or any(_identity(item) != held.identity for item in (before, opened, after, final))):
            raise _Changed("A structural directory changed its name, identity, ownership or permissions.")

    def parent(self, name: str) -> int:
        held = self.held.get(name)
        if held is None:
            self._anchors()
            # This original O_RDONLY/no-follow open supplies the first use's
            # kernel permission check; future uses must re-prove it afresh.
            descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.io.fd)
            try:
                held = _Held(descriptor, _identity(os.fstat(descriptor)))
                self._named(name, held)
            except BaseException:
                os.close(descriptor)
                raise
            self.held[name] = held
        else:
            self._named(name, held)
        return held.fd

    def finish(self) -> None:
        self._scope()
        if self.reusable:
            try:
                for name, held in self.held.items():
                    self._named(name, held)
            except _Unprovable:
                self.disable()


@contextmanager
def reading_directories(io: ReadIO, store_name: str) -> Iterator[None]:
    previous = io._read_directories
    resources = DirectoryReads(io, store_name)
    io._read_directories = resources
    try:
        yield
        resources.finish()
    except _Changed as exc:
        if previous is not None:
            previous.invalidate()
        raise ProjectConflict(str(exc)) from exc
    except BaseException:
        if previous is not None:
            previous.invalidate()
        raise
    finally:
        resources.invalidate()
        io._read_directories = previous


def read_stored_file(io: ReadIO, components: tuple[str, ...], reader: FileReader,
                     directory: DirectoryOpener) -> tuple[bytes, int]:
    resources = io._read_directories
    parents, name = components[:-1], components[-1]
    if resources is not None:
        try:
            resources._scope()
            if resources.io is not io:
                raise ProjectConflict("Directory resources belong to another IO.")
            if resources.reusable and parents and parents[0] in {"objects", "generations"}:
                first = parents[0]
                parent = resources.parent(first)
                with directory(parent, parents[1:]) as descriptor:
                    value = reader(descriptor, name)
                resources._named(first, resources.held[first])
                return value
        except _Unprovable:
            # In particular, metadata-denied/access-allowed/open-allowed must
            # retain the original fresh-open result, not become missing/denied.
            resources.disable()
        except _Changed as exc:
            resources.invalidate()
            # Preserve the OS errno when the original fresh opener also refuses.
            with directory(io.fd, parents):
                pass
            raise ProjectConflict(str(exc)) from exc
        except BaseException:
            resources.invalidate()
            raise
    with directory(io.fd, parents) as descriptor:
        return reader(descriptor, name)
