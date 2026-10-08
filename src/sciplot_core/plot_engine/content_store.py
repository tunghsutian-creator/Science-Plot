"""Immutable content-addressed scientific provenance outside native projects."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from sciplot_core.plot_document import seal_document, validate_document
from sciplot_core.plot_document.validation import finite_json
from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot
from sciplot_core.studio_core.project_query_paths import canonical_path

from .errors import EngineError

MINIMUM_BLOB_BYTES = 64 * 1024
REFERENCE_KIND = "sciplot_content_reference"
_REFERENCE_FIELDS = {"kind", "schema_version", "sha256", "encoding", "byte_length"}


def _encoded(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _reference(payload: bytes) -> dict[str, Any]:
    return {"kind": REFERENCE_KIND, "schema_version": 1, "sha256": hashlib.sha256(payload).hexdigest(),
            "encoding": "canonical_json_utf8", "byte_length": len(payload)}


def _reference_path(root: Path, reference: dict[str, Any]) -> Path:
    if (set(reference) != _REFERENCE_FIELDS or reference.get("kind") != REFERENCE_KIND
            or type(reference.get("schema_version")) is not int or reference["schema_version"] != 1
            or reference.get("encoding") != "canonical_json_utf8"
            or not isinstance(reference.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None
            or type(reference.get("byte_length")) is not int or reference["byte_length"] < 2):
        raise EngineError("document_content_reference_invalid", "The scientific content reference is invalid.",
                          action="inspect_document_content")
    return canonical_path(root / "content" / (reference["sha256"] + ".json"))


def _verified_bytes(root: Path, reference: dict[str, Any]) -> bytes:
    path = _reference_path(root, reference)
    try:
        snapshot = _stable_file_snapshot(path, label="Scientific content")
    except (OSError, ValueError) as exc:
        raise EngineError("document_content_unavailable", "Referenced scientific content is missing or unstable.",
                          action="restore_document_content", sha256=reference["sha256"], evidence=str(path)) from exc
    if snapshot["sha256"] != reference["sha256"] or snapshot["identity"]["size"] != reference["byte_length"]:
        raise EngineError("document_content_corrupt", "Referenced scientific content does not match its immutable byte seal.",
                          action="restore_document_content", sha256=reference["sha256"], evidence=str(path))
    payload: bytes = snapshot["bytes"]
    return payload


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _store(root: Path, payload: bytes) -> dict[str, Any]:
    reference = _reference(payload)
    path = _reference_path(root, reference)
    if path.exists():
        _verified_bytes(root, reference)
        return reference
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".content-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic create-if-absent: never replace an existing (possibly corrupt)
        # blob, including a concurrent writer's already published identical one.
        try:
            os.link(temporary, path)
        except FileExistsError:
            _verified_bytes(root, reference)
        temporary.unlink()
        temporary = None
        _fsync_directory(path.parent)
        _fsync_directory(path.parent.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return reference


def _references(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    provenance = document["scientific"]["provenance"]
    return [(key, value) for key, value in provenance.items()
            if isinstance(value, dict) and value.get("kind") == REFERENCE_KIND]


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
    """Verify full blob bytes each time; never parse or reserialize large JSON here."""
    for _key, reference in _references(document):
        _verified_bytes(root, reference)


def referenced_files(root: Path, document: dict[str, Any]) -> dict[str, str]:
    """Return validated expected file identities for engine guards, without reading blobs."""
    return {str(_reference_path(root, reference)): reference["sha256"] for _key, reference in _references(document)}


def resolve_document_content(root: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Explicitly recover the full original scientific projection without writes."""
    result = validate_document(document)
    for key, reference in _references(result):
        encoded = _verified_bytes(root, reference)
        try:
            payload = json.loads(encoded)
            finite_json(payload)
        except (UnicodeError, ValueError) as exc:
            raise EngineError("document_content_invalid_json", "Scientific content is not valid finite JSON.",
                              action="inspect_document_content", sha256=reference["sha256"]) from exc
        if not isinstance(payload, (dict, list)) or _encoded(payload) != encoded:
            raise EngineError("document_content_invalid_json", "Scientific content is not its declared canonical object or array.",
                              action="inspect_document_content", sha256=reference["sha256"])
        result["scientific"]["provenance"][key] = deepcopy(payload)
    return seal_document(result)
