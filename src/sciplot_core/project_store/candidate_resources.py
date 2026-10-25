"""Private projections of the host's existing finite resource capabilities."""
from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import stat
from typing import Any

from .errors import ProjectConflict, ProjectStoreError
from .io import STORE, directory, install, member_names, parts, read_file, sha
from .repository import FileProjectStore


def _identity(info: os.stat_result) -> dict[str, int]:
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ProjectConflict("A resource view requires a private host-owned directory.")
    return {"device": info.st_dev, "inode": info.st_ino}


def _no_store(fd: int) -> None:
    try:
        os.stat(STORE, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ProjectConflict("A private resource view cannot contain a second store.")


def validate_resources_binding(value: Any) -> None:
    if (not isinstance(value, dict) or set(value) != {"root", "device", "inode", "views"}
            or not isinstance(value["root"], str) or not Path(value["root"]).is_absolute()
            or any(type(value[key]) is not int or value[key] < 0 for key in ("device", "inode"))
            or not isinstance(value["views"], dict)):
        raise ProjectStoreError("Invalid closed private resource-view binding.")
    for view in value["views"].values():
        if (not isinstance(view, dict) or set(view) != {"device", "inode"}
                or any(type(view[key]) is not int or view[key] < 0 for key in view)):
            raise ProjectStoreError("Invalid closed private resource directory identity.")


class CandidateResources:
    def __init__(self, store: FileProjectStore, snapshot: dict[str, Any], root: Path,
                 primary: Path, *, bound: dict[str, Any] | None = None) -> None:
        self.store, self.snapshot = store, snapshot
        self.root = root.expanduser().absolute()
        if (self.root.resolve(strict=True) != self.root
                or any(self.root.is_relative_to(path) or path.is_relative_to(self.root)
                       for path in (primary, store.root, *store.locations.values()))):
            raise ProjectConflict("A private resource root cannot alias or overlap another resource namespace.")
        self.identity = _identity(self.root.stat(follow_symlinks=False))
        self.views: dict[str, dict[str, int]] = {}
        if bound is not None:
            validate_resources_binding(bound)
            if (bound["root"] != str(self.root) or set(bound["views"]) != set(store.locations)
                    or {key: bound[key] for key in self.identity} != self.identity):
                raise ProjectConflict("Private resource views changed after the host bound them.")
        with self._container() as container:
            if set(os.listdir(container)) - set(store.locations):
                raise ProjectConflict("A private resource container contains an ungranted resource key.")
            for key in store.locations:
                if bound is None:
                    try:
                        os.mkdir(key, mode=0o700, dir_fd=container)
                    except FileExistsError:
                        pass
                with directory(container, (key,)) as fd:
                    _no_store(fd)
                    self.views[key] = _identity(os.fstat(fd))
                    if bound is not None:
                        if self.views[key] != bound["views"][key]:
                            raise ProjectConflict("A private resource directory was replaced after host binding.")
                    else:
                        self._clone(fd, key)

    def _clone(self, fd: int, key: str) -> None:
        prefix = f"@{key}/"
        declared = {name[len(prefix):]: entry for name, entry in self.snapshot["files"].items()
                    if name.startswith(prefix) and self.admits(key, name[len(prefix):], output=True)}
        existing = member_names(fd)
        if existing - set(declared):
            raise ProjectConflict("A resource clone cannot adopt unregistered private bytes.")
        for relative, entry in declared.items():
            leaf = parts(relative)
            with directory(fd, leaf[:-1], create=True) as parent:
                if relative not in existing:
                    install(parent, leaf[-1], self.store.read_bytes(prefix + relative,
                            generation=self.snapshot["generation"]), mode=entry["mode"], exclusive=True)
                data, mode = read_file(parent, leaf[-1], owned=True)
            if sha(data) != entry["sha256"] or mode != entry["mode"]:
                raise ProjectConflict("A resource clone must retain the selected generation's bytes and modes.")

    @contextmanager
    def _container(self) -> Iterator[int]:
        if self.root.resolve(strict=True) != self.root:
            raise ProjectConflict("The private resource container acquired a path alias.")
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if _identity(os.fstat(fd)) != self.identity:
                raise ProjectConflict("The private resource container changed identity.")
            yield fd
            if _identity(self.root.stat(follow_symlinks=False)) != self.identity:
                raise ProjectConflict("The private resource container changed identity during IO.")
        finally:
            os.close(fd)

    @contextmanager
    def open(self, key: str) -> Iterator[int]:
        with self._container() as container, directory(container, (key,)) as fd:
            if key not in self.views or _identity(os.fstat(fd)) != self.views[key]:
                raise ProjectConflict("The private resource directory changed identity.")
            _no_store(fd)
            yield fd
            if _identity(os.stat(key, dir_fd=container, follow_symlinks=False)) != self.views[key]:
                raise ProjectConflict("The private resource directory changed identity during IO.")

    def admits(self, key: str, relative: str, *, output: bool = False) -> bool:
        members = self.store.location_members[key]
        return members is None or relative in members or (not output and any(
            relative == "." or name.startswith(relative + "/") for name in members))

    def logical(self, path: Path, *, private_only: bool = False) -> str | None:
        matches = set()
        for key, actual in self.store.locations.items():
            roots = [self.root / key]
            if not private_only:
                roots += [actual, Path(self.snapshot["locators"].get(key, str(actual)))]
            for root in roots:
                if path.is_relative_to(root):
                    relative = path.relative_to(root).as_posix()
                    if relative != ".":
                        parts(relative)
                    if not self.admits(key, relative):
                        raise ProjectConflict("The private resource path exceeds its finite host capability.")
                    with self.open(key):
                        matches.add(f"@{key}" if relative == "." else f"@{key}/{relative}")
        if len(matches) > 1:
            raise ProjectConflict("A resource path has ambiguous trusted namespaces.")
        if not matches and path.is_relative_to(self.root):
            raise ProjectConflict("The resource container does not grant its own parent or unknown keys.")
        return next(iter(matches)) if matches else None

    def binding(self) -> dict[str, Any]:
        for key in self.views:
            with self.open(key):
                pass
        return {"root": str(self.root), **self.identity, "views": self.views.copy()}
