"""Manifest member names and the host-selected finite archive location."""
import os
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.foundation.path_names import safe_filename
from sciplot_core.project_store import FileProjectStore, ResourceRoot
from sciplot_core.project_store.io import StoreIO, directory

_CANONICAL_MANIFEST_NAME = "intake_manifest.json"


@contextmanager
def admitted_project_generation(project: Path, *, blocking: bool = False) -> Iterator[tuple[FileProjectStore, StoreIO, dict[str, Any]]]:
    """Read primary sealed metadata; never lease or project external resources."""
    primary = FileProjectStore(project, locations={})
    with StoreIO(project, {}).locked(blocking=blocking):
        with primary._locked(allow_pending=True) as (io, current):
            yield primary, io, current


def _validate_manifest_target(path: Path, *, project_dir: Path) -> Path:
    if path.is_symlink():
        raise PermissionError(f"Refusing a symlink-backed SciPlot project manifest: {path}")
    if path.parent.resolve() != project_dir:
        raise ValueError("A SciPlot project manifest must stay inside its project.")
    return path


def _project_manifest_paths(project_dir: Path, *, mirror_path: Path | None = None) -> tuple[Path, ...]:
    project = project_dir.expanduser().resolve()
    canonical = _validate_manifest_target(project / _CANONICAL_MANIFEST_NAME, project_dir=project)
    mirrors = [_validate_manifest_target(path, project_dir=project) for path in sorted(project.glob("*.sciplot.json"))]
    if mirror_path is not None:
        requested = mirror_path.expanduser().absolute()
        _validate_manifest_target(requested, project_dir=project)
        if requested.suffixes[-2:] != [".sciplot", ".json"]:
            raise ValueError("The SciPlot project-manifest mirror must end in `.sciplot.json`.")
        mirrors.append(project / requested.name)
    return tuple(dict.fromkeys((canonical, *sorted(mirrors))))



def intake_snapshot_location(project: Path, payload: dict[str, Any]) -> ResourceRoot:
    name = safe_filename(f"{payload.get('project_slug') or project.name}.zip")
    if (project / ".sciplot_store/local_locations.json").is_file():
        descriptor = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with directory(descriptor, (".sciplot_resources", "snapshot"), create=True):
                pass
        finally:
            os.close(descriptor)
        return ResourceRoot(project / ".sciplot_resources/snapshot", (name,))
    return ResourceRoot(project.parent, (name,))


def admitted_intake_manifest(project: Path, *, initial: dict[str, Any] | None = None,
                             blocking: bool = False) -> dict[str, Any] | None:
    """Select archive names from sealed bytes, without projecting a pending head.

    This is only host-capability selection. Ordinary manifest reads still check
    the exact visible preimage and require explicit recovery when it is pending.
    """
    if (project / ".sciplot_store/head.json").is_file():
        with admitted_project_generation(project, blocking=blocking) as (_primary, io, current):
            names = [_CANONICAL_MANIFEST_NAME, *sorted(name for name in current["files"]
                if "/" not in name and name.endswith(".sciplot.json"))]
            for name in names:
                entry = current["files"].get(name)
                if entry is not None:
                    value = json.loads(io.get(entry))
                    if not isinstance(value, dict):
                        raise ValueError("The admitted project manifest must be an object.")
                    return value
        return initial
    if initial is not None:
        return initial
    for path in _project_manifest_paths(project):
        if path.is_file():
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict):
                raise ValueError("The project manifest must be an object.")
            return value
    return None
