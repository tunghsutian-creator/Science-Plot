"""Resolve project context and normalize request-level optional values and review notes."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _project_context_for_document(document_path: Path) -> dict[str, Any] | None:
    candidate = document_path.expanduser().resolve()
    studio_dir = next(
        (parent for parent in candidate.parents if parent.name == "studio"),
        None,
    )
    if studio_dir is not None:
        project_dir = studio_dir.parent
        request_path = project_dir / "plot_request.json"
        if request_path.exists():
            return {
                "project_dir": project_dir,
                "request_path": request_path,
                "figure_id": (
                    None if candidate == studio_dir / "document.vsz" else candidate.stem
                ),
            }
    return None


resolve_studio_project_context = _project_context_for_document


def _normalize_optional_string(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _converge_studio_request_review_notes(
    request: dict[str, Any],
) -> bool:
    from sciplot_core.intake.catalog import converge_material_review_notes

    return converge_material_review_notes(request)
