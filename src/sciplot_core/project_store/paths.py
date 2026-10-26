"""Exact native/source locator operations against an explicitly selected store."""

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from .errors import ProjectConflict, ProjectStoreError, ProjectSourceVersionMismatch
from .io import STORE, StoreIO, parts, sha
import sciplot_core.project_store.state as state
import sciplot_core.project_store.native_work as native_work


class LocatorStore(Protocol):
    root: Path
    locations: dict[str, Path]

    def _locked(self, *, import_legacy: bool = False, repair: bool = False,
                allow_pending: bool = False) -> AbstractContextManager[tuple[StoreIO, dict[str, Any]]]: ...
    def logical_path(self, path: Path) -> str: ...
    def resolve_source(self, source_id: str, version: str) -> Path: ...


def resolve_path(store: LocatorStore, original: str | Path, *, expected_sha256: str | None = None,
                 source_id: str | None = None, generation: str | None = None) -> Path:
    import sciplot_core.project_store.locators as locators

    literal = str(original)
    with store._locked() as (io, current):
        value = state.reachable(io, current, generation) if generation else current
        private = native_work.resolve(io, value, Path(literal), expected_sha256=expected_sha256, source_id=source_id)
        if private is not None:
            return private
        import sciplot_core.project_store.directories as directories
        owned = locators.owned_source_view(io, value, Path(literal), expected_sha256=expected_sha256, source_id=source_id)
        if owned is None:
            owned = directories.owned_view(io, value, Path(literal), expected_sha256=expected_sha256)
        if owned is not None:
            return owned[0]
        if (generation is not None and generation != current["generation"]
                and source_id is not None and expected_sha256 is not None):
            logical_source = locators.logical_for_literal(value, literal)
            if logical_source is None:
                try:
                    selected = store.logical_path(Path(literal))
                    logical_source = selected if selected in value["files"] else None
                except ProjectStoreError:
                    pass
            origin = locators.original_for_logical(value, logical_source) if logical_source else literal
            identity, version, _entry = locators.source_entry(io, value, origin,
                expected_sha256=expected_sha256, source_id=source_id)
            return store.resolve_source(identity, version)
        logical = locators.logical_for_literal(value, literal)
        if logical is None:
            try:
                candidate = store.logical_path(Path(literal))
                logical = candidate if candidate in value["files"] else None
            except ProjectStoreError:
                pass
        if logical is not None:
            entry = locators.checked_member(io, value, logical, expected_sha256)
            if source_id is not None:
                locators.source_entry(io, value, locators.original_for_logical(value, logical),
                    expected_sha256=entry["sha256"], source_id=source_id)
            components = parts(logical)
            return (store.locations[components[0][1:]] / Path(*components[1:])
                    if components[0].startswith("@") else store.root / Path(*components))
        closed = directories.resolve(io, value, Path(literal), expected_sha256=expected_sha256)
        if closed is not None:
            return closed
        identity, version, entry = locators.source_entry(io, value, literal,
            expected_sha256=expected_sha256, source_id=source_id)
        local = io.read("local_sources.json") or {"versions": {}}
        if local["versions"].get(identity, {}).get(version) == entry["sha256"]:
            return store.resolve_source(identity, version)
        from .io import read_file
        import os

        source = Path(literal)
        try:
            parent = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                data, _mode = read_file(parent, source.name)
            finally:
                os.close(parent)
        except OSError as exc:
            raise ProjectConflict("The exact registered original is missing; no same-name reconnection is allowed.") from exc
        if sha(data) != version:
            raise ProjectSourceVersionMismatch(literal, version, sha(data), "The exact original source differs from its registered version.")
        return source

def literal_path(store: LocatorStore, actual: Path, *, generation: str | None = None) -> str:
    import sciplot_core.project_store.locators as locators

    with store._locked() as (io, current):
        value = state.reachable(io, current, generation) if generation else current
        if actual == store.root:
            io.verify_roots()
            return str(value["locators"][""])
        private = native_work.literal(io, value, actual)
        if private is not None:
            return private
        import sciplot_core.project_store.directories as directories
        owned = locators.owned_source_view(io, value, actual)
        if owned is None:
            owned = directories.owned_view(io, value, actual)
        if owned is not None:
            return owned[1]
        try:
            logical = store.logical_path(actual)
        except ProjectStoreError:
            logical = None
        if logical is not None and logical in value["files"]:
            locators.checked_member(io, value, logical, None)
            return locators.original_for_logical(value, logical)
        prefix_literal = directories.literal(io, value, actual)
        if prefix_literal is not None:
            return prefix_literal
        for identity, versions in value["sources"].items():
            for version, entry in versions.items():
                name = Path(entry.get("locator") or entry.get("logical") or "source.bin").name
                if actual == store.root / STORE / "sources" / identity / version / name:
                    from .io import read_file
                    import os

                    parent = os.open(actual.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        observed = read_file(parent, actual.name)[0]
                    finally:
                        os.close(parent)
                    if observed != io.get(entry):
                        raise ProjectConflict("The resolved source view changed.")
                    return str(entry["locator"])
        raise ProjectStoreError("The actual path has no exact preserved locator in this generation.")
