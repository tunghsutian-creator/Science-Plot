"""Immutable revisions and durable journal, outside the native project inventory."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable
from contextlib import AbstractContextManager

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json, read_json_object
from sciplot_core.plot_document import validate_document
from .paths import canonical_path
from .ports import ProjectRepository as ProjectRepository

from sciplot_core.project_lifecycle.errors import EngineError
from .content_references import referenced_files, verify_document_content
from . import file_content


from .contracts import AuthorityMode
from .aggregate_validation import validate_snapshot
from .journal_identity import saved_command


def digest(payload: Any) -> str:
    return canonical_json_sha256(payload, allow_nan=False)


def document_root(project: Path, figure_id: str) -> Path:
    project = canonical_path(project)
    return project.parent / ".sciplot_documents" / digest([str(project), figure_id])[:32]


def transaction_path(root: Path, key: str) -> Path:
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise EngineError("document_invalid_idempotency_key", "Use a stable non-empty idempotency key of at most 128 characters.")
    return root / "transactions" / digest(key) / "transaction.json"


class FileProjectRepository:
    """The existing format's sole revision/head/journal writer; no mirror store.

    The composition root supplies the native-compatible lease adapter. Low-level
    compatibility reads/writes keep their historical caller-held lease contract.
    """
    def __init__(self, *, lease: Callable[[Path], AbstractContextManager[Any]] | None = None,
                 snapshot_validator: Callable[[Path, dict[str, Any]], None] | None = None) -> None:
        self._lease, self._validate_snapshot = lease, snapshot_validator

    def lease(self, root: Path) -> AbstractContextManager[Any]:
        if self._lease is None:
            raise RuntimeError("Application writes require an explicitly composed repository lease.")
        return self._lease(root)

    def content_snapshot(self, path: Path) -> dict[str, Any]:
        return file_content.read_snapshot(path)

    def publish_content(self, path: Path, payload: bytes, verify_existing: Callable[[], None]) -> None:
        file_content.publish(path, payload, verify_existing)

    def json_members(self, directory: Path, pattern: str) -> list[Path]:
        canonical_path(directory)
        return sorted(directory.glob(pattern))

    def create_namespace(self, root: Path) -> None:
        canonical_path(root)
        root.mkdir()

    def prepare_namespace(self, root: Path) -> None:
        canonical_path(root)
        root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def require_empty_output(self, output: Path) -> None:
        canonical_path(output)
        if output.exists() and any(output.iterdir()):
            raise EngineError("managed_output_conflict", "The selected output directory already contains files.")

    def has_head(self, root: Path) -> bool:
        return self.exists(root / "head.json")

    def has_revision(self, root: Path, revision: int) -> bool:
        return self.exists(root / "revisions" / f"{revision:08d}.json")

    def exists(self, path: Path) -> bool:
        canonical_path(path)
        return path.exists()

    def load_revision(self, root: Path, revision: int) -> dict[str, Any]:
        if type(revision) is not int or revision < 0:
            raise EngineError("document_state_invalid", "The revision number is invalid.")
        envelope = self.read(root / "revisions" / f"{revision:08d}.json")
        validate_document(envelope["document"])
        verify_document_content(root, envelope["document"], read_snapshot=self.content_snapshot)
        if envelope["document"]["revision"] != revision:
            raise EngineError("document_state_invalid", "Document revision and snapshot disagree.")
        return envelope


    def write(self, path: Path, payload: dict[str, Any]) -> None:
        canonical_path(path)
        atomic_write_json(path, payload)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


    def read(self, path: Path) -> dict[str, Any]:
        canonical_path(path)
        payload = read_json_object(path)
        if payload is None:
            raise EngineError("document_state_missing", "Required document state is missing or invalid.",
                              evidence=str(path))
        if path.name == "transaction.json":
            saved_command(payload)
        return payload


    def load_head(self, root: Path) -> dict[str, Any]:
        head = self.read(root / "head.json")
        revision = head.get("revision")
        if type(revision) is not int or revision < 0:
            raise EngineError("document_state_invalid", "The revision pointer is invalid.")
        envelope = self.load_revision(root, revision)
        if digest(envelope) != head.get("sha256"):
            raise EngineError("document_state_invalid", "The revision does not match its committed pointer.")
        validate_document(envelope["document"])
        verify_document_content(root, envelope["document"], read_snapshot=self.content_snapshot)
        if envelope["binding"].get("scientific_content_files", {}) != referenced_files(root, envelope["document"]):
            raise EngineError("document_content_binding_invalid", "Scientific content references and currentness guards disagree.")
        if envelope["document"]["revision"] != revision:
            raise EngineError("document_state_invalid", "Document revision and pointer disagree.")
        return envelope


    def commit(self, root: Path, document: dict[str, Any], binding: dict[str, Any], transaction: str) -> None:
        verify_document_content(root, document, read_snapshot=self.content_snapshot)
        if binding.get("scientific_content_files", {}) != referenced_files(root, document):
            raise EngineError("document_content_binding_invalid", "Scientific content references lack their currentness guards.")
        if self._validate_snapshot is None:
            validate_snapshot(root, document, read_snapshot=self.content_snapshot)
        else:
            self._validate_snapshot(root, document)
        envelope = {"document": validate_document(document), "binding": binding,
                    "transaction": transaction}
        revision = document["revision"]
        target = root / "revisions" / f"{revision:08d}.json"
        if self.exists(target) and self.read(target) != envelope:
            raise EngineError("document_revision_collision", "A different snapshot already occupies this revision.")
        if self.exists(root / "head.json"):
            current = self.load_head(root)
            previous = current["document"]
            if (document["plot_id"] != previous["plot_id"]
                    or AuthorityMode.of(document) != AuthorityMode.of(previous)):
                raise EngineError("document_identity_conflict", "A committed aggregate cannot change identity or authority.")
            if document["revision"] == previous["revision"]:
                if current != envelope:
                    raise EngineError("document_revision_collision", "The current revision already has another snapshot.")
            elif document["revision"] != previous["revision"] + 1:
                raise EngineError("document_revision_conflict", "Commit must advance the current revision once.",
                                  current_revision=previous["revision"])
        elif revision != 0:
            raise EngineError("document_revision_conflict", "An aggregate starts at revision zero.")
        if not self.exists(target):
            self.write(target, envelope)
        self.write(root / "head.json", {"revision": revision, "sha256": digest(envelope)})


    def active(self, root: Path) -> dict[str, Any] | None:
        path = root / "active.json"
        if not self.exists(path):
            return None
        pointer = self.read(path)
        return self.read(transaction_path(root, pointer["key"]))


    def persist(self, root: Path, transaction: dict[str, Any]) -> None:
        saved_command(transaction)
        target = transaction_path(root, transaction["request"]["idempotency_key"])
        if self.exists(target):
            original = self.read(target)
            for field in ("request", "request_hash", "normalized_command", "rollback_request", "reimport_request"):
                if original.get(field) != transaction.get(field):
                    raise EngineError("document_idempotency_conflict", "A persisted command identity is immutable.")
        event = {"phase": transaction["phase"], "retry_counts": dict(transaction.get("retry_counts", {})),
                 "error": transaction.get("error")}
        history = transaction.setdefault("events", [])
        previous = {key: history[-1].get(key) for key in event} if history else None
        if previous != event:
            history.append({**event, "at": datetime.now(timezone.utc).isoformat()})
        self.write(transaction_path(root, transaction["request"]["idempotency_key"]), transaction)


    def reserve(self, root: Path, transaction: dict[str, Any]) -> None:
        self.persist(root, transaction)
        self.write(root / "active.json", {"key": transaction["request"]["idempotency_key"]})
