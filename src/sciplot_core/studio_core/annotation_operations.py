"""Reviewed semantic operations reuse the native document edit transaction."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.annotation_contracts import annotation_records
from sciplot_core.studio_core.annotation_axes import axis_unit
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError, annotation_operation_capabilities
from sciplot_core.studio_core.document_edit_state import audit_edited_document
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_figure
from sciplot_core.studio_core.sample_style import expand_sample_styles
from sciplot_core.studio_core.annotation_batch import compile_annotation_operations as compile_annotation_operations


def inspect_annotation_state(project: Path, *, figure_id: str | None = None) -> dict[str, Any]:
    selected = resolve_project_figure(project, figure_id)
    document, spec_path = Path(selected["document"]), Path(selected["spec"])
    baseline, raw = file_sha256(document), spec_path.read_bytes()
    audit_edited_document(document, spec_path)
    spec = json.loads(raw)
    records = annotation_records(spec)
    if file_sha256(document) != baseline or spec_path.read_bytes() != raw:
        raise AnnotationOperationError("stale_revision", "The figure changed during annotation inspection.")
    return {"kind": "sciplot_annotation_state", "version": 1, "status": "ok",
            "figure_id": selected["figure_id"], "document_sha256": baseline,
            "annotations": records, "axes": {
                axis: {"unit": axis_unit(spec, axis), **{key: spec["axes"][axis][key]
                                                        for key in ("label", "min", "max", "scale")}}
                for axis in ("x", "y")},
            "capabilities": annotation_operation_capabilities()}


def preview_document_operations(
    project: Path, operations: list[dict[str, Any]], *, output_dir: Path,
    figure_id: str | None = None, expected_document_sha256: str,
) -> dict[str, Any]:
    from sciplot_core.studio_core.document_edit import preview_document_edit

    if not isinstance(operations, list) or not 1 <= len(operations) <= 100 or not all(
        isinstance(operation, dict) for operation in operations
    ):
        raise AnnotationOperationError("invalid_operations", "Provide 1–100 explicit operations.")
    spec_sha: str | None = None
    if any(operation.get("op") == "set_sample_style" for operation in operations):
        selected = resolve_project_figure(project, figure_id)
        query = inspect_project(project, figure_id=selected["figure_id"])
        selected = query["selected_figure"]
        if selected["document_sha256"] != expected_document_sha256:
            raise AnnotationOperationError("stale_revision", "Inspect the current saved document revision.")
        raw = Path(selected["spec"]).read_bytes()
        spec_sha = sha256(raw).hexdigest()
        if spec_sha != selected["spec_sha256"]:
            raise AnnotationOperationError("stale_revision", "The sample mapping changed; inspect again.")
        operations = expand_sample_styles(json.loads(raw), selected["objects"], operations)
        return preview_document_edit(project, [], output_dir=output_dir, figure_id=selected["figure_id"],
                                     expected_document_sha256=expected_document_sha256,
                                     expected_spec_sha256=spec_sha, operations=operations)
    return preview_document_edit(project, [], output_dir=output_dir, figure_id=figure_id,
                                 expected_document_sha256=expected_document_sha256,
                                 operations=operations)
