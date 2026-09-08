"""Reviewed semantic operations reuse the native document edit transaction."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.annotation_contracts import annotation_records
from sciplot_core.studio_core.annotation_axes import axis_unit
from sciplot_core.studio_core.annotation_schema import (
    AnnotationOperationError, annotation_operation_capabilities, validate_operation_batch,
)
from sciplot_core.studio_core.document_edit_state import audit_edited_document
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_figure
from sciplot_core.studio_core.sample_style import expand_sample_styles
from sciplot_core.studio_core.sample_style_presets import expand_style_presets
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

    validate_operation_batch(operations)
    spec_sha: str | None = None
    if any(operation.get("op") in {"set_sample_style", "apply_sample_style_preset"} for operation in operations):
        selected = resolve_project_figure(project, figure_id)
        query = inspect_project(project, figure_id=selected["figure_id"])
        selected = query["selected_figure"]
        if selected["document_sha256"] != expected_document_sha256:
            raise AnnotationOperationError("stale_revision", "Inspect the current saved document revision.")
        raw = Path(selected["spec"]).read_bytes()
        spec_sha = sha256(raw).hexdigest()
        if spec_sha != selected["spec_sha256"]:
            raise AnnotationOperationError("stale_revision", "The sample mapping changed; inspect again.")
        spec = json.loads(raw)
        operations = expand_sample_styles(spec, selected["objects"], expand_style_presets(spec, operations))
        return preview_document_edit(project, [], output_dir=output_dir, figure_id=selected["figure_id"],
                                     expected_document_sha256=expected_document_sha256,
                                     expected_spec_sha256=spec_sha, operations=operations)
    return preview_document_edit(project, [], output_dir=output_dir, figure_id=figure_id,
                                 expected_document_sha256=expected_document_sha256,
                                 operations=operations)
