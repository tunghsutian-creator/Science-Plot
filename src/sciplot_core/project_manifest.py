"""Intake compatibility views delegate to complete immutable project generations."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
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
from sciplot_core.foundation.project_archives import write_project_archive
from sciplot_core.foundation.private_project_manifest import (
    private_manifest_descriptor,
    private_project_manifest_scope as private_project_manifest_scope,
)
from sciplot_core.project_commands.resources import NativeAdoption, PreparedFile
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_manifest_locations import (
    _CANONICAL_MANIFEST_NAME, _project_manifest_paths as _project_manifest_paths,
    intake_snapshot_location as intake_snapshot_location,
)
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ResourceRoot
from sciplot_core.project_store.adapters import project_storage_scope, publish_files
from sciplot_core.project_store.io import install, parts, read_file, sha

_PROJECT_MANIFEST_LOCK = RLock()
_PRIVATE_SNAPSHOT: ContextVar[tuple[Path, int, int] | None] = ContextVar("intake_private_snapshot", default=None)

def _read_manifest_path(path: Path) -> dict[str, Any]:
    value = read_json_object(path)
    if value is None:
        raise ValueError(f"Expected a readable JSON object at {path}.")
    return value

def _manifest_store(project: Path, payload: dict[str, Any] | None = None) -> FileProjectStore:
    if private_manifest_descriptor(project) is not None:
        raise ValueError("A private producer returns candidate bytes; it cannot create a project generation.")
    return project_store(project, with_snapshot=True, intake_compat=True, snapshot_payload=payload)


@contextmanager
def locked_intake_project_manifest(project_dir: Path) -> Iterator[Path]:
    project = project_dir.expanduser().resolve(strict=True)
    with _PROJECT_MANIFEST_LOCK:
        if private_manifest_descriptor(project) is not None:
            yield project
            private_manifest_descriptor(project)
            return
        store = _manifest_store(project)
        capabilities = {key: ResourceRoot(path, store.location_members[key]) for key, path in store.locations.items()}
        with project_storage_scope(project, locations=capabilities):
            yield project


def _read_intake_project_manifest_unlocked(project: Path, *, store: FileProjectStore | None = None) -> dict[str, Any] | None:
    private = private_manifest_descriptor(project)
    targets = _project_manifest_paths(project)
    if private is not None:
        for path in targets:
            try:
                data, _mode = read_file(private, path.name, owned=True)
            except FileNotFoundError:
                continue
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("A private candidate manifest must be one object.")
            return value
        return None
    if (project / ".sciplot_store/head.json").is_file():
        selected = store or _manifest_store(project)
        if selected.root != project:
            raise ValueError("The selected manifest store belongs to another project.")
        with selected._locked() as (io, current):
            for path in targets:
                if path.name in current["files"]:
                    entry = current["files"][path.name]
                    data = io.get(entry)
                    physical = io.physical(path.name)
                    if physical is None or physical != (data, entry["mode"]):
                        raise ProjectConflict("The visible project manifest differs from its committed generation.")
                    value = json.loads(data)
                    if not isinstance(value, dict):
                        raise ValueError("The project manifest generation is invalid.")
                    return value
        return None
    for path in targets:
        if path.is_file():
            return _read_manifest_path(path)
    return None


def read_intake_project_manifest(project_dir: Path, *, store: FileProjectStore | None = None) -> dict[str, Any] | None:
    return _read_intake_project_manifest_unlocked(project_dir.expanduser().resolve(), store=store)


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


def _captured_project_write(value: bytes | Path | PreparedFile) -> PreparedFile:
    if isinstance(value, PreparedFile):
        value.__post_init__()
        return value
    if isinstance(value, bytes):
        return PreparedFile(value, 0o600)
    descriptor = os.open(value.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        data, mode = read_file(descriptor, value.name, owned=True)
        return PreparedFile(data, mode)
    finally:
        os.close(descriptor)


def _write_snapshot_member(candidate: Path, name: str, value: bytes | Path | PreparedFile) -> None:
    parts(name)
    prepared = _captured_project_write(value)
    target = candidate / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(prepared.data)
    target.chmod(prepared.mode)
    os.utime(target, (315532800, 315532800))


def _stage_snapshot(store: FileProjectStore, payload: dict[str, Any], writes: Mapping[str, bytes | Path | PreparedFile | None],
                    snapshot_writer: Callable[[Path, dict[str, Any]], None] | None = None, *,
                    native_adoptions: Sequence[NativeAdoption] = ()) -> bytes:
    snapshot = store.snapshot()
    adopted = {item.resource: item for item in native_adoptions}
    if len(adopted) != len(native_adoptions):
        raise ProjectConflict("A snapshot native observation must identify one exact pending write.")
    for name, observed in snapshot["outside_changes"].items():
        if name.startswith("@"):
            continue
        proof, value, previous = adopted.get(name), writes.get(name), snapshot["files"].get(name)
        if proof is None or value is None or previous is None or name in snapshot.get("input_resources", []):
            raise ProjectConflict("Outside project bytes changed; reconcile them before packaging.")
        captured = _captured_project_write(value)
        if (proof.before_sha256 != previous["sha256"] or proof.observed_sha256 != observed
                or sha(captured.data) != observed or captured.mode != previous["mode"]):
            raise ProjectConflict("The snapshot native overlay differs from its audited pending adoption.")
    with TemporaryDirectory(prefix="sciplot-package-stage-") as folder:
        candidate = Path(folder) / store.root.name
        candidate.mkdir()
        for name in snapshot["files"]:
            if name.startswith("@"):
                continue
            if name in writes and writes[name] is None:
                continue
            data = writes[name] if name in writes else PreparedFile(
                store.read_bytes(name, generation=snapshot["generation"]), snapshot["files"][name]["mode"])
            assert data is not None
            _write_snapshot_member(candidate, name, data)
        for name, data in writes.items():
            if not name.startswith("@") and data is not None:
                _write_snapshot_member(candidate, name, data)
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
                                  project_writes: Mapping[str, bytes | Path | PreparedFile | None] | None = None,
                                  native_adoptions: Sequence[NativeAdoption] = ()) -> dict[str, bytes | PreparedFile | None]:
    """Build one complete private manifest/mirror/ZIP mutation; never install it."""
    root = project.expanduser().resolve(strict=True)
    selected = store or _manifest_store(root, payload)
    selected.snapshot(import_legacy=True)
    writes: dict[str, bytes | PreparedFile | None] = {}
    for name, value in (project_writes or {}).items():
        components = parts(name)
        if name.startswith("@") or components[0] == ".sciplot_resources":
            raise ValueError("Project snapshot overlays must use project members, not external resource roots.")
        writes[name] = _captured_project_write(value) if value is not None else None
    writes.update(_stage_manifest_bytes(root, payload, mirror_path=mirror_path))
    if include_snapshot:
        resource = intake_snapshot_location(root, payload)
        assert resource.members is not None
        writes["@snapshot/" + resource.members[0]] = _stage_snapshot(selected, payload, writes, native_adoptions=native_adoptions)
    return writes


def _commit_intake_project_manifest_unlocked(project: Path, payload: dict[str, Any], *,
                                             mirror_path: Path | None = None) -> tuple[Path, ...]:
    private = private_manifest_descriptor(project)
    if private is not None:
        private_writes = _stage_manifest_bytes(project, payload, mirror_path=mirror_path)
        for name, data in private_writes.items():
            private_manifest_descriptor(project)
            install(private, name, data, mode=0o600)
        private_manifest_descriptor(project)
        return _project_manifest_paths(project, mirror_path=mirror_path)
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
