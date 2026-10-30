"""Concrete selected-generation resolver shared by host runtime views."""
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator, Iterable
import tempfile
import os
from sciplot_core.foundation.source_locations import source_location_scope
from typing import Any

from . import state
from .errors import ProjectConflict, ProjectStoreError
from .io import digest
from .incoming_sources import literal_sealed_tree, resolve_expected_source, selected_expectations
from .repository import FileProjectStore


class ProjectSourceResolver:
    def __init__(self, store: FileProjectStore, generation: str | None = None) -> None:
        self.store = store
        with store._locked() as (io, current):
            self.snapshot = state.generation(io, generation) if generation is not None else current
            if self.snapshot["project_id"] != current["project_id"]:
                raise ProjectConflict("A source resolver must belong to this exact project.")
        self.generation: str = self.snapshot["generation"]
        self._primary_roots = (Path(self.snapshot["locators"][""]), store.root)
        self._resource_roots: list[tuple[Path, tuple[str, ...] | None]] = []
        for key, original in self.snapshot["locators"].items():
            if not key:
                continue
            members = store.location_members.get(key)
            if key not in store.locations:
                prefix = f"@{key}/"
                members = tuple(name[len(prefix):] for name in self.snapshot["files"] if name.startswith(prefix))
            self._resource_roots.append((Path(original), members))
        self._resource_roots.extend((root, store.location_members[key]) for key, root in store.locations.items())
        self._sources = {entry["locator"] for versions in self.snapshot["sources"].values()
                         for entry in versions.values() if entry.get("locator")}

    @property
    def inspection_generation(self) -> str | None:
        return self.generation

    def source_identity(self, original: str | Path, version: str | None, identity: str | None) -> str | None:
        return identity

    @staticmethod
    def _in_resource(path: Path, root: Path, members: tuple[str, ...] | None) -> bool:
        if not path.is_relative_to(root):
            return False
        if members is None:
            return True
        relative = path.relative_to(root).as_posix()
        return (bool(members) if relative == "." else
                relative in members or any(member.startswith(relative + "/") for member in members))

    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None) -> Path:
        expected = resolve_expected_source(self.store, self.snapshot, original,
                                           expected_sha256=expected_sha256, source_id=source_id)
        if expected is not None:
            return expected
        path = Path(original).expanduser().absolute()
        # Only exact known namespaces enter the store. Private host-created
        # audit copies outside those roots retain their ordinary local IO.
        if (source_id is not None or str(path) in self._sources
                or any(path.is_relative_to(root) for root in self._primary_roots)
                or any(self._in_resource(path, root, members) for root, members in self._resource_roots)):
            return self.store.resolve_path(original, expected_sha256=expected_sha256,
                                           source_id=source_id, generation=self.generation)
        return path

    def literal_path(self, actual: Path) -> str:
        sealed = literal_sealed_tree(self.store, self.snapshot, actual)
        if sealed is not None:
            return sealed
        path = actual.expanduser().absolute()
        if (path.is_relative_to(self.store.root)
                or any(self._in_resource(path, root, self.store.location_members[key])
                       for key, root in self.store.locations.items())):
            return self.store.literal_path(path, generation=self.generation)
        return str(path)

    def binding(self) -> dict[str, Any]:
        value = {"kind": "sciplot_project_runtime", "version": 1, "root": str(self.store.root),
                "project_id": self.snapshot["project_id"], "generation": self.generation,
                "generation_sha256": digest(self.snapshot),
                "locations": {key: {"path": str(path), "members": list(members) if members is not None else None}
                              for key, path in self.store.locations.items()
                              for members in [self.store.location_members[key]]}}
        expectations = selected_expectations(self.snapshot)
        if expectations is not None:
            value["source_expectations"] = expectations
        return value


