"""Bind a trusted selected project generation to the pure scientific IO port."""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_locations import (
    literal_source_path, resolve_source_path, selected_source_resolver, source_location_scope,
)
from . import state
from .errors import ProjectConflict
from .io import digest
from .repository import FileProjectStore


class ProjectSourceResolver:
    def __init__(self, store: FileProjectStore, generation: str | None = None) -> None:
        self.store = store
        with store._locked() as (io, current):
            self.snapshot = state.generation(io, generation) if generation is not None else current
            if self.snapshot["project_id"] != current["project_id"]:
                raise ProjectConflict("A source resolver must belong to this exact project.")
        self.generation = self.snapshot["generation"]
        self._roots = tuple(Path(value) for value in self.snapshot["locators"].values()) + (
            store.root, *store.locations.values())
        self._sources = {entry["locator"] for versions in self.snapshot["sources"].values()
                         for entry in versions.values() if entry.get("locator")}

    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None) -> Path:
        path = Path(original).expanduser().absolute()
        # Only exact known namespaces enter the store. Private host-created
        # audit copies outside those roots retain their ordinary local IO.
        if (source_id is not None or str(path) in self._sources
                or any(path.is_relative_to(root) for root in self._roots)):
            return self.store.resolve_path(original, expected_sha256=expected_sha256,
                                           source_id=source_id, generation=self.generation)
        return path

    def literal_path(self, actual: Path) -> str:
        path = actual.expanduser().absolute()
        if any(path.is_relative_to(root) for root in (self.store.root, *self.store.locations.values())):
            return self.store.literal_path(path, generation=self.generation)
        return str(path)

    def binding(self) -> dict[str, Any]:
        return {"kind": "sciplot_project_runtime", "version": 1, "root": str(self.store.root),
                "project_id": self.snapshot["project_id"], "generation": self.generation,
                "generation_sha256": digest(self.snapshot),
                "locations": {key: {"path": str(path), "members": list(members) if members is not None else None}
                              for key, path in self.store.locations.items()
                              for members in [self.store.location_members[key]]}}


@contextmanager
def project_runtime(store: FileProjectStore, generation: str | None = None) -> Iterator[ProjectSourceResolver]:
    resolver = ProjectSourceResolver(store, generation)
    with source_location_scope(resolver):
        yield resolver


# Host adapters use the same port as pure source consumers.
resolve_runtime_path = resolve_source_path
literal_runtime_path = literal_source_path


def selected_project_store() -> FileProjectStore | None:
    """Return only the currently host-bound concrete store, preserving its caps."""
    selected = selected_source_resolver()
    return selected.store if isinstance(selected, ProjectSourceResolver) else None
