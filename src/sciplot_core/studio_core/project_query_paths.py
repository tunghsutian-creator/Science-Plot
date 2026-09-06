"""Read-only managed project and registered figure identity resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.launchers.delivery_binding import delivery_binding_from_content
from sciplot_core.launchers.delivery_inspection import (
    inspect_delivery_launcher_contract,
)
from sciplot_core.policy import DELIVERY_LAUNCHER
from sciplot_core.studio_core.delivery_target import _managed_project
from sciplot_core.studio_core.figure_set_state import _read_studio_figure_set


def canonical_path(value: Path) -> Path:
    path = value.expanduser().absolute()
    if any(member.is_symlink() for member in (path, *path.parents)):
        raise ValueError(f"Managed project queries cannot follow a symlink: {path}")
    return path.resolve()


def read_object(path: Path) -> dict[str, Any]:
    canonical_path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def bound_delivery_project(root: Path) -> Path:
    """Identify ownership even when a visible VSZ has outstanding edits."""
    root = canonical_path(root)
    launcher = canonical_path(root / DELIVERY_LAUNCHER)
    if inspect_delivery_launcher_contract(root).get("ready") is not True:
        raise ValueError(f"The delivery has no valid SciPlot launcher: {root}")
    binding = delivery_binding_from_content(launcher.read_text(encoding="utf-8"))
    if binding is None or binding.request is None:
        raise ValueError("Portable delivery has no associated managed project.")
    canonical_path(Path(binding.request))
    if binding.source is not None:
        if not canonical_path(Path(binding.source)).exists():
            raise ValueError("The delivery's associated project source is missing.")
    project = _managed_project(root, binding)
    if project is None:
        raise ValueError(
            "Portable or relocated delivery has no current project binding."
        )
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
            binding = delivery_binding_from_content(
                (path.parent.parent / DELIVERY_LAUNCHER).read_text(encoding="utf-8")
            )
            if binding is None or path.name not in dict(binding.documents):
                raise ValueError("The visible VSZ is not registered in this delivery.")
        else:
            raise ValueError("Standalone VSZ has no managed project binding.")
    elif path.is_dir() or path.name == DELIVERY_LAUNCHER:
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
    if identity is None and value.suffix.lower() == ".vsz":
        path = canonical_path(value)
        matches = [item for item in figures if item["document"] == str(path)]
        if matches:
            identity = matches[0]["figure_id"]
        elif path.parent.name == "project":
            binding = delivery_binding_from_content(
                (path.parent.parent / DELIVERY_LAUNCHER).read_text(encoding="utf-8")
            )
            if binding is None or path.name != binding.primary:
                raise ValueError(
                    "Select the figure_id explicitly for a secondary visible VSZ."
                )
    identity = identity or primary_id
    matches = [item for item in figures if item["figure_id"] == identity]
    if not matches:
        raise ValueError(f"Unknown figure_id: {identity}")
    selected = matches[0]
    if selected["status"] != "ready" or not selected["document_sha256"]:
        raise ValueError(f"The selected figure has no saved document: {identity}")
    return selected
