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
from .incoming_sources import selected_sealed_view
from .candidate_resources import CandidateResources, overlaps_resource_grant


class ProjectCandidateResolver(ProjectSourceResolver):
    def __init__(self, store: FileProjectStore, candidate_root: Path, generation: str | None = None, *,
                 bound_identity: dict[str, int] | None = None, resources_root: Path | None = None,
                 bound_resources: dict[str, Any] | None = None) -> None:
        super().__init__(store, generation)
        self.candidate_root = candidate_root.expanduser().absolute()
        active = (store.root, *store.locations.values()) if resources_root is None else (store.root,)
        if (self.candidate_root.resolve(strict=True) != self.candidate_root
                or any(self.candidate_root.is_relative_to(root) or root.is_relative_to(self.candidate_root)
                       for root in active)
                or resources_root is not None and overlaps_resource_grant(self.candidate_root, store)):
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
        if bound_resources is not None and (resources_root is None or bound_identity is None):
            raise ProjectConflict("Worker resource views require their host-bound primary candidate.")
        self.resources = (CandidateResources(store, self.snapshot, resources_root, self.candidate_root,
                                            bound=bound_resources) if resources_root is not None else None)
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

    def logical_resource(self, original: str | Path, *, private_only: bool = False) -> str | None:
        path = Path(original).expanduser().absolute()
        primary = path.is_relative_to(self.candidate_root) or not private_only
        relative = self._relative(path) if primary else None
        resource = self.resources.logical(path, private_only=private_only) if self.resources is not None else None
        if resource is not None and relative is not None and relative.startswith(".sciplot_resources/"):
            relative = None  # The registered cold-resource mount retains its @key namespace.
        if relative is not None and resource is not None:
            raise ProjectConflict("A candidate path has ambiguous primary and resource namespaces.")
        if relative is not None:
            resource = relative
        if resource is not None:
            with self._namespace(resource) as (fd, local):
                self._ordinary_path(fd, local)
        return resource

    @staticmethod
    def _ordinary_path(fd: int, relative: str) -> None:
        components = () if relative == "." else parts(relative)
        current = os.dup(fd)
        try:
            for index, name in enumerate(components):
                try:
                    info = os.stat(name, dir_fd=current, follow_symlinks=False)
                except FileNotFoundError:
                    return  # Only an admitted output port may later create it.
                if stat.S_ISDIR(info.st_mode):
                    following = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                    os.close(current)
                    current = following
                elif index != len(components) - 1 or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ProjectConflict("A candidate path cannot traverse aliases, special files or unowned links.")
        finally:
            os.close(current)

    @contextmanager
    def _namespace(self, logical: str) -> Iterator[tuple[int, str]]:
        if logical.startswith("@"):
            key, _, relative = logical[1:].partition("/")
            if self.resources is None or key not in self.store.locations:
                raise ProjectConflict("This candidate has no private resource view.")
            with self.resources.open(key) as fd:
                yield fd, relative or "."
        else:
            with self._root() as fd:
                yield fd, logical

    def _private_path(self, logical: str) -> Path:
        if logical.startswith("@"):
            assert self.resources is not None
            return self.resources.root / logical[1:]
        return self.candidate_root if logical == "." else self.candidate_root / logical

    def _literal(self, logical: str) -> str:
        if logical.startswith("@"):
            key, _, relative = logical[1:].partition("/")
            origin = Path(self.snapshot["locators"].get(key, str(self.store.locations[key])))
            return str(origin / relative) if relative else str(origin)
        return str(self.origin if logical == "." else self.origin / logical)

    def _source(self, relative: str, expected: str | None, source_id: str | None) -> None:
        if source_id is None:
            return
        literal = self._literal(relative)
        matches = [entry for identity, versions in self.snapshot["sources"].items()
                   for version, entry in versions.items()
                   if (source_id == identity or source_id in entry.get("aliases", []))
                   and entry.get("locator") == literal and version == expected]
        if len(matches) != 1:
            raise ProjectConflict("The candidate source must retain its exact original locator, UUID and version.")

    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None) -> Path:
        path = Path(original).expanduser().absolute()
        sealed = selected_sealed_view(self.store, self.snapshot, path,
                                      expected_sha256=expected_sha256, source_id=source_id)
        if sealed is not None:
            return sealed
        relative = self.logical_resource(path)
        if relative is None:
            return super().resolve_path(original, expected_sha256=expected_sha256, source_id=source_id)
        self._source(relative, expected_sha256, source_id)
        with self._namespace(relative) as (fd, local):
            components = () if local == "." else parts(local)
            with directory(fd, components[:-1]) as parent:
                info = os.fstat(parent) if not components else os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                with directory(fd, components) as child:
                    names = member_names(child)
                    members = {name: self._read(child, name) for name in names}
                prefix = "" if relative == "." else relative + "/"
                declared = {name[len(prefix):]: entry for name, entry in self.snapshot["files"].items()
                            if name.startswith(prefix) and (prefix or not name.startswith("@"))}
                if relative.startswith("@"):
                    key = relative[1:].split("/", 1)[0]
                    assert self.resources is not None
                    for name in members:
                        member = name if local == "." else local + "/" + name
                        if not self.resources.admits(key, member):
                            raise ProjectConflict("A finite resource directory contains an ungranted private member.")
                protected = {name[len(prefix):] for name in self._input_members if name.startswith(prefix)}
                for name in protected:
                    entry = declared.get(name)
                    if (entry is None or name not in members or sha(members[name][0]) != entry["sha256"]
                            or members[name][1] != entry["mode"]):
                        raise ProjectConflict("A candidate scientific input directory changed its bytes or membership.")
                version = digest({"kind": "directory", "files": [
                    {"path": name, "content_sha256": sha(data[0])} for name, data in sorted(members.items())]})
                if expected_sha256 is not None and version != expected_sha256:
                    raise ProjectConflict("The candidate directory has another explicit source version.")
            else:
                data, mode = self._read(fd, local)
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
        return self._private_path(relative)

    def output_path(self, original: str | Path) -> Path:
        """An admitted renderer output may create only private ordinary members."""
        relative = self.logical_resource(original)
        local = relative.split("/", 1)[1] if relative is not None and relative.startswith("@") and "/" in relative else relative
        if (relative is None or relative == "." or relative in self._input_members
                or local is None or local.split("/", 1)[0] in {"raw", "source"}):
            raise ProjectConflict("A candidate renderer output cannot overwrite science or escape its private primary root.")
        if relative.startswith("@"):
            key, _, member = relative[1:].partition("/")
            if not member or self.resources is None or not self.resources.admits(key, member, output=True):
                raise ProjectConflict("A resource output requires an exact host-granted member.")
        components = parts(local)
        with self._namespace(relative) as (fd, _), directory(fd, components[:-1], create=True) as parent:
            try:
                info = os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ProjectConflict("A candidate output must be an ordinary unaliased private file.")
        return self._private_path(relative)

    def literal_path(self, actual: Path) -> str:
        sealed = selected_sealed_view(self.store, self.snapshot, actual.expanduser().absolute())
        if sealed is not None:
            return super().literal_path(sealed)
        relative = self.logical_resource(actual)
        if relative is None:
            return super().literal_path(actual)
        self.resolve_path(actual)
        return self._literal(relative)

    def binding(self) -> dict[str, Any]:
        with self._root():
            candidate: dict[str, Any] = {"root": str(self.candidate_root), **self.identity}
            if self.resources is not None:
                candidate["resources"] = self.resources.binding()
            return {**super().binding(), "kind": "sciplot_project_candidate_runtime",
                    "candidate": candidate}
