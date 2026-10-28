"""Compose native use cases with the shared project command/store contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar, cast

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import MembershipRead, NativeAdoption, ProjectCommand, ProjectCommands, ProjectionRead, MissingGeneratedOutput
from sciplot_core.project_commands.read_projections import projection_digest
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_host_factory import (
    _admitted_project as _admitted_project, _admitted_request as _admitted_request,
    _run_output_capability as _run_output_capability, project_store as project_store,
)
from sciplot_core.project_store.runtime import project_runtime, resolve_runtime_path
from sciplot_core.source_coverage.managed_documents import source_records
from sciplot_core.studio_core.project_query_paths import canonical_path

_P = ParamSpec("_P")
_R = TypeVar("_R")


def project_command_runtime(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """Pin actual scientific IO for a complete public native use case."""
    @wraps(function)
    def invoke(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        value = args[0] if args else kwargs.get("project_dir", kwargs.get("project"))
        from sciplot_core.studio_core.project_query_paths import resolve_project_path

        project = resolve_project_path(cast(Path, value))
        repository = project_store(project)
        repository.snapshot(import_legacy=True)
        with project_runtime(repository):
            return function(*args, **kwargs)

    return invoke


def project_read_runtime(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """Read an existing generation without importing or repairing a project."""
    @wraps(function)
    def invoke(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        value = args[0] if args else kwargs.get("project_dir", kwargs.get("project"))
        from sciplot_core.studio_core.project_query_paths import resolve_project_path

        project = resolve_project_path(cast(Path, value))
        if not (project / ".sciplot_store").exists():
            return function(*args, **kwargs)
        with project_runtime(project_store(project)):
            return function(*args, **kwargs)

    return invoke


def figure_read_state(project: Path, selected: dict[str, Any]) -> dict[str, Any]:
    """The actual selected native/spec/source reads, independent of publication."""
    project = canonical_path(project)
    document, spec = canonical_path(Path(selected["document"])), canonical_path(Path(selected["spec"]))
    if any(not path.is_relative_to(project) for path in (document, spec)):
        raise ValueError("The selected native figure must remain inside its project")
    paths = {project / "plot_request.json", document, spec}
    sources: dict[str, str] = {}
    for source, expected in source_records(json.loads(spec.read_text())).items():
        path = canonical_path(resolve_runtime_path(source, expected_sha256=expected))
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError("A selected native scientific source changed")
        if path.is_relative_to(project) and path.relative_to(project).parts[0] not in {".sciplot_store", ".sciplot_resources"}:
            paths.add(path)
        else:
            sources[str(source)] = actual
    files = {path.relative_to(project).as_posix(): file_sha256(path) for path in sorted(paths)}
    registry = project / "studio" / "figure_set.json"
    projected = []
    if registry.is_file():
        kind, key = "studio_figure_v1", str(selected["figure_id"])
        projected.append(ProjectionRead("studio/figure_set.json", kind, key,
                                        projection_digest(registry.read_bytes(), kind=kind, key=key)).to_payload())
    return {"project_files": files, "source_files": sources, "projected_reads": projected}


def figure_binding(project: Path, selected: dict[str, Any], *, store: FileProjectStore | None = None) -> dict[str, Any]:
    repository = store or project_store(project)
    snapshot = repository.snapshot(import_legacy=True)
    reads = figure_read_state(project, selected)
    for logical, digest in reads["project_files"].items():
        if snapshot["files"].get(logical, {}).get("sha256") != digest:
            raise ValueError("The selected native figure has unregistered outside changes")
    return {"project_id": snapshot["project_id"], "generation": snapshot["generation"],
            "files": reads["project_files"], "projected_reads": reads["projected_reads"],
            "source_files": reads["source_files"]}


def adopt_saved_native(project: Path, selected: dict[str, Any], *,
                       expected_binding: dict[str, Any] | None = None) -> dict[str, Any]:
    """Register one audited Legacy save; retain an explicit mutation's read witness."""
    from sciplot_core.project_commands import ProjectMutation
    from sciplot_core.studio_core.native_scientific_audit import audit_edited_document

    repository = project_store(project)
    reads = figure_read_state(project, selected)
    before = repository.snapshot(import_legacy=True)
    document = Path(selected["document"])
    logical = repository.logical_path(document)
    expected = before["files"].get(logical, {}).get("sha256")
    observed = file_sha256(document)
    if (selected.get("document_sha256", observed) != observed
            or selected.get("spec_sha256", reads["project_files"][repository.logical_path(Path(selected["spec"]))])
            != reads["project_files"][repository.logical_path(Path(selected["spec"]))]):
        raise ValueError("The selected saved native or specification revision is stale")
    if expected_binding is not None and (
        expected_binding["project_id"] != before["project_id"]
        or expected_binding["files"] != reads["project_files"]
        or expected_binding.get("projected_reads", []) != reads["projected_reads"]
        or expected_binding.get("source_files", {}) != reads["source_files"]
    ):
        raise ValueError("The saved native baseline changed before mutation admission")
    if expected == observed:
        return figure_binding(project, selected, store=repository)
    if expected is None:
        raise ValueError("An unknown native member cannot be adopted as a saved Legacy figure")
    audit = audit_edited_document(document, Path(selected["spec"]))
    if audit.get("document_sha256") != observed:
        raise ValueError("The saved Legacy native audit does not bind these exact observed bytes")
    from sciplot_core.studio_core.observed_figure_binding import observed_figure_binding

    binding = observed_figure_binding(project, {**selected, "document_sha256": observed}, audit)
    audit_hash = canonical_json_sha256(audit)
    request = {"family": "saved_legacy_native", "resource": logical,
               "before_sha256": expected, "observed_sha256": observed, "audit_sha256": audit_hash}
    key = canonical_json_sha256({"project_id": before["project_id"], "request": request})
    command = command_for_binding(repository, binding, kind="native_import", key=key, writes=[logical], request=request,
        native_adoptions=[NativeAdoption(logical, expected, observed, audit_hash)])
    ProjectCommands(repository).execute(command, lambda: ProjectMutation({logical: document}, request,
        sources=source_versions(binding, store=repository), artifacts={"audit.json": json.dumps(audit, ensure_ascii=False).encode()}))
    return figure_binding(project, selected, store=repository)


