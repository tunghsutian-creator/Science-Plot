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
    observe_managed_curve,
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


def _curve_project_status(observed: tuple[dict[str, Any], dict[str, Any], bool]) -> dict[str, Any]:
    from sciplot_core.task_semantic_creation import current_result

    item, state, selected = observed
    plot = item["plot"]
    result = current_result(state)
    current = result.get("current_project") or {}
    if current.get("plot_id") is not None and (current["plot_id"], current["revision"]) != (item["plot_id"], item["revision"]):
        raise ValueError("The selected Managed project advanced during inspection; query again.")
    cache = current.get("export_current") or {}
    return {"kind": "sciplot_project_inspection", "version": 1, "status": "ok", "project": str(plot),
            "request": str(Path(state["task_dir"]) / "task.json"), "primary_figure_id": item["figure_id"], "figures": [item],
            **({"selected_figure": item} if selected else {}),
            "source": {"current": current.get("status") == "current"},
            "qa": {"current": cache.get("current") is True and cache.get("byte_inventory_verified") is True},
            "delivery": {"current": result.get("native_delivery_current") is True}, "ready_to_use": result.get("ready_to_use") is True,
            "readiness_evaluated": True, "document_authority": "managed_plot", "live_gui_state_evaluated": False,
            "next_step": {"action": "open_managed_plot", "cli_argv": ["sciplot", "plot", "open", str(plot), "--json"]}}


@observe_existing_store()
def inspect_project(project: Path, **options: Any) -> dict[str, Any]:
    from sciplot_core.studio_core.managed_frequency_query import inspect_frequency_creation

    curve = observe_managed_curve(project, figure_id=options.get("figure_id"))
    if curve is not None:
        if any(options.get(key) for key in ("object_path", "native", "include_annotations", "include_axes")):
            raise ValueError("Managed figures expose their current objects through plot open; use the reported canonical plot path.")
        return _curve_project_status(curve)
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
