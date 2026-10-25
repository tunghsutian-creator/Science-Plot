"""Host-only resource capabilities for every recognized project entry point."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_manifest_locations import admitted_intake_manifest, admitted_project_generation, intake_snapshot_location
from sciplot_core.project_store.io import StoreIO, owned_io
from sciplot_core.project_store.adapters import store_for_project


def _admitted_project(project: Path, *, intake_compat: bool = False) -> tuple[dict[str, Any], frozenset[str]]:
    claims: frozenset[str] = frozenset()
    path = project / "plot_request.json"
    if not (project / ".sciplot_store/head.json").is_file():
        canonical_path(path)
        value = json.loads(path.read_bytes()) if path.is_file() else {}
    else:
        from sciplot_core.project_store import ProjectConflict
        from sciplot_core.project_store import projection

        # Only immutable admitted request bytes can select a host output root.
        # A pending head may still have its exact predecessor projection; its
        # sealed request selects caps, while explicit resume owns all repair.
        with admitted_project_generation(project, blocking=intake_compat) as (_primary, io, current):
            claims = frozenset(current.get("resource_roots", {}))
            entry = current["files"].get("plot_request.json")
            if entry is None:
                if intake_compat and io.physical("plot_request.json") is None:
                    return {}, claims  # Manifest-only Intake is a supported creation state.
                raise ProjectConflict("The admitted project has no canonical request")
            admitted = io.get(entry)
            actual = io.physical("plot_request.json")
            allowed: set[tuple[bytes, int] | None] = {(admitted, entry["mode"])}
            if projection.pending(io, current):
                from sciplot_core.project_store import state, commands

                for key, outcome in current["commands"].items():
                    record = state.command(io, key)
                    if (record is not None and record.get("phase") != "complete"
                            and record.get("install_generation") == current["generation"]
                            and record.get("install_parent") == current.get("parent")
                            and outcome.get("generation") == current["generation"]):
                        commands.public(io, record, projection_pending=True)
                        parent = state.reachable(io, current, record["install_parent"])
                        previous = parent["files"].get("plot_request.json")
                        allowed.add((io.get(previous), previous["mode"]) if previous else None)
            if actual not in allowed:
                raise ProjectConflict("The canonical request differs from its admitted generation; external roots were not selected")
            value = json.loads(admitted)
    if not isinstance(value, dict):
        raise ValueError("The canonical project request must be an object")
    return value, claims


def _admitted_request(project: Path) -> dict[str, Any]:
    return _admitted_project(project)[0]


def _run_output_capability(project: Path, request: dict[str, Any], locations: dict[str, Any], *,
                           create: bool, claims: frozenset[str]) -> None:
    from sciplot_core.project_store import ProjectRecoveryRequired, ResourceRoot

    value = request.get("output")
    if not isinstance(value, str) or not value.strip():
        return
    output = canonical_path(Path(value) if Path(value).is_absolute() else project / value)
    key = "run_" + canonical_json_sha256(str(output))[:16]
    if not create and key not in claims:
        return  # Unused legacy render outputs do not acquire another authority.
    if project.is_relative_to(output):
        raise ValueError("An external run output cannot contain its source project")
    source_value = request.get("input")
    if isinstance(source_value, str) and source_value:
        source = canonical_path(Path(source_value) if Path(source_value).is_absolute() else project / source_value)
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("An external run output cannot overlap its scientific input")
    if any(output.is_relative_to(project / name) for name in ("raw", "source")):
        raise ValueError("A run output cannot overlap preserved scientific source members")
    if output.is_relative_to(project):
        return
    for supplied in locations.values():
        cap = supplied if isinstance(supplied, ResourceRoot) else ResourceRoot(supplied)
        root = Path(cap.path)
        if output.is_relative_to(root):
            relative = output.relative_to(root).as_posix()
            if cap.members is None or relative in cap.members or any(name.startswith(relative + "/") for name in cap.members):
                return
    if not output.exists():
        if key in claims:
            raise ProjectRecoveryRequired("The registered external run root is missing; explicit recovery is required")
        if not create:
            return
        output.mkdir(parents=True, exist_ok=False)
    if not output.is_dir():
        raise ValueError("The declared external run output must be a dedicated directory")
    locations[key] = output


def _snapshot_members(project: Path, *, blocking: bool = False) -> set[str]:
    """Retain finite archive members already admitted by exact host commands."""
    members: set[str] = set()
    with admitted_project_generation(project, blocking=blocking) as (primary, _io, current):
        names = list(current["files"])
        for record in primary.commands():
            names.extend(record.get("write_set", record.get("metadata", {}).get("write_set", [])))
        for name in names:
            components = str(name).split("/")
            if (len(components) == 2 and components[0] == "@snapshot" and components[1].endswith(".zip")
                    and components[1] not in {".zip", "..zip"} and "\\" not in components[1]):
                members.add(components[1])
    return members


def project_store(project: Path, *, create_delivery: bool = False, with_snapshot: bool = False,
                  create_output: bool = False, intake_compat: bool = False,
                  snapshot_payload: dict[str, Any] | None = None) -> FileProjectStore:
    """Select only the host's already-bound delivery root, never a wire mount."""
    project = canonical_path(project)
    if owned_io(project) is not None:
        return store_for_project(project)
    request, claims = _admitted_project(project, intake_compat=intake_compat)
    if (project / ".sciplot_store" / "local_locations.json").exists():
        with StoreIO(project, {}).locked(blocking=intake_compat):
            repository = FileProjectStore(project)
        if with_snapshot and "snapshot" not in repository.locations:
            from sciplot_core.project_store import ResourceRoot

            manifest = admitted_intake_manifest(project, initial=snapshot_payload, blocking=intake_compat)
            if manifest is not None or intake_compat:
                locations: dict[str, Any] = {key: ResourceRoot(path, repository.location_members[key])
                                             for key, path in repository.locations.items()}
                locations["snapshot"] = intake_snapshot_location(project, manifest or {})
                return FileProjectStore(project, locations=locations)
        return repository
    raw_delivery = request.get("delivery_output")
    if isinstance(raw_delivery, str) and raw_delivery.strip():
        canonical_path(Path(raw_delivery))  # Validate before the legacy resolver normalizes it.
    delivery = canonical_path(requested_delivery_root({"request": request}, run_output=project))
    if create_delivery:
        delivery.mkdir(parents=True, exist_ok=True)
    selected_locations: dict[str, Any] = {"delivery": delivery} if delivery.is_dir() and not delivery.is_relative_to(project) else {}
    if with_snapshot or "snapshot" in claims:
        manifest = admitted_intake_manifest(project, initial=snapshot_payload, blocking=intake_compat)
        if manifest is not None or intake_compat or "snapshot" in claims:
            selected_locations["snapshot"] = intake_snapshot_location(project, manifest or {})
    _run_output_capability(project, request, selected_locations, create=create_output, claims=claims)
    repository = FileProjectStore(project, locations=selected_locations)
    if (project / ".sciplot_store/head.json").is_file():
        members = _snapshot_members(project, blocking=intake_compat)
        if members:
            from sciplot_core.project_store import ResourceRoot

            existing = selected_locations.get("snapshot")
            if existing is not None:
                members.update(existing.members or ())
            selected_locations["snapshot"] = ResourceRoot(
                existing.path if existing is not None else project.parent, tuple(sorted(members)))
            repository = FileProjectStore(project, locations=selected_locations)
    return repository

