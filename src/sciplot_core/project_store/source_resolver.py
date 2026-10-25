"""Concrete selected-generation resolver shared by host runtime views."""
from pathlib import Path
from typing import Any

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
