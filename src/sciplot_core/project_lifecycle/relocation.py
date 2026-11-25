"""Explicit relocation of a saved Store, not a new project or a paper snapshot."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.research_destination import require_data_destination
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.io import STORE

from .errors import EngineError
from .store_composition import existing_store


def _overlaps(target: Path, protected: Path) -> bool:
    return target.is_relative_to(protected) or protected.is_relative_to(target)


def _new_destination(value: Path, origin: Path) -> Path:
    target = canonical_path(value)
    require_data_destination(target)
    if _overlaps(target, origin):
        raise EngineError("project_bundle_path_overlap", "Choose a new destination outside the original project or bundle.")
    if target.exists():
        raise EngineError("project_bundle_destination_exists", "The bundle or relocation destination already exists; nothing was replaced.")
    if not target.parent.is_dir():
        raise EngineError("project_bundle_parent_missing", "Choose a new destination under an existing research directory.")
    return target


def _result(operation: str, project: Path, bundle: Path, head: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "sciplot_project_bundle_result", "version": 1, "status": operation,
            "project": str(project), "bundle": str(bundle), "project_id": head["project_id"],
            "generation": head["generation"], "mode": "same_project_relocation",
            "independent_project": False, "host_grants_included": False}


def export_project_bundle(project: Path, destination: Path) -> dict[str, Any]:
    """Bundle the exact admitted generation, without opening or initializing a plot."""
    root = canonical_path(project)
    if not canonical_path(root / STORE / "head.json").is_file():
        raise EngineError("project_bundle_store_required", "Choose the exact root of an already versioned Store. A VSZ, old unregistered project and paper package cannot be relocated this way.")
    out = _new_destination(destination, root)
    store = existing_store(root)
    for key, location in store.locations.items():
        members = store.location_members[key]
        protected = (location,) if members is None else (location / member for member in members)
        if any(_overlaps(out, path) for path in protected):
            raise EngineError("project_bundle_path_overlap", "The bundle destination overlaps a registered project resource.")

    with store._locked():
        head = store.snapshot()
        if head["projection_status"] != "current":
            raise ProjectConflict("Resolve unadmitted outside changes before bundling the saved project.")
        bundle = store.export_bundle(out)
    return _result("exported", root, bundle, head)


def import_project_bundle(bundle: Path, destination: Path) -> dict[str, Any]:
    """Rebind the same authoritative bundle in a new local directory without running it."""
    source = canonical_path(bundle)
    if not canonical_path(source / "bundle.json").is_file() or not canonical_path(source / "store").is_dir():
        raise EngineError("project_bundle_required", "Choose an exact Store bundle directory produced by project bundle-export.")
    out = _new_destination(destination, source)
    # The existing importer validates original generation/command bytes and
    # installs only its confined local resource roots. Executor host grants live
    # outside the Store and aren't read or installed by this use case.
    store = FileProjectStore.import_bundle(source, out)
    head = store.snapshot()
    if head["projection_status"] != "current":
        raise ProjectConflict("The installed relocation is not current; preserve its directory and inspect it.")
    return _result("imported", store.root, source, head)
