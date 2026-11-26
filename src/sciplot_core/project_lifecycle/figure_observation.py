"""Read exact saved project figure identities without opening or altering them."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from sciplot_core.delivery_identity import DELIVERY_IDENTITY, delivery_identity_path, read_delivery_binding
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.project_store.io import observe_existing_store
from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.policy import DELIVERY_LAUNCHER
from sciplot_core.studio_core.delivery_target import _managed_project
from sciplot_core.studio_core.figure_set_state import _read_studio_figure_set

from .errors import EngineError


def read_object(path: Path) -> dict[str, Any]:
    canonical_path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def bound_delivery_project(root: Path) -> Path:
    """Identify ownership even when a visible VSZ has outstanding edits."""
    root = canonical_path(root)
    canonical_path(delivery_identity_path(root))
    binding = read_delivery_binding(root)
    if binding is None or binding.request is None:
        raise ValueError("Portable delivery has no associated managed project.")
    project = _managed_project(root, binding)
    if project is None:
        raise ValueError(
            "Portable or relocated delivery has no current project binding."
        )
    canonical_path(resolve_source_path(binding.request))
    if binding.source is not None:
        from sciplot_core.studio_core.project_query_sources import current_source_files

        files, identities = current_source_files(project, Path(binding.source), project_snapshot(project)[2])
        from sciplot_core.project_store.runtime import inspect_runtime_source_file, inspect_runtime_source_tree

        if files:
            for path, digest in files.items():
                inspect_runtime_source_file(path, expected_sha256=digest, source_id=identities.get(path))
        else:
            inspect_runtime_source_tree(binding.source)
    return canonical_path(project)


def resolve_project_path(value: Path) -> Path:
    """Resolve explicit project entries; never discover a project from raw data."""
    path = canonical_path(value)
    if path.is_dir() and (path / "plot_request.json").is_file():
        project = path
    elif path.is_file() and path.name == "plot_request.json":
        project = path.parent
    elif path.is_file() and path.suffix.lower() == ".vsz":
        studio = path.parent.parent if path.parent.name == "figures" else path.parent
        if studio.name == "studio" and (studio.parent / "plot_request.json").is_file():
            project = studio.parent
            _, _, figures = project_snapshot(project)
            if not any(item["document"] == str(path) for item in figures):
                raise ValueError(
                    "The VSZ is not a registered canonical project figure."
                )
        elif path.parent.name == "project":
            project = bound_delivery_project(path.parent.parent)
            binding = read_delivery_binding(path.parent.parent)
            if binding is None or path.name not in dict(binding.documents):
                raise ValueError("The visible VSZ is not registered in this delivery.")
        else:
            raise ValueError("Standalone VSZ has no managed project binding.")
    elif path.is_dir() or path.name in {DELIVERY_LAUNCHER, DELIVERY_IDENTITY}:
        root = path if path.is_dir() else path.parent
        if (root / "plot_request.json").is_file():
            project = root
        else:
            project = bound_delivery_project(root)
    else:
        raise ValueError(
            "Expected a project, plot_request.json, registered VSZ, or bound delivery."
        )
    read_object(project / "plot_request.json")
    canonical_path(project / "studio" / "document.vsz")
    if not (project / "studio" / "document.vsz").is_file():
        raise ValueError("The managed project has no saved canonical document.")
    return project


def project_snapshot(project: Path) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    request = read_object(project / "plot_request.json")
    studio = project / "studio"
    # Legacy path normalization resolves paths. Check the original member paths
    # first so an in-tree symlink cannot disappear during normalization.
    for member in (
        studio / "document.vsz",
        studio / "spec.json",
        studio / "figures",
        *(studio / "figures").glob("*.vsz"),
        *(studio / "figures").glob("*.spec.json"),
    ):
        canonical_path(member)
    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    registry_path = project / "studio" / "figure_set.json"
    canonical_path(registry_path)
    registry = _read_studio_figure_set(
        project, expected_plan=plan, require_ready_artifacts=True
    )
    if registry is None and plan is None and registry_path.is_file():
        # Legacy registries have no task contract. Preserve their read-only
        # identities without upgrading their evidence or permitting escape paths.
        if read_object(registry_path).get("version") == 1:
            registry = _read_studio_figure_set(project)
    if registry is None:
        if registry_path.exists() or plan is not None:
            raise ValueError(
                "The figure-set registry is missing, corrupt, or inconsistent."
            )
        primary_id = "primary"
        entries = [
            {
                "figure_id": primary_id,
                "status": "ready",
                "document": str(project / "studio" / "document.vsz"),
                "spec": str(project / "studio" / "spec.json"),
            }
        ]
    else:
        primary_id = str(registry["primary_figure_id"])
        entries = registry["figures"]
    figures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in entries:
        identity = str(item["figure_id"])
        if identity in seen:
            raise ValueError("Figure identities must be unique within a project.")
        seen.add(identity)
        document, spec = (
            canonical_path(Path(item["document"])),
            canonical_path(Path(item["spec"])),
        )
        if not all(
            path.is_relative_to(project / "studio") for path in (document, spec)
        ):
            raise ValueError("A registered figure path escapes its project.")
        if item.get("status") == "ready" and not all(
            path.is_file() for path in (document, spec)
        ):
            raise ValueError(
                "A ready figure is missing its saved document or specification."
            )
        figures.append(
            {
                "figure_id": identity,
                "title": item.get("title") or identity,
                "primary": identity == primary_id,
                "status": item.get("status"),
                "document": str(document),
                "spec": str(spec),
                "document_sha256": existing_file_sha256(document),
                "spec_sha256": existing_file_sha256(spec),
            }
        )
    if primary_id not in seen or not figures:
        raise ValueError("The project has no registered primary figure.")
    return request, primary_id, figures


def select_figure(
    value: Path, primary_id: str, figures: list[dict[str, Any]], figure_id: str | None
) -> dict[str, Any]:
    identity = figure_id
    if value.suffix.lower() == ".vsz":
        path = canonical_path(value)
        matches = [item for item in figures if item["document"] == str(path)]
        if matches:
            registered = matches[0]["figure_id"]
            if identity is not None and identity != registered:
                raise ValueError("The figure ID does not match this saved VSZ.")
            identity = registered
        elif identity is None and path.parent.name == "project":
            binding = read_delivery_binding(path.parent.parent)
            if binding is None or path.name != binding.primary:
                raise ValueError("Select the figure_id explicitly for a secondary visible VSZ.")
    identity = primary_id if identity is None else identity
    matches = [item for item in figures if item["figure_id"] == identity]
    if not matches:
        raise EngineError(
            "figure_selection_mismatch",
            f"Unknown figure_id: {identity}. Inspect the project without a figure ID to list saved figures.",
            action="inspect_project",
        )
    selected = matches[0]
    if selected["status"] != "ready" or not selected["document_sha256"]:
        raise ValueError(f"The selected figure has no saved document: {identity}")
    return selected


@dataclass(frozen=True)
class LegacyFigureObservation:
    """One saved native registry and its byte witnesses, not publication readiness."""

    target: Path
    project: Path
    request: dict[str, Any]
    request_sha256: str | None
    registry_sha256: str | None
    primary_figure_id: str
    figures: list[dict[str, Any]]

    def select(self, figure_id: str | None = None) -> dict[str, Any]:
        return select_figure(self.target, self.primary_figure_id, self.figures, figure_id)

    def require_current(self, *, selected: dict[str, Any] | None = None) -> None:
        figures = self.figures if selected is None else (selected,)
        if (existing_file_sha256(self.project / "plot_request.json") != self.request_sha256
                or existing_file_sha256(self.project / "studio/figure_set.json") != self.registry_sha256
                or any(existing_file_sha256(Path(figure[field])) != figure[field + "_sha256"]
                       for figure in figures for field in ("document", "spec"))):
            raise EngineError(
                "stale_revision",
                "The saved project changed during inspection. Inspect the project again and use its current document hashes.",
                action="inspect_project",
            )


@observe_existing_store()
def observe_legacy_project(target: Path) -> LegacyFigureObservation:
    """Read the existing native registry, without attaching a semantic writer."""
    project = resolve_project_path(target)
    request_sha = existing_file_sha256(project / "plot_request.json")
    registry_sha = existing_file_sha256(project / "studio/figure_set.json")
    request, primary, figures = project_snapshot(project)
    return LegacyFigureObservation(target, project, request, request_sha, registry_sha, primary, figures)


def resolve_project_figure(project: Path, figure_id: str | None = None) -> dict[str, Any]:
    """Select one exact saved native member without starting a Qt runtime."""
    observation = observe_legacy_project(project)
    selected = observation.select(figure_id)
    observation.require_current(selected=selected)
    return {"project": str(observation.project), **selected}
