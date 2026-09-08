"""Read the saved managed project for external clients without preparing it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.studio_core.document_edit_policy import filter_editable_fields
from sciplot_core.studio_core.sample_style import sample_style_targets
from sciplot_core.studio_core.project_query_evidence import (
    publication_indicators,
    source_indicators,
)
from sciplot_core.studio_core.project_query_paths import (
    project_snapshot,
    resolve_project_path,
    select_figure,
)
from sciplot_core.veusz_runtime import veusz_worker_environment


def resolve_project_figure(
    project: Path, figure_id: str | None = None
) -> dict[str, Any]:
    """Resolve one registered saved figure without starting a Qt runtime."""
    root = resolve_project_path(project)
    _, primary, figures = project_snapshot(root)
    return {"project": str(root), **select_figure(project, primary, figures, figure_id)}


def _inspect_document(document: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sciplot_core.veusz_worker",
            "inspect-document-state",
            str(document),
        ],
        env=veusz_worker_environment(),
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


def inspect_project(
    project: Path,
    *,
    figure_id: str | None = None,
    object_path: str | None = None,
) -> dict[str, Any]:
    """Return current byte identities and separately labelled historical evidence.

    ``status=ok`` only means the query succeeded. No rendering, scientific audit,
    human review, publication, or readiness certification is performed here.
    """
    root = resolve_project_path(project)
    request_path = root / "plot_request.json"
    request_sha = existing_file_sha256(request_path)
    registry_sha = existing_file_sha256(root / "studio" / "figure_set.json")
    request, primary, figures = project_snapshot(root)
    for figure in figures:
        figure["sample_styles"] = sample_style_targets(json.loads(Path(figure["spec"]).read_text()))
    source = source_indicators(root, request, figures)
    payload: dict[str, Any] = {
        "kind": "sciplot_project_inspection",
        "version": 1,
        "status": "ok",
        "project": str(root),
        "request": str(request_path),
        "request_sha256": request_sha,
        "primary_figure_id": primary,
        "figures": figures,
        "source": source,
        **publication_indicators(root, request, figures, source),
        "ready_to_use": None,
        "readiness_evaluated": False,
        "document_authority": "saved_vsz",
        "live_gui_state_evaluated": False,
    }
    if figure_id is not None or object_path is not None:
        figure = select_figure(project, primary, figures, figure_id)
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
    if (
        existing_file_sha256(request_path) != request_sha
        or existing_file_sha256(root / "studio" / "figure_set.json") != registry_sha
        or any(
            existing_file_sha256(Path(item[field])) != item[field + "_sha256"]
            for item in figures
            for field in ("document", "spec")
        )
    ):
        raise ValueError("The saved project changed during inspection; query again.")
    return payload


__all__ = ["inspect_project", "resolve_project_figure", "resolve_project_path"]
