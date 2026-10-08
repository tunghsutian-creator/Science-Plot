"""Immutable revisions and durable journal, outside the native project inventory."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json, read_json_object
from sciplot_core.plot_document import validate_document
from sciplot_core.studio_core.project_query_paths import canonical_path

from .errors import EngineError
from .content_store import referenced_files, verify_document_content


def digest(payload: Any) -> str:
    return canonical_json_sha256(payload, allow_nan=False)


def write(path: Path, payload: dict[str, Any]) -> None:
    canonical_path(path)
    atomic_write_json(path, payload)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read(path: Path) -> dict[str, Any]:
    canonical_path(path)
    payload = read_json_object(path)
    if payload is None:
        raise EngineError("document_state_missing", "Required document state is missing or invalid.",
                          evidence=str(path))
    return payload


def document_root(project: Path, figure_id: str) -> Path:
    project = canonical_path(project)
    return project.parent / ".sciplot_documents" / digest([str(project), figure_id])[:32]


def transaction_path(root: Path, key: str) -> Path:
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise EngineError("document_invalid_idempotency_key", "Use a stable non-empty idempotency key of at most 128 characters.")
    return root / "transactions" / digest(key) / "transaction.json"


def load_head(root: Path) -> dict[str, Any]:
    head = read(root / "head.json")
    revision = head.get("revision")
    if type(revision) is not int or revision < 0:
        raise EngineError("document_state_invalid", "The revision pointer is invalid.")
    envelope = read(root / "revisions" / f"{revision:08d}.json")
    if digest(envelope) != head.get("sha256"):
        raise EngineError("document_state_invalid", "The revision does not match its committed pointer.")
    validate_document(envelope["document"])
    verify_document_content(root, envelope["document"])
    if envelope["binding"].get("scientific_content_files", {}) != referenced_files(root, envelope["document"]):
        raise EngineError("document_content_binding_invalid", "Scientific content references and currentness guards disagree.")
    if envelope["document"]["revision"] != revision:
        raise EngineError("document_state_invalid", "Document revision and pointer disagree.")
    return envelope


def commit(root: Path, document: dict[str, Any], binding: dict[str, Any], transaction: str) -> None:
    verify_document_content(root, document)
    if binding.get("scientific_content_files", {}) != referenced_files(root, document):
        raise EngineError("document_content_binding_invalid", "Scientific content references lack their currentness guards.")
    envelope = {"document": validate_document(document), "binding": binding,
                "transaction": transaction}
    revision = document["revision"]
    target = root / "revisions" / f"{revision:08d}.json"
    if target.exists() and read(target) != envelope:
        raise EngineError("document_revision_collision", "A different snapshot already occupies this revision.")
    if not target.exists():
        write(target, envelope)
    write(root / "head.json", {"revision": revision, "sha256": digest(envelope)})


def active(root: Path) -> dict[str, Any] | None:
    path = root / "active.json"
    if not path.exists():
        return None
    pointer = read(path)
    return read(transaction_path(root, pointer["key"]))


def persist(root: Path, transaction: dict[str, Any]) -> None:
    event = {"phase": transaction["phase"], "retry_counts": dict(transaction.get("retry_counts", {})),
             "error": transaction.get("error")}
    history = transaction.setdefault("events", [])
    previous = {key: history[-1].get(key) for key in event} if history else None
    if previous != event:
        history.append({**event, "at": datetime.now(timezone.utc).isoformat()})
    write(transaction_path(root, transaction["request"]["idempotency_key"]), transaction)


def reserve(root: Path, transaction: dict[str, Any]) -> None:
    persist(root, transaction)
    write(root / "active.json", {"key": transaction["request"]["idempotency_key"]})
