"""Concrete selected-generation resolver shared by host runtime views."""
from pathlib import Path
from typing import Any

from . import state
from .errors import ProjectConflict
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
        self.generation = self.snapshot["generation"]
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
