"""Read an admitted physical directory; source caches never prove delivery IO."""

from pathlib import Path

from . import directories, state
from .errors import ProjectStoreError
from .paths import LocatorStore
from .root_bindings import require as require_roots


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
        selected = directories._prefix(value, Path(original).expanduser().absolute(),
                                       {"": io.root, **io.locations})
        if selected is None:
            raise ProjectStoreError("Physical evidence requires a registered directory prefix.")
        prefix, _literal = selected
        components = tuple(prefix.rstrip("/").split("/")) if prefix else ()
        key = components[0][1:] if components and components[0].startswith("@") else ""
        if io.location_members.get(key) is not None:
            raise ProjectStoreError("A finite file grant cannot expose a physical directory.")
        checked = directories._checked_prefix(io, value, Path(original).expanduser().absolute())
        if checked is None or checked[0] != prefix:
            raise ProjectStoreError("The physical directory has no exact generation projection.")
        relative = components[1:] if key else components
        return (io.locations[key] if key else io.root).joinpath(*relative)
