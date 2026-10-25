"""A host-held private primary-project clone is an IO view, never a new store."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import stat
from typing import Any

from .errors import ProjectConflict, ProjectStoreError
from .io import STORE, digest, directory, member_names, parts, read_file, sha
from .repository import FileProjectStore
from .source_resolver import ProjectSourceResolver


class ProjectCandidateResolver(ProjectSourceResolver):
    def __init__(self, store: FileProjectStore, candidate_root: Path, generation: str | None = None, *,
                 bound_identity: dict[str, int] | None = None) -> None:
        super().__init__(store, generation)
        self.candidate_root = candidate_root.expanduser().absolute()
        if (self.candidate_root.resolve(strict=True) != self.candidate_root
                or any(self.candidate_root.is_relative_to(root) or root.is_relative_to(self.candidate_root)
                       for root in (store.root, *store.locations.values()))):
            raise ProjectConflict("A private candidate cannot alias or overlap an active project resource root.")
        info = self.candidate_root.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ProjectStoreError("A candidate requires one canonical private host-owned directory.")
        self.identity = {"device": info.st_dev, "inode": info.st_ino}
        if bound_identity is not None and bound_identity != self.identity:
            raise ProjectConflict("The private candidate directory was replaced after host binding.")
        self.origin = Path(self.snapshot["locators"][""])
        self._input_members = set(self.snapshot.get("input_resources", []))
        self._input_members.update(entry["logical"] for versions in self.snapshot["sources"].values()
                                   for entry in versions.values() if entry.get("logical"))
        with self._root() as fd:
            names = member_names(fd)
            if bound_identity is None:
                for logical, entry in self.snapshot["files"].items():
                    if logical.startswith("@"):
                        continue
                    if logical not in names or self._read(fd, logical)[0] != store.read_bytes(logical, generation=self.generation):
                        raise ProjectConflict("A candidate must begin as the complete selected primary generation.")
                    if self._read(fd, logical)[1] != entry["mode"]:
                        raise ProjectConflict("The candidate must preserve each selected member's mode.")

    @contextmanager
    def _root(self) -> Iterator[int]:
        if self.candidate_root.resolve(strict=True) != self.candidate_root:
            raise ProjectConflict("The private candidate acquired a path alias.")
        fd = os.open(self.candidate_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if ({"device": info.st_dev, "inode": info.st_ino} != self.identity
                    or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise ProjectConflict("The private candidate directory identity changed.")
            try:
                os.stat(STORE, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ProjectConflict("A private candidate must not create a second project store.")
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def _read(fd: int, logical: str) -> tuple[bytes, int]:
        components = parts(logical)
        with directory(fd, components[:-1]) as parent:
            return read_file(parent, components[-1], owned=True)

    def _relative(self, path: Path) -> str | None:
        matches = {path.relative_to(root).as_posix() for root in (self.candidate_root, self.store.root, self.origin)
                   if path.is_relative_to(root)}
        if len(matches) > 1:
            raise ProjectConflict("The candidate path has ambiguous primary namespaces.")
        if not matches:
            return None
        relative = matches.pop()
        if relative != ".":
            parts(relative)
        return relative

    def _source(self, relative: str, expected: str | None, source_id: str | None) -> None:
        if source_id is None:
            return
        literal = str(self.origin / relative)
        matches = [entry for identity, versions in self.snapshot["sources"].items()
                   for version, entry in versions.items()
                   if (source_id == identity or source_id in entry.get("aliases", []))
                   and entry.get("locator") == literal and version == expected]
        if len(matches) != 1:
            raise ProjectConflict("The candidate source must retain its exact original locator, UUID and version.")

    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None) -> Path:
        path = Path(original).expanduser().absolute()
        relative = self._relative(path)
        if relative is None:
            return super().resolve_path(original, expected_sha256=expected_sha256, source_id=source_id)
        self._source(relative, expected_sha256, source_id)
        with self._root() as fd:
            components = () if relative == "." else parts(relative)
            with directory(fd, components[:-1]) as parent:
                info = os.fstat(parent) if not components else os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                with directory(fd, components) as child:
                    names = member_names(child)
                    members = {name: self._read(child, name) for name in names}
                prefix = "" if relative == "." else relative + "/"
                declared = {name[len(prefix):]: entry for name, entry in self.snapshot["files"].items()
                            if name.startswith(prefix) and not name.startswith("@")}
                protected = {name[len(prefix):] for name in self._input_members if name.startswith(prefix)}
                for name in protected:
                    entry = declared.get(name)
                    if entry is None or name not in members or sha(members[name][0]) != entry["sha256"]:
                        raise ProjectConflict("A candidate scientific input directory changed its bytes or membership.")
                version = digest({"kind": "directory", "files": [
                    {"path": name, "content_sha256": sha(data[0])} for name, data in sorted(members.items())]})
                if expected_sha256 is not None and version != expected_sha256:
                    raise ProjectConflict("The candidate directory has another explicit source version.")
            else:
                data, mode = self._read(fd, relative)
                entry = self.snapshot["files"].get(relative)
                expected = expected_sha256
                if relative in self._input_members:
                    if entry is None:
                        raise ProjectConflict("A candidate input is not a selected generation member.")
                    if expected is not None and expected != entry["sha256"]:
                        raise ProjectConflict("The candidate input declares another scientific version.")
                    expected = entry["sha256"]
                    if mode != entry["mode"]:
                        raise ProjectConflict("A candidate scientific input changed its mode.")
                if expected is not None and sha(data) != expected:
                    raise ProjectConflict("The candidate member differs from its exact requested bytes.")
        return self.candidate_root if relative == "." else self.candidate_root / relative

    def literal_path(self, actual: Path) -> str:
        relative = self._relative(actual.expanduser().absolute())
        if relative is None:
            return super().literal_path(actual)
        self.resolve_path(actual)
        return str(self.origin if relative == "." else self.origin / relative)

    def binding(self) -> dict[str, Any]:
        with self._root():
            return {**super().binding(), "kind": "sciplot_project_candidate_runtime",
                    "candidate": {"root": str(self.candidate_root), **self.identity}}
