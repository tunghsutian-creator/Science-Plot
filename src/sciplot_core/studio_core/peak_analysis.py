"""Source-bound observed peak candidates; no smoothing or scientific assignments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.studio_core.document_edit_state import audit_edited_document
from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.studio_core.peak_evidence import peak_candidates_for_spec as peak_candidates_for_spec
from sciplot_core.studio_core.peak_evidence import validate_peak_candidate as validate_peak_candidate


def inspect_peak_candidates(
    project: Path, *, figure_id: str | None = None, object_path: str,
    window: dict[str, Any], polarity: str, expected_document_sha256: str,
) -> dict[str, Any]:
    selected = resolve_project_figure(project, figure_id)
    document, spec_path = Path(selected["document"]), Path(selected["spec"])
    if file_sha256(document) != expected_document_sha256:
        raise AnnotationOperationError("stale_revision", "Inspect the current document revision first.")
    spec_bytes = spec_path.read_bytes()
    audit_edited_document(document, spec_path)
    candidates = peak_candidates_for_spec(json.loads(spec_bytes), object_path=object_path,
                                         window=window, polarity=polarity)
    if spec_path.read_bytes() != spec_bytes or file_sha256(document) != expected_document_sha256:
        raise AnnotationOperationError("stale_revision", "The figure changed during peak inspection.")
    return {
        "kind": "sciplot_peak_candidates", "version": 1, "status": "ok",
        "figure_id": selected["figure_id"], "document_sha256": expected_document_sha256,
        "candidates": [{**c, "figure_id": selected["figure_id"],
                        "document_sha256": expected_document_sha256} for c in candidates],
        "interpretation": "Observed unsmoothed strict interior extrema; no chemical or phase assignment.",
        "empty_reason": "No strict interior extrema in this window; boundaries and plateaus are excluded."
        if not candidates else None,
    }
