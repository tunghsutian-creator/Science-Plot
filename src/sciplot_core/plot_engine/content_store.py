"""Existing scientific CAS encoding/verification through the selected repository."""
from pathlib import Path
from typing import Any
import json as json

from sciplot_core.plot_document import seal_document, validate_document
from sciplot_core.project_lifecycle.paths import canonical_path
from sciplot_core.project_lifecycle.context import content_snapshot, publish_content
from sciplot_core.project_lifecycle import content_references as _format
from sciplot_core.project_lifecycle.content_references import (
    _encoded as _encoded, _reference as _reference, _reference_path as _reference_path,
    referenced_files as referenced_files,
)

MINIMUM_BLOB_BYTES = 64 * 1024
REFERENCE_KIND = _format.REFERENCE_KIND


def _verified_bytes(root: Path, reference: dict[str, Any]) -> bytes:
    return _format._verified_bytes(root, reference, read_snapshot=content_snapshot)


def _store(root: Path, payload: bytes) -> dict[str, Any]:
    reference = _reference(payload)
    path = _reference_path(root, reference)
    publish_content(path, payload, lambda: _verified_bytes(root, reference))
    return reference


def intern_document(root: Path, document: dict[str, Any], *, minimum_bytes: int = MINIMUM_BLOB_BYTES) -> dict[str, Any]:
    """Intern large top-level provenance values once, before the first revision.

    Existing compact documents are verified and reused. This changes the science
    projection's representation, so established inline revisions must not be
    silently interned during ordinary presentation edits.
    """
    if type(minimum_bytes) is not int or minimum_bytes < 2:
        raise ValueError("minimum_bytes must be an integer of at least two bytes.")
    result = validate_document(document)
    root = canonical_path(root)
    for key, value in result["scientific"]["provenance"].items():
        if key == "figure_spec" and result.get("plot_type") == "ManagedPlot":
            # Grammar is the canonical control plane, never a payload cache.
            continue
        if (key == "managed" and result.get("plot_type") == "ManagedPlot" and isinstance(value, dict)
                and value.get("kind") == "managed_scientific_model"):
            # This small control plane identifies source/executor authority and
            # must be readable before any payload resolution or native work.
            # Even a large explicit executor schema stays canonical inline.
            continue
        if isinstance(value, dict) and value.get("kind") == REFERENCE_KIND:
            _verified_bytes(root, value)
        elif isinstance(value, (dict, list)):
            encoded = _encoded(value)
            if len(encoded) >= minimum_bytes:
                result["scientific"]["provenance"][key] = _store(root, encoded)
    return seal_document(result)



def verify_document_content(root: Path, document: dict[str, Any]) -> None:
    _format.verify_document_content(root, document, read_snapshot=content_snapshot)


def resolve_provenance_value(root: Path, document: dict[str, Any], key: str) -> Any:
    return _format.resolve_provenance_value(root, document, key, read_snapshot=content_snapshot)


def resolve_document_content(root: Path, document: dict[str, Any]) -> dict[str, Any]:
    return _format.resolve_document_content(root, document, read_snapshot=content_snapshot)
