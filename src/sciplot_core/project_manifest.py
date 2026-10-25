"""Intake compatibility views delegate to complete immutable project generations."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock, get_ident
from typing import Any

from sciplot_core.foundation.json_io import atomic_write_json, read_json_object
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.path_names import safe_filename
from sciplot_core.foundation.project_archives import write_project_archive
from sciplot_core.project_commands.resources import PreparedFile
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ResourceRoot
from sciplot_core.project_store.adapters import project_storage_scope, publish_files, store_for_project
from sciplot_core.project_store.io import directory, owned_io

_CANONICAL_MANIFEST_NAME = "intake_manifest.json"
_PROJECT_MANIFEST_LOCK = RLock()
_PRIVATE_SNAPSHOT: ContextVar[tuple[Path, int, int] | None] = ContextVar("intake_private_snapshot", default=None)


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


def _read_manifest_path(path: Path) -> dict[str, Any]:
    value = read_json_object(path)
    if value is None:
        raise ValueError(f"Expected a readable JSON object at {path}.")
    return value


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


def _manifest_store(project: Path, payload: dict[str, Any] | None = None) -> FileProjectStore:
    if owned_io(project) is not None:
        return store_for_project(project)
    if (project / ".sciplot_store/local_locations.json").is_file():
        current = FileProjectStore(project)
        if "snapshot" in current.locations:
            return current
        if payload is None:
            snapshot = current.snapshot()
            payload = json.loads(current.read_bytes(_CANONICAL_MANIFEST_NAME)) if _CANONICAL_MANIFEST_NAME in snapshot["files"] else {}
        capabilities = {key: ResourceRoot(path, current.location_members[key]) for key, path in current.locations.items()}
        capabilities["snapshot"] = intake_snapshot_location(project, payload)
        return FileProjectStore(project, locations=capabilities)
    if payload is None:
        for path in _project_manifest_paths(project):
            if path.is_file():
                payload = _read_manifest_path(path)
                break
    return FileProjectStore(project, locations={"snapshot": intake_snapshot_location(project, payload or {})})


@contextmanager
def locked_intake_project_manifest(project_dir: Path) -> Iterator[Path]:
    project = project_dir.expanduser().resolve(strict=True)
    with _PROJECT_MANIFEST_LOCK:
        store = _manifest_store(project)
        capabilities = {key: ResourceRoot(path, store.location_members[key]) for key, path in store.locations.items()}
        with project_storage_scope(project, locations=capabilities):
            yield project


def _read_intake_project_manifest_unlocked(project: Path) -> dict[str, Any] | None:
    targets = _project_manifest_paths(project)
    if (project / ".sciplot_store/head.json").is_file():
        store = _manifest_store(project)
        snapshot = store.snapshot()
        for path in targets:
            if path.name in snapshot["files"]:
                value = json.loads(store.read_bytes(path.name))
                if not isinstance(value, dict):
                    raise ValueError("The project manifest generation is invalid.")
                return value
        return None
    for path in targets:
        if path.is_file():
            return _read_manifest_path(path)
    return None


def read_intake_project_manifest(project_dir: Path) -> dict[str, Any] | None:
    return _read_intake_project_manifest_unlocked(project_dir.expanduser().resolve())


def _is_private_snapshot_root(project: Path) -> bool:
    binding = _PRIVATE_SNAPSHOT.get()
    return binding == (project.resolve(), os.getpid(), get_ident())


def _stage_manifest_bytes(project: Path, payload: dict[str, Any], *, mirror_path: Path | None = None) -> dict[str, bytes]:
    safe = json_safe(payload)
    if not isinstance(safe, dict):
        raise TypeError("An intake project manifest must be a JSON object.")
    writes = {}
    with TemporaryDirectory(prefix="sciplot-manifest-stage-") as folder:
        for target in _project_manifest_paths(project, mirror_path=mirror_path):
            staged = atomic_write_json(Path(folder) / target.name, safe)
            if _read_manifest_path(staged) != safe:
                raise RuntimeError("The staged intake manifest failed validation.")
            writes[target.name] = staged.read_bytes()
    return writes


def _stage_snapshot(store: FileProjectStore, payload: dict[str, Any], writes: Mapping[str, bytes | Path | PreparedFile | None],
                    snapshot_writer: Callable[[Path, dict[str, Any]], None] | None = None) -> bytes:
    snapshot = store.snapshot()
    if any(not name.startswith("@") for name in snapshot["outside_changes"]):
        raise ProjectConflict("Outside project bytes changed; reconcile them before packaging.")
    with TemporaryDirectory(prefix="sciplot-package-stage-") as folder:
        candidate = Path(folder) / store.root.name
        candidate.mkdir()
        for name in snapshot["files"]:
            if name.startswith("@"):
                continue
            if name in writes and writes[name] is None:
                continue
            target = candidate / name
            target.parent.mkdir(parents=True, exist_ok=True)
            data = writes[name] if name in writes else store.read_bytes(name, generation=snapshot["generation"])
            assert data is not None
            target.write_bytes(data.read_bytes() if isinstance(data, Path) else data.data if isinstance(data, PreparedFile) else data)
            os.utime(target, (315532800, 315532800))
        for name, data in writes.items():
            if not name.startswith("@") and data is not None:
                target = candidate / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data.read_bytes() if isinstance(data, Path) else data.data if isinstance(data, PreparedFile) else data)
                os.utime(target, (315532800, 315532800))
        capability = intake_snapshot_location(store.root, payload)
        assert capability.members is not None
        archive = Path(folder) / capability.members[0]
        token = _PRIVATE_SNAPSHOT.set((candidate.resolve(), os.getpid(), get_ident()))
        try:
            if snapshot_writer is None:
                write_project_archive(candidate, archive)
            else:
                snapshot_writer(candidate, payload)
        finally:
            _PRIVATE_SNAPSHOT.reset(token)
        if not archive.is_file():
            raise RuntimeError("The private project snapshot did not produce its declared ZIP.")
        return archive.read_bytes()


def stage_intake_project_manifest(project: Path, payload: dict[str, Any], *, include_snapshot: bool = True,
                                  store: FileProjectStore | None = None,
                                  mirror_path: Path | None = None,
                                  project_writes: Mapping[str, bytes | Path | PreparedFile | None] | None = None) -> dict[str, bytes]:
    """Build one complete private manifest/mirror/ZIP mutation; never install it."""
    root = project.expanduser().resolve(strict=True)
    selected = store or _manifest_store(root, payload)
    selected.snapshot(import_legacy=True)
    writes = _stage_manifest_bytes(root, payload, mirror_path=mirror_path)
    if include_snapshot:
        resource = intake_snapshot_location(root, payload)
        assert resource.members is not None
        writes["@snapshot/" + resource.members[0]] = _stage_snapshot(selected, payload, {**(project_writes or {}), **writes})
    return writes


def _commit_intake_project_manifest_unlocked(project: Path, payload: dict[str, Any], *,
                                             mirror_path: Path | None = None) -> tuple[Path, ...]:
    store = _manifest_store(project, payload)
    writes = stage_intake_project_manifest(project, payload, include_snapshot=False, store=store, mirror_path=mirror_path)
    publish_files(store, writes, kind="publish", result={"manifest": _CANONICAL_MANIFEST_NAME})
    return _project_manifest_paths(project, mirror_path=mirror_path)


def commit_intake_project_manifest(project_dir: Path, payload: dict[str, Any], *,
                                    mirror_path: Path | None = None) -> tuple[Path, ...]:
    with locked_intake_project_manifest(project_dir) as project:
        return _commit_intake_project_manifest_unlocked(project, payload, mirror_path=mirror_path)


@contextmanager
def edit_intake_project_manifest(project_dir: Path, *, mirror_path: Path | None = None,
                                  require_existing: bool = False) -> Iterator[dict[str, Any] | None]:
    with locked_intake_project_manifest(project_dir) as project:
        payload = _read_intake_project_manifest_unlocked(project)
        if payload is None and require_existing:
            raise FileNotFoundError(f"No Intake project manifest found in {project}.")
        yield payload
        if payload is not None:
            _commit_intake_project_manifest_unlocked(project, payload, mirror_path=mirror_path)


@contextmanager
def edit_intake_project_manifest_with_snapshot(project_dir: Path, *,
        snapshot_writer: Callable[[Path, dict[str, Any]], None], mirror_path: Path | None = None,
        require_existing: bool = False) -> Iterator[dict[str, Any] | None]:
    with locked_intake_project_manifest(project_dir) as project:
        payload = _read_intake_project_manifest_unlocked(project)
        if payload is None and require_existing:
            raise FileNotFoundError(f"No Intake project manifest found in {project}.")
        yield payload
        if payload is None:
            return
        store = _manifest_store(project, payload)
        writes = _stage_manifest_bytes(project, payload, mirror_path=mirror_path)
        resource = intake_snapshot_location(project, payload)
        assert resource.members is not None
        writes["@snapshot/" + resource.members[0]] = _stage_snapshot(store, payload, writes, snapshot_writer)
        publish_files(store, writes, kind="publish", result={"manifest": _CANONICAL_MANIFEST_NAME})


__all__ = ["commit_intake_project_manifest", "edit_intake_project_manifest", "edit_intake_project_manifest_with_snapshot",
           "locked_intake_project_manifest", "read_intake_project_manifest", "stage_intake_project_manifest", "intake_snapshot_location"]
