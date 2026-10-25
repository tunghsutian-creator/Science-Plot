"""Pure existing CAS reference format and byte verification; no filesystem IO."""
from collections.abc import Callable
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from sciplot_core.plot_document import seal_document, validate_document
from sciplot_core.plot_document.validation import finite_json
from .paths import canonical_path
from .errors import EngineError

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


def _verified_bytes(root: Path, reference: dict[str, Any], *, read_snapshot: Callable[[Path], dict[str, Any]]) -> bytes:
    path = _reference_path(root, reference)
    try:
        snapshot = read_snapshot(path)
    except (OSError, ValueError) as exc:
        raise EngineError("document_content_unavailable", "Referenced scientific content is missing or unstable.",
                          action="restore_document_content", sha256=reference["sha256"], evidence=str(path)) from exc
    if snapshot["sha256"] != reference["sha256"] or snapshot["identity"]["size"] != reference["byte_length"]:
        raise EngineError("document_content_corrupt", "Referenced scientific content does not match its immutable byte seal.",
                          action="restore_document_content", sha256=reference["sha256"], evidence=str(path))
    payload: bytes = snapshot["bytes"]
    return payload


def _references(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    provenance = document["scientific"]["provenance"]
    return [(key, value) for key, value in provenance.items()
            if isinstance(value, dict) and value.get("kind") == REFERENCE_KIND]


def verify_document_content(root: Path, document: dict[str, Any], *, read_snapshot: Callable[[Path], dict[str, Any]]) -> None:
    """Verify full blob bytes each time; never parse or reserialize large JSON here."""
    for _key, reference in _references(document):
        _verified_bytes(root, reference, read_snapshot=read_snapshot)


def referenced_files(root: Path, document: dict[str, Any]) -> dict[str, str]:
    """Return validated expected file identities for engine guards, without reading blobs."""
    return {str(_reference_path(root, reference)): reference["sha256"] for _key, reference in _references(document)}


def resolve_provenance_value(root: Path, document: dict[str, Any], key: str, *, read_snapshot: Callable[[Path], dict[str, Any]]) -> Any:
    """Read one provenance value through the existing immutable byte owner."""
    value = document["scientific"]["provenance"].get(key)
    if not isinstance(value, dict) or value.get("kind") != REFERENCE_KIND:
        return deepcopy(value)
    encoded = _verified_bytes(root, value, read_snapshot=read_snapshot)
    try:
        payload = json.loads(encoded)
        finite_json(payload)
    except (UnicodeError, ValueError) as exc:
        raise EngineError("document_content_invalid_json", "Scientific content is not valid finite JSON.",
                          action="inspect_document_content", sha256=value["sha256"]) from exc
    if not isinstance(payload, (dict, list)) or _encoded(payload) != encoded:
        raise EngineError("document_content_invalid_json", "Scientific content is not its declared canonical object or array.",
                          action="inspect_document_content", sha256=value["sha256"])
    return payload


def resolve_document_content(root: Path, document: dict[str, Any], *, read_snapshot: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    """Explicitly recover the full original scientific projection without writes."""
    result = validate_document(document)
    for key, _reference_value in _references(result):
        result["scientific"]["provenance"][key] = resolve_provenance_value(root, result, key, read_snapshot=read_snapshot)
    return seal_document(result)
