"""Read admitted physical artifacts; source caches never prove delivery IO."""

from pathlib import Path
from typing import Any

from . import directories, locators, state
from .errors import ProjectStoreError
from .io import STORE, StoreIO, parts
from .paths import LocatorStore
from .root_bindings import require as require_roots


def _project_root(store: LocatorStore, original: str | Path, *,
                  generation: str | None, preserved: bool) -> tuple[Path, str]:
    literal = Path(original).expanduser().absolute()
    if not (store.root / STORE / "head.json").is_file():
        raise ProjectStoreError("Project identity requires an existing registered generation.")
    with store._locked() as (io, current):
        value = state.reachable(io, current, generation) if generation else current
        require_roots(io, current)
        matches = [(key, root) for key, root in {"": io.root, **io.locations}.items()
                   if literal == root or preserved and key in value["locators"]
                   and literal == Path(value["locators"][key])]
        if len(matches) != 1:
            raise ProjectStoreError("Project identity requires an exact bound physical resource root.")
        key, root = matches[0]
        if (key not in value["resource_roots"] or key not in value["locators"]
                or io.location_members.get(key) is not None):
            raise ProjectStoreError("Project identity requires a generation-bound whole-directory root.")
        return root, str(value["locators"][key])


def literal_project_root(store: LocatorStore, original: str | Path, *,
                         generation: str | None = None) -> str:
    """Identify an exact physical host root without certifying mutable members."""
    return _project_root(store, original, generation=generation, preserved=False)[1]


def projected_project_root(store: LocatorStore, original: str | Path, *,
                           generation: str | None = None) -> Path:
    """Locate an exact whole host root from its physical or preserved identity.

    This selects only an already-bound root, including an official cold import.
    Its members still require the separate strict physical-evidence projection.
    """
    return _project_root(store, original, generation=generation, preserved=True)[0]


def _directory(io: StoreIO, value: dict[str, Any], literal: Path,
               selected: tuple[str, str]) -> Path:
    prefix, _literal = selected
    components = tuple(prefix.rstrip("/").split("/")) if prefix else ()
    key = components[0][1:] if components and components[0].startswith("@") else ""
    if io.location_members.get(key) is not None:
        raise ProjectStoreError("A finite file grant cannot expose a physical directory.")
    checked = directories._checked_prefix(io, value, literal)
    if checked is None or checked[0] != prefix:
        raise ProjectStoreError("The physical directory has no exact generation projection.")
    relative = components[1:] if key else components
    return (io.locations[key] if key else io.root).joinpath(*relative)


def projected_directory(store: LocatorStore, original: str | Path, *,
                        generation: str | None = None) -> Path:
    """Select a verified whole directory from existing host caps, without writes.

    This is a physical-evidence reader, not source resolution or output admission.
    Finite file-only grants cannot expose their parent directory. All membership,
    bytes, modes and root identity checks remain those of the generation owner.
    """
    with store._locked() as (io, current):
        value = state.reachable(io, current, generation) if generation else current
        require_roots(io, current)
        literal = Path(original).expanduser().absolute()
        selected = directories._prefix(value, literal, {"": io.root, **io.locations})
        if selected is None:
            raise ProjectStoreError("Physical evidence requires a registered directory prefix.")
        return _directory(io, value, literal, selected)


def projected_artifact(store: LocatorStore, original: str | Path, *,
                       generation: str | None = None) -> Path | None:
    """Read an exact registered file/directory; None means neither is registered.

    A failed current-resource check never becomes a source-cache read. Private
    stage paths outside this generation retain their caller's existing IO port.
    """
    with store._locked() as (io, current):
        value = state.reachable(io, current, generation) if generation else current
        require_roots(io, current)
        literal = Path(original).expanduser().absolute()
        if (directories.owned_view(io, value, literal) is not None
                or locators.owned_source_view(io, value, literal) is not None):
            raise ProjectStoreError("A source cache cannot prove current physical artifact existence.")
        logical = locators.logical_for_literal(value, str(literal))
        if logical is None:
            try:
                actual = store.logical_path(literal)
            except ProjectStoreError:
                actual = None
            if actual is not None and actual in value["files"]:
                logical = actual
        if logical is not None:
            locators.checked_member(io, value, logical, None)
            components = parts(logical)
            key = components[0][1:] if components[0].startswith("@") else ""
            return (io.locations[key] if key else io.root).joinpath(*(components[1:] if key else components))
        selected = directories._prefix(value, literal, {"": io.root, **io.locations})
        return _directory(io, value, literal, selected) if selected is not None else None
