"""Compile one closed semantic operation batch without loading a native document."""

from __future__ import annotations

import copy
from typing import Any

from sciplot_core.studio_core.annotation_contracts import annotation_records, normalize_annotation, _closed
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError


def compile_annotation_operations(
    spec: dict[str, Any], operations: Any, *, document_sha256: str, figure_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise AnnotationOperationError("invalid_operations", "Provide 1–100 explicit operations.")
    result = copy.deepcopy(spec)
    items = copy.deepcopy(annotation_records(spec))
    styles, actual = [], []
    touched: set[str] = set()
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise AnnotationOperationError("invalid_operation", f"Operation {index} must be an object.")
        kind = operation.get("op")
        if kind == "set_style":
            _closed(operation, {"op", "object_path", "setting_path", "expected_value", "value"})
            styles.append({k: v for k, v in operation.items() if k != "op"})
            continue
        identifier = operation.get("id")
        if not isinstance(identifier, str) or identifier in touched:
            raise AnnotationOperationError("duplicate_annotation_id", "Each batch may touch an annotation ID only once.")
        touched.add(identifier)
        existing = next((item for item in items if item["id"] == identifier), None)
        if kind in {"remove_annotation", "update_annotation"}:
            _closed(operation, {"op", "id", "expected_annotation"} |
                    ({"replacement"} if kind == "update_annotation" else set()))
            if existing is None or existing != operation["expected_annotation"]:
                raise AnnotationOperationError("stale_annotation", "Inspect the exact annotation record before editing it.")
            items.remove(existing)
            if kind == "remove_annotation":
                actual.append({"op": kind, "id": identifier, "before": existing, "after": None})
                continue
            replacement = operation["replacement"]
            if not isinstance(replacement, dict) or replacement.get("id") != identifier:
                raise AnnotationOperationError("invalid_operation", "Replacement must be an add operation with the same ID.")
        else:
            if existing is not None:
                raise AnnotationOperationError("duplicate_annotation_id", "Annotation ID already exists.")
            replacement = operation
        if replacement.get("op") == "add_peak_label":
            candidate = replacement.get("candidate")
            if not isinstance(candidate, dict) or candidate.get("document_sha256") != document_sha256 or candidate.get("figure_id") != figure_id:
                raise AnnotationOperationError("stale_peak_candidate", "Inspect peak candidates for this exact saved figure revision.")
        normalized = normalize_annotation(spec, replacement)
        items.append(normalized)
        actual.append({"op": kind, "id": identifier, "before": existing, "after": normalized})
    if len(items) > 100:
        raise AnnotationOperationError("annotation_limit", "At most 100 annotations per figure are supported.")
    if items:
        result["native_annotations"] = {"version": 1, "items": items}
    else:
        result.pop("native_annotations", None)
    return styles, result, actual