def command_for_binding(store: FileProjectStore, binding: dict[str, Any], *, kind: str, key: str,
                        writes: list[str], request: dict[str, Any],
                        projected_writes: list[ProjectionRead] | None = None,
                        native_adoptions: list[NativeAdoption] | None = None,
                        missing_outputs: tuple[MissingGeneratedOutput, ...] = ()) -> ProjectCommand:
    reads = dict(binding["files"])
    snapshot = store.snapshot()
    for logical in writes:
        if logical not in reads and not any(item.resource == logical for item in projected_writes or ()):
            reads[logical] = snapshot["files"].get(logical, {}).get("sha256")
    return ProjectCommand.create(
        kind, key, project_id=binding["project_id"], expected_generation=binding["generation"],
        read_set=reads, write_set=writes, request=request,
        expected_revision=canonical_json_sha256({"files": binding["files"],
            "projected_reads": binding.get("projected_reads", []), "source_files": binding.get("source_files", {})}),
        projected_reads=[ProjectionRead(**item) for item in binding.get("projected_reads", [])],
        projected_writes=projected_writes or (), native_adoptions=native_adoptions or (),
        read_memberships=[MembershipRead(**item) for item in binding.get("read_memberships", [])],
        missing_outputs=missing_outputs)


def whole_memberships(store: FileProjectStore, snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return [MembershipRead.capture(snapshot["files"], prefix).to_payload()
            for prefix in ("", *("@" + name for name in sorted(store.locations)))]


def source_versions(binding: dict[str, Any], *, store: FileProjectStore | None = None) -> list[dict[str, str]]:
    snapshot = store.snapshot() if store is not None else {"sources": {}}
    result = []
    for path, digest in sorted(binding.get("source_files", {}).items()):
        known = [identity for identity, versions in snapshot["sources"].items()
                 if versions.get(digest, {}).get("locator") == path]
        if len(known) > 1:
            raise ValueError("The source literal and version have ambiguous registered identities")
        identity = known[0] if known else canonical_json_sha256({"project_id": binding["project_id"], "locator": path})[:32]
        result.append({"source_id": identity, "path": str(resolve_runtime_path(path, expected_sha256=digest)),
                       "version": digest, "locator": path})
    return result


def command_result(record: dict[str, Any]) -> dict[str, Any]:
    """Project the one canonical receipt; no independent durable status is kept."""
    if record.get("phase") != "complete":
        from sciplot_core.project_commands import ProjectCommandUnknown

        raise ProjectCommandUnknown()
    return {**record["result"], "project_command": {name: record[name] for name in (
        "command_id", "command_digest", "project_id", "generation", "phase")},
        "artifact_paths": record.get("artifact_paths", {})}


def application(project: Path) -> ProjectCommands:
    return ProjectCommands(project_store(project))


def query_for_apply(app: ProjectCommands, key: str) -> dict[str, Any] | None:
    return app.query(key)
