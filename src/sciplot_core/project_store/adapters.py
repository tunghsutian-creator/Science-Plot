"""Compatibility storage ports delegate writes to the one command repository."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation

from .io import StoreIO, owned_io
from .repository import FileProjectStore
from .resources import ResourceRoot
from . import projection, state


def store_for_project(project: Path, *, locations: Mapping[str, Path | ResourceRoot] | None = None) -> FileProjectStore:
    root = project.expanduser().resolve(strict=True)
    active = owned_io(root)
    if active is not None:
        capabilities = {key: ResourceRoot(path, active.location_members[key]) for key, path in active.locations.items()}
        if locations is not None and capabilities != dict(locations):
            raise ValueError("An active project scope cannot change trusted resource capabilities.")
        return FileProjectStore(root, locations=capabilities)
    return FileProjectStore(root, locations=locations)


@contextmanager
def project_storage_scope(project: Path, *, locations: Mapping[str, Path | ResourceRoot] | None = None) -> Iterator[FileProjectStore]:
    store = store_for_project(project, locations=locations)
    with StoreIO(store.root, store.locations, store.location_members).locked(blocking=True) as io:
        current = state.head(io)
        if current is None:
            current = state.import_legacy(io)
        projection.recover(io, current)
        yield store


def publish_files(store: FileProjectStore, writes: Mapping[str, bytes | Path | None], *,
                  kind: str, baseline: dict[str, Any] | None = None,
                  result: dict[str, Any] | None = None,
                  artifacts: Mapping[str, bytes | Path] | None = None) -> dict[str, Any]:
    snapshot = store.snapshot(import_legacy=True)
    expected = baseline or {"project_id": snapshot["project_id"], "generation": snapshot["generation"],
        "files": {name: snapshot["files"].get(name, {}).get("sha256") for name in writes}}
    if expected["project_id"] != snapshot["project_id"]:
        raise ValueError("The editing baseline belongs to another stable project.")
    reads = dict(expected["files"])
    for name in writes:
        if name not in reads:
            raise ValueError("The editing session did not observe this save destination.")
    from sciplot_core.project_commands.contracts import ProjectionRead

    projected = [ProjectionRead(**item) for item in expected.get("projected_reads", [])]
    command = ProjectCommand.create(kind, uuid4().hex, project_id=snapshot["project_id"],
        expected_generation=expected["generation"], read_set=reads, write_set=sorted(writes),
        request={"storage_adapter": kind, "resources": sorted(writes)}, projected_reads=projected)
    return ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, result or {}, artifacts=artifacts or {}))
