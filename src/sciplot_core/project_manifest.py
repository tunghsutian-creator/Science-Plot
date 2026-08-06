"""Read and transactionally commit canonical Intake project state."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from sciplot_core.foundation.json_io import atomic_write_json, read_json_object
from sciplot_core.foundation.json_values import json_safe


_CANONICAL_MANIFEST_NAME = "intake_manifest.json"
_PROJECT_MANIFEST_LOCK = RLock()


@contextmanager
def locked_intake_project_manifest(project_dir: Path) -> Iterator[Path]:
    """Hold the project-state lock for a commit or derived snapshot."""

    project = project_dir.expanduser().resolve()
    with _PROJECT_MANIFEST_LOCK:
        directory_fd = os.open(
            project,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX)
            yield project
        finally:
            try:
                fcntl.flock(directory_fd, fcntl.LOCK_UN)
            finally:
                os.close(directory_fd)


def _validate_manifest_target(path: Path, *, project_dir: Path) -> Path:
    if path.is_symlink():
        raise PermissionError(
            f"Refusing a symlink-backed SciPlot project manifest: {path}"
        )
    if path.parent.resolve() != project_dir:
        raise ValueError("A SciPlot project manifest must stay inside its project.")
    return path


def _project_manifest_paths(
    project_dir: Path,
    *,
    mirror_path: Path | None = None,
) -> tuple[Path, ...]:
    project = project_dir.expanduser().resolve()
    canonical = _validate_manifest_target(
        project / _CANONICAL_MANIFEST_NAME,
        project_dir=project,
    )
    mirrors = [
        _validate_manifest_target(path, project_dir=project)
        for path in sorted(project.glob("*.sciplot.json"))
    ]
    if mirror_path is not None:
        requested_path = mirror_path.expanduser().absolute()
        _validate_manifest_target(requested_path, project_dir=project)
        if requested_path.suffixes[-2:] != [".sciplot", ".json"]:
            raise ValueError(
                "The SciPlot project-manifest mirror must end in `.sciplot.json`."
            )
        requested_mirror = project / requested_path.name
        if requested_mirror not in mirrors:
            mirrors.append(requested_mirror)
    return tuple(dict.fromkeys((canonical, *sorted(mirrors))))


def _read_manifest_path(path: Path) -> dict[str, Any]:
    payload = read_json_object(path)
    if payload is None:
        raise ValueError(f"Expected a readable JSON object at {path}.")
    return payload


def _read_intake_project_manifest_unlocked(
    project: Path,
) -> dict[str, Any] | None:
    candidates: Iterable[Path] = (
        project / _CANONICAL_MANIFEST_NAME,
        *sorted(project.glob("*.sciplot.json")),
    )
    for path in candidates:
        _validate_manifest_target(path, project_dir=project)
        if path.is_file():
            return _read_manifest_path(path)
    return None


def read_intake_project_manifest(project_dir: Path) -> dict[str, Any] | None:
    """Read canonical project state, with the legacy mirror as a fallback."""

    return _read_intake_project_manifest_unlocked(project_dir.expanduser().resolve())


def _commit_intake_project_manifest_unlocked(
    project: Path,
    payload: dict[str, Any],
    *,
    mirror_path: Path | None = None,
) -> tuple[Path, ...]:
    safe_payload = json_safe(payload)
    if not isinstance(safe_payload, dict):
        raise TypeError("An intake project manifest must be a JSON object.")
    targets = _project_manifest_paths(project, mirror_path=mirror_path)
    prior_payloads = {
        path: _read_manifest_path(path) if path.is_file() else None for path in targets
    }
    committed: list[Path] = []
    try:
        for path in targets:
            atomic_write_json(path, safe_payload)
            committed.append(path)
        for path in targets:
            if _read_manifest_path(path) != safe_payload:
                raise RuntimeError(
                    f"Installed intake project manifest failed validation: {path}"
                )
    except BaseException as exc:
        rollback_errors: list[str] = []
        for path in reversed(committed):
            prior = prior_payloads[path]
            try:
                if prior is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_json(path, prior)
            except BaseException as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "Intake project manifest commit failed and rollback was "
                "incomplete: " + "; ".join(rollback_errors)
            ) from exc
        raise
    return targets


def commit_intake_project_manifest(
    project_dir: Path,
    payload: dict[str, Any],
    *,
    mirror_path: Path | None = None,
) -> tuple[Path, ...]:
    """Replace canonical state and compatibility mirrors with rollback.

    Each file replacement is atomic. The canonical manifest is authoritative;
    compatibility mirrors receive the same payload. If a later replacement
    fails, earlier replacements are restored to their previous JSON objects.
    Use :func:`edit_intake_project_manifest` for read-modify-write updates.
    """

    with locked_intake_project_manifest(project_dir) as project:
        return _commit_intake_project_manifest_unlocked(
            project,
            payload,
            mirror_path=mirror_path,
        )


@contextmanager
def edit_intake_project_manifest(
    project_dir: Path,
    *,
    mirror_path: Path | None = None,
    require_existing: bool = False,
) -> Iterator[dict[str, Any] | None]:
    """Edit current project state under one cross-process transaction lock."""

    with locked_intake_project_manifest(project_dir) as project:
        payload = _read_intake_project_manifest_unlocked(project)
        if payload is None and require_existing:
            raise FileNotFoundError(f"No Intake project manifest found in {project}.")
        yield payload
        if payload is not None:
            _commit_intake_project_manifest_unlocked(
                project,
                payload,
                mirror_path=mirror_path,
            )


@contextmanager
def edit_intake_project_manifest_with_snapshot(
    project_dir: Path,
    *,
    snapshot_writer: Callable[[Path, dict[str, Any]], None],
    mirror_path: Path | None = None,
    require_existing: bool = False,
) -> Iterator[dict[str, Any] | None]:
    """Commit manifests and one derived snapshot with rollback under one lock."""

    with locked_intake_project_manifest(project_dir) as project:
        payload = _read_intake_project_manifest_unlocked(project)
        if payload is None and require_existing:
            raise FileNotFoundError(f"No Intake project manifest found in {project}.")
        prior_payload = deepcopy(payload)
        yield payload
        if payload is None:
            return
        _commit_intake_project_manifest_unlocked(
            project,
            payload,
            mirror_path=mirror_path,
        )
        try:
            snapshot_writer(project, payload)
        except BaseException as exc:
            if prior_payload is None:
                raise RuntimeError(
                    "The derived project snapshot failed after creating a new "
                    "manifest generation; automatic rollback is unavailable."
                ) from exc
            try:
                _commit_intake_project_manifest_unlocked(
                    project,
                    prior_payload,
                    mirror_path=mirror_path,
                )
            except BaseException as rollback_exc:
                raise RuntimeError(
                    "The derived project snapshot failed and manifest rollback "
                    f"was incomplete: {rollback_exc}"
                ) from exc
            raise


__all__ = [
    "commit_intake_project_manifest",
    "edit_intake_project_manifest",
    "edit_intake_project_manifest_with_snapshot",
    "locked_intake_project_manifest",
    "read_intake_project_manifest",
]
