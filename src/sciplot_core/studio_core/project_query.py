"""Read the saved managed project for external clients without preparing it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core.source_tables.read_session import with_table_reads
from sciplot_core.source_coverage.native_file_snapshots import observed_native_document
from sciplot_core.studio_core.document_edit_policy import filter_editable_fields
from sciplot_core.studio_core.sample_style import sample_style_targets
from sciplot_core.studio_core.project_query_evidence import (
    publication_indicators,
    source_indicators,
)
from sciplot_core.project_lifecycle.figure_observation import (
    LegacyFigureObservation,
    observe_legacy_project,
    observe_plot_head,
)
from sciplot_core.veusz_runtime import veusz_worker_environment
from sciplot_core.native_process import run_worker
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store.io import observe_existing_store
from sciplot_core.project_store.source_resolver import query_sources


def _inspect_document(document: Path) -> dict[str, Any]:
    arguments = ["inspect-document-state", str(document)]
    with observed_native_document(arguments, document):
        completed = run_worker(
            [sys.executable, "-m", "sciplot_core.veusz_worker", *arguments],
            env=veusz_worker_environment(), cold_runner=subprocess.run,
            capture_output=True,
            text=True,
            timeout=120,
        )
    if completed.returncode:
        raise RuntimeError(
            f"Cannot inspect the saved Veusz document: {completed.stderr.strip()}"
        )
    payload = json.loads(completed.stdout)
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "sciplot_veusz_document_state"
        or payload.get("version") != 1
        or payload.get("status") != "passed"
        or not isinstance(payload.get("widgets"), dict)
    ):
        raise ValueError("The document worker returned an invalid inspection.")
    return payload


@with_table_reads
def _inspect_legacy_project(
    observation: LegacyFigureObservation,
    *,
    figure_id: str | None = None,
    object_path: str | None = None,
    native: bool | None = None,
    include_annotations: bool = False,
    include_axes: bool = False,
) -> dict[str, Any]:
    """Return current byte identities and separately labelled historical evidence.

    ``status=ok`` only means the query succeeded. No rendering, scientific audit,
    human review, publication, or readiness certification is performed here.
    """
    root, request, figures = observation.project, observation.request, observation.figures
    selection_requested = (figure_id is not None or object_path is not None or native is not None
                           or include_annotations or include_axes)
    selected = observation.select(figure_id) if selection_requested else None
    selected_metadata: dict[str, Any] = {}
    for figure in figures:
        spec = json.loads(Path(figure["spec"]).read_text())
        figure["sample_styles"] = sample_style_targets(spec)
        if figure is selected:
            if include_annotations:
                from sciplot_core.studio_core.annotation_contracts import annotation_records

                selected_metadata["annotations"] = annotation_records(spec)
            if include_axes:
                from sciplot_core.studio_core.annotation_axes import axis_unit

                selected_metadata["axes"] = {
                    axis: {"unit": axis_unit(spec, axis), **{key: spec["axes"][axis][key]
                            for key in ("label", "min", "max", "scale")}}
                    for axis in ("x", "y")}
    source = source_indicators(root, request, figures)
    payload: dict[str, Any] = {
        "kind": "sciplot_project_inspection",
        "version": 1,
        "status": "ok",
        "project": str(root),
        "request": str(root / "plot_request.json"),
        "request_sha256": observation.request_sha256,
        "primary_figure_id": observation.primary_figure_id,
        "figures": figures,
        "source": source,
        **publication_indicators(root, request, figures, source),
        "ready_to_use": None,
        "readiness_evaluated": False,
        "document_authority": "saved_vsz",
        "live_gui_state_evaluated": False,
    }
    if selected is not None:
        payload["selected_figure"] = {**selected, **selected_metadata}
    inspect_native = native if native is not None else (figure_id is not None or object_path is not None)
    if inspect_native or object_path is not None:
        figure = selected or observation.select(figure_id)
        state = _inspect_document(Path(figure["document"]))
        if state.get("document") != {
            "path": figure["document"],
            "sha256": figure["document_sha256"],
        }:
            raise ValueError(
                "The saved document changed during inspection; query again."
            )
        widgets = filter_editable_fields(state["widgets"], Path(figure["spec"]))
        if object_path is not None:
            if object_path not in widgets:
                raise ValueError(
                    f"Unknown object_path in this saved figure: {object_path}"
                )
            widgets = {object_path: widgets[object_path]}
        payload["selected_figure"] = {
            **figure,
            **selected_metadata,
            "objects": {
                path: {
                    **value,
                    "target": {
                        "figure_id": figure["figure_id"],
                        "object_path": path,
                        "document_sha256": figure["document_sha256"],
                    },
                }
                for path, value in widgets.items()
            },
            "object_count": len(widgets),
        }
    observation.require_current()
    return payload


def _creation_history(plot: Path, document: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    from sciplot_core.task_storage import load_task

    source = document["scientific"]["provenance"].get("binding", {}).get("semantic_task", {}).get("task")
    if not isinstance(source, str):
        return None, None
    journal = Path(source)
    try:
        state = load_task(journal) if (journal / "task.json").is_file() else {}
    except (ValueError, OSError, RuntimeError):
        return journal, None  # A creation receipt is not the current figure authority.
    task = state.get("project_creation_figure")
    return journal, task if isinstance(task, dict) and state.get("project") == str(plot) else None


def _inspect_managed_project(project: Path, *, figure_id: str | None) -> dict[str, Any] | None:
    from sciplot_core.foundation.canonical_paths import canonical_path
    from sciplot_core.plot_engine.managed_delivery_continuation import local_managed_target, managed_delivery_location
    from sciplot_core.project_lifecycle.repository_router import ComposedProjectRepository
    from sciplot_core.task_semantic_owner import inspect_managed_publication
    from sciplot_core.task_storage import load_task

    value = canonical_path(project)
    delivery = managed_delivery_location(value)
    snapshot = native = selected_journal = None
    if delivery is not None:
        root, snapshot, manifest = delivery
        # The one-figure project-create receipt historically advertised the
        # plan's figure ID, not the package's item ID. Validate that alias
        # against the matched original below rather than forgetting it.
        native = local_managed_target(root, figure_id if len(manifest["items"]) != 1 else None,
                                      native_snapshot=snapshot, manifest=manifest, owner=ComposedProjectRepository())
        plot, head = native["plot"], native["head"]
    elif (value.parent.name == "managed" and value.parent.parent.name == ".sciplot_documents"
          or value.parent.name == ".sciplot_semantic"):
        plot, head = value, observe_plot_head(value, optional=True)
    elif value.name == "task.json" and value.parent.name == "creation" and value.is_file():
        state = load_task(value.parent)
        if not isinstance(state.get("project_creation_figure"), dict) or not isinstance(state.get("project"), str):
            return None
        selected_journal = value.parent
        plot = canonical_path(Path(state["project"]))
        head = observe_plot_head(plot, optional=True)
    else:
        return None
    if head is None or head["document"].get("plot_type") != "ManagedPlot":
        return None
    document = head["document"]
    journal, original = _creation_history(plot, document)
    if selected_journal is not None and (journal != selected_journal or original is None):
        raise ValueError("The selected creation journal does not own this Managed plot.")
    package_id = native["item_id"] if native else None
    plot_id = document["plot_id"]
    identity = original["figure_id"] if original is not None else package_id or plot_id
    identifiers = {identity, package_id} if native is not None else {identity, plot_id}
    if figure_id is not None and figure_id not in identifiers:
        raise ValueError(f"Unknown figure_id for this Managed project: {figure_id}")
    if figure_id == package_id and package_id is not None:
        identity = package_id
    current = inspect_managed_publication(plot, plot_id=plot_id, revision=document["revision"])
    cache = current["export_current"]
    publication = cache.get("publication") or {}
    qa = publication.get("publication_qa", {}).get("status")
    ready = cache["current"] is True and (publication.get("ready_to_use") is True
                                         or publication.get("native_export_ready") is True)
    item = {"figure_id": identity, "title": original["title"] if original else native["label"] if native else plot_id,
            "status": "ready" if ready else current["status"], "plot": str(plot), "plot_id": plot_id,
            **{key: current[key] for key in ("revision", "scientific_hash", "presentation_hash")},
            "document": current["artifact"], "exports": publication.get("exports", []), "export_current": cache}
    return {"kind": "sciplot_project_inspection", "version": 1, "status": "ok", "project": str(plot),
            "request": str(journal / "task.json") if original is not None and journal is not None else None,
            "primary_figure_id": identity, "figures": [item],
            **({"selected_figure": item} if figure_id is not None or snapshot is not None else {}),
            "source": {"current": current["status"] == "current"},
            "qa": {"current": ready and qa == "passed", "status": qa},
            "delivery": {"current": ready, "scope": "selected_managed_export_files"},
            **({"selected_snapshot": {"path": native["native_snapshot"], "item_id": package_id, "current": True}}
                if native is not None else {}),
            "publication_scope": "selected_managed_revision", "ready_to_use": ready,
            "readiness_evaluated": True, "document_authority": "managed_plot", "live_gui_state_evaluated": False,
            "next_step": {"action": "open_managed_plot", "cli_argv": ["sciplot", "plot", "open", str(plot), "--json"]}}


@observe_existing_store()
def inspect_project(project: Path, **options: Any) -> dict[str, Any]:
    from sciplot_core.studio_core.managed_frequency_query import inspect_frequency_creation

    curve = _inspect_managed_project(project, figure_id=options.get("figure_id"))
    if curve is not None:
        if any(options.get(key) for key in ("object_path", "native", "include_annotations", "include_axes")):
            raise ValueError("Managed figures expose their current objects through plot open; use the reported canonical plot path.")
        return curve
    managed = inspect_frequency_creation(project, figure_id=options.get("figure_id"))
    if managed is None:
        observation = observe_legacy_project(project)
        if (observation.project / ".sciplot_store").exists():
            with query_sources(project_store(observation.project)):
                return _inspect_legacy_project(observation, **options)
        return _inspect_legacy_project(observation, **options)
    if any(options.get(key) for key in ("object_path", "native", "include_annotations", "include_axes")):
        raise ValueError("Managed figures expose their current objects through plot open; use the reported figure plot path.")
    return managed


__all__ = ["inspect_project"]
