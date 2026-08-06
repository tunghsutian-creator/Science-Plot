"""Build one verified Studio figure-set registry entry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_core.figure_registry_geometry import (
    registry_figure_size_mm,
)
from sciplot_core.studio_core.figure_task_evidence import (
    figure_registry_projection_from_task,
    figure_task_from_queue_item,
)
from sciplot_core.studio_core.registry_state import (
    _studio_document_state,
    _veusz_spec_path,
)


def _figure_registry_entry(
    *,
    figure: dict[str, Any],
    document_path: Path,
    generated_hash: str | None,
    series_count: int,
    status: str = "ready",
    unavailable: dict[str, Any] | None = None,
    state_document_path: Path | None = None,
) -> dict[str, Any]:
    task = figure_task_from_queue_item(figure)
    document_state = _studio_document_state(
        state_document_path or document_path,
        generated_hash=generated_hash,
    )
    task_projection = (
        figure_registry_projection_from_task(task)
        if task is not None
        else {
            "figure_id": str(figure["id"]),
            "title": str(figure.get("title") or figure["id"]),
            "metric": str(figure["y_metric"]),
            "x_metric": str(figure["x_metric"]),
            "y_metric": str(figure["y_metric"]),
            "order": int(figure.get("order") or 0),
            "artifact_stem": str(figure.get("artifact_stem") or figure["id"]),
            "document_stem": str(figure.get("document_stem") or figure["id"]),
        }
    )
    entry = {
        **task_projection,
        "status": status,
        "document": str(document_path),
        "spec": str(_veusz_spec_path(document_path)),
        "generated_hash": generated_hash,
        "series_count": int(series_count),
        "size_mm": registry_figure_size_mm(
            document_path,
            state_document_path=state_document_path,
        ),
        "single_page": True,
        "document_authority": document_state["authority"],
        "document_state": document_state,
    }
    if unavailable is not None:
        entry["unavailable"] = json_safe(unavailable)
    return entry


__all__ = ["_figure_registry_entry"]
