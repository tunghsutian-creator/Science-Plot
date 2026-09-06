"""Durable native-edit outcomes and one-document replacement with rollback."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.studio_core.delivery_recovery import _write_durable
from sciplot_core.studio_core.document_edit_state import edit_state, history_directory
from sciplot_core.studio_core.delivery_recovery_state import canonical_path


def read_edit_operation(project: Path, operation_id: str) -> dict[str, Any]:
    root = history_directory(project, operation_id)
    record_path = canonical_path(root / "outcome.json")
    if not record_path.is_file():
        raise ValueError("No recorded document edit with that operation identity.")
    record = json.loads(record_path.read_text())
    relative = Path(record["document_relative"])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:1] != ("studio",)
    ):
        raise ValueError("The recorded edit does not name a managed document.")
    document = canonical_path(project / relative)
    current = file_sha256(document) if document.is_file() else None
    return {
        "kind": "sciplot_document_edit_outcome",
        "version": 1,
        "project": str(project),
        "operation_id": operation_id,
        "status": record["status"],
        "document": str(document),
        "document_sha256": current,
        "result_sha256": record["result_sha256"],
        "result_is_current": current == record["result_sha256"],
        "previous_document_sha256": record["base_sha256"],
        "archive": str(root / "before.vsz"),
        "ready_to_use": False,
        "export_required": None,
        "readiness_evaluated": False,
    }


def prior_edit_result(project: Path, review: dict[str, Any]) -> dict[str, Any] | None:
    root = history_directory(project, review["operation_id"])
    if not (root / "outcome.json").exists():
        return None
    stored = json.loads((root / "preview.json").read_text())
    if stored != review:
        raise ValueError("The stored operation does not match this edit preview.")
    outcome = read_edit_operation(project, review["operation_id"])
    if outcome["result_is_current"]:
        # A process can stop after replace but before writing its success reply.
        # The durable intent and archived before/after files prove that case.
        pending = json.loads((root / "outcome.json").read_text())
        if file_sha256(root / "after.vsz") != pending["result_sha256"]:
            raise ValueError("Document edit recovery evidence changed.")
        if file_sha256(root / "before.vsz") != pending["base_sha256"]:
            raise ValueError("Document edit archive changed.")
        pending["status"] = "applied"
        atomic_write_json(root / "outcome.json", pending)
        return {**outcome, "status": "already_applied"}
    if outcome["status"] == "applied":
        raise ValueError(
            "This edit was applied, but the document has since changed. Inspect current state."
        )
    if outcome["document_sha256"] != outcome["previous_document_sha256"]:
        raise ValueError(
            "An interrupted edit has a conflicting current document. Preserve its archive."
        )
    return None


def _replace_current_document(staged: Path, document: Path) -> None:
    os.replace(staged, document)


def commit_document_edit(
    project: Path,
    document: Path,
    candidate: Path,
    review: dict[str, Any],
) -> dict[str, Any]:
    """Caller holds the external-session and canonical-project locks."""
    before_state = review["base_state"]
    if edit_state(project) != before_state:
        raise ValueError(
            "Project or delivery changed after preview; inspect current state."
        )
    original = document.read_bytes()
    original_mode = document.stat().st_mode & 0o777
    base_hash = file_sha256(document)
    result_hash = file_sha256(candidate)
    root = history_directory(project, review["operation_id"])
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    before_path, after_path = root / "before.vsz", root / "after.vsz"
    if before_path.exists():
        if file_sha256(before_path) != base_hash:
            raise ValueError("The archived edit baseline conflicts with current state.")
    else:
        _write_durable(before_path, original)
    # A retry before commit may produce a different harmless native-save timestamp.
    atomic_write_json(root / "preview.json", review)
    shutil.copyfile(candidate, after_path)
    with after_path.open("rb") as handle:
        os.fsync(handle.fileno())
    record = {
        "status": "pending",
        "document_relative": str(document.relative_to(project)),
        "base_sha256": base_hash,
        "result_sha256": result_hash,
    }
    atomic_write_json(root / "outcome.json", record)
    descriptor, name = tempfile.mkstemp(
        prefix=".external-edit-", suffix=".vsz", dir=document.parent
    )
    os.close(descriptor)
    staged = Path(name)
    replaced = False
    try:
        shutil.copyfile(after_path, staged)
        staged.chmod(original_mode)
        with staged.open("rb") as handle:
            os.fsync(handle.fileno())
        # Exclude our temporary install file from the active project inventory.
        expected = {
            **before_state,
            "project_files": {
                **before_state["project_files"],
                str(staged.relative_to(project)): result_hash,
            },
        }
        if edit_state(project) != expected:
            raise ValueError("Project changed during staging; no edit was installed.")
        _replace_current_document(staged, document)
        replaced = True
        after_state = {
            **before_state,
            "project_files": {
                **before_state["project_files"],
                str(document.relative_to(project)): result_hash,
            },
        }
        if edit_state(project) != after_state:
            raise ValueError("Project changed during edit installation.")
        record["status"] = "applied"
        atomic_write_json(root / "outcome.json", record)
    except BaseException:
        if replaced:
            if document.is_file() and file_sha256(document) != result_hash:
                shutil.copyfile(document, root / "conflicting_document.vsz")
            with staged.open("wb") as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
            staged.chmod(original_mode)
            os.replace(staged, document)
        record["status"] = "rolled_back"
        atomic_write_json(root / "outcome.json", record)
        raise
    finally:
        staged.unlink(missing_ok=True)
    return {
        **read_edit_operation(project, review["operation_id"]),
        "export_required": True,
    }