class QuerySourceResolver(ProjectSourceResolver):
    """Use checked physical evidence; sealed-only files get disposable external views."""
    def __init__(self, store: FileProjectStore, generation: str | None = None, *,
                 semantic_sources: Iterable[dict[str, Any]] = (),
                 protected_roots: Iterable[Path] = ()) -> None:
        super().__init__(store, generation)
        # A current query remains a current physical observation after unrelated
        # project commands. Only an explicit historical/sealed scope freezes it.
        self._inspection_generation = (self.generation if generation is not None
            or selected_expectations(self.snapshot) is not None else None)
        self._semantic_aliases: dict[tuple[str, str, str], str] = {}
        for source in semantic_sources:
            if not isinstance(source.get("source_id"), str):
                continue  # Old Legacy sources retain their path/version-only identity.
            matches = [identity for identity, versions in self.snapshot["sources"].items()
                       if source["sha256"] in versions
                       and versions[source["sha256"]].get("locator") == source["path"]]
            if len(matches) != 1:
                raise ProjectConflict("A captured semantic source must name one exact registered file version.")
            self._semantic_aliases[(source["path"], source["sha256"], source["source_id"])] = matches[0]
        self.temporary: tempfile.TemporaryDirectory[str] | None = None
        self._views: dict[Path, str] = {}
        from sciplot_core.foundation.source_locations import selected_source_resolver

        parent = selected_source_resolver()
        self._temporary_protection: list[tuple[Path, tuple[str, ...] | None]] = [*((root, None) for root in self._primary_roots),
            *self._resource_roots, *((root, None) for root in protected_roots),
            *(parent._temporary_protection if isinstance(parent, QuerySourceResolver) else ())]

    @property
    def inspection_generation(self) -> str | None:
        return self._inspection_generation

    def source_identity(self, original: str | Path, version: str | None, identity: str | None) -> str | None:
        if version is None or identity is None:
            return identity
        literal = self.literal_path(Path(original))
        return self._semantic_aliases.get((literal, version, identity), identity)

    def literal_path(self, actual: Path) -> str:
        """Identify the source locator; inspection separately proves current bytes."""
        from .locators import original_for_logical

        path = actual.expanduser().absolute()
        if path in self._views:
            return self._views[path]
        if str(path) in self._sources:
            return str(path)
        try:
            logical = self.store.logical_path(path)
        except ProjectStoreError:
            return super().literal_path(path)
        if logical in self.snapshot["files"]:
            return original_for_logical(self.snapshot, logical)
        return super().literal_path(path)

    def _temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        # gettempdir() can probe by writing. Choose and validate the host's
        # existing base without invoking that probe, even on its first use.
        value = tempfile.tempdir
        if value is None:
            value = next((os.environ[key] for key in ("TMPDIR", "TEMP", "TMP") if os.environ.get(key)), "/tmp")
        base = Path(os.fsdecode(value)).expanduser().absolute().resolve(strict=True)
        if not base.is_dir():
            raise ProjectStoreError("A query temporary base must be an existing directory.")
        protected: set[Path] = set()
        for root, members in self._temporary_protection:
            aliases = {root.expanduser().absolute(), root.expanduser().absolute().resolve()}
            protected.update(path if members is None else path / member
                             for path in aliases for member in (members if members is not None else ("",)))
        if any(base == root or base.is_relative_to(root) for root in protected):
            raise ProjectConflict("A query temporary base must stay outside protected project and source namespaces.")
        # An external ancestor such as /tmp is valid. Before creation, exclude
        # every protected descendant from the entire possible child-name set.
        prefix = "sciplot-query-source-"
        while any(root.is_relative_to(base) and root != base
                  and root.relative_to(base).parts[0].startswith(prefix) for root in protected):
            prefix += "private-"
        return tempfile.TemporaryDirectory(prefix=prefix, dir=str(base))

    def close(self) -> None:
        if self.temporary is not None:
            self.temporary.cleanup()
        self._views.clear()

    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None) -> Path:
        from sciplot_core.project_store.source_inspection import inspect_file
        from sciplot_core.project_store.physical_projection import projected_artifact
        from sciplot_core.project_store.locators import source_entry

        path = Path(original).expanduser().absolute()
        literal = self.literal_path(path)
        source_id = self.source_identity(original, expected_sha256, source_id)
        if source_id is not None or literal in self._sources:
            observation = inspect_file(self.store, literal, expected_sha256=expected_sha256,
                                       source_id=source_id, generation=self.inspection_generation)
            if observation.physical is not None:
                return observation.physical
            with self.store._locked() as (io, _current):
                identity, version, entry = source_entry(io, self.snapshot, literal,
                    expected_sha256=expected_sha256, source_id=source_id)
                data = io.get(entry)
            if self.temporary is None:
                self.temporary = self._temporary_directory()
            target = Path(self.temporary.name).resolve() / (identity + "-" + version)
            if not target.exists():
                target.write_bytes(data)
                target.chmod(0o400)
            self._views[target] = literal
            if target.read_bytes() != data or target.stat().st_mode & 0o777 != 0o400:
                raise ProjectConflict("A private query source view changed from its exact sealed bytes or mode.")
            return target
        physical = projected_artifact(self.store, original, generation=self.inspection_generation)
        if physical is not None:
            return physical
        if (any(path.is_relative_to(root) for root in self._primary_roots)
                or any(self._in_resource(path, root, members) for root, members in self._resource_roots)):
            raise ProjectStoreError("A query cannot expose an unregistered path in its selected project resources.")
        return path


@contextmanager
def query_sources(store: FileProjectStore, generation: str | None = None, *,
                  semantic_sources: Iterable[dict[str, Any]] = (),
                  protected_roots: Iterable[Path] = ()) -> Iterator[None]:
    resolver = QuerySourceResolver(store, generation, semantic_sources=semantic_sources, protected_roots=protected_roots)
    try:
        with source_location_scope(resolver):
            yield
    finally:
        resolver.close()
