"""Preview and adopt source-preserving edits from one bound visible VSZ."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import existing_file_sha256, file_sha256
from sciplot_core.project_manifest import locked_intake_project_manifest
from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
from sciplot_core.source_coverage.file_snapshots import (
    _assert_snapshot_current,
    _stable_file_snapshot,
)
from sciplot_core.source_coverage.managed_documents import (
    _source_records,
    _verify_prepared_data,
)
from sciplot_core.studio_core.delivery_recovery_state import (
    RecoveryBlocked,
    canonical_path,
    capture_recovery_state,
)


def _audit_candidate(
    candidate: Path, spec_path: Path, *, native_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit, spec = _audit_exact_document_data(
        document_path=candidate, spec_path=spec_path, check_presentation=False,
        native_audit=native_audit,
    )
    snapshots = [
        _stable_file_snapshot(path, label="recovery prepared source")
        for path in _source_records(spec)
    ]
    derived = _verify_prepared_data(spec, snapshots)
    for snapshot in snapshots:
        _assert_snapshot_current(snapshot, label="recovery prepared source")
    return {
        "status": "passed",
        "unit_count": audit["unit_count"],
        "prepared_unit_count": derived["unit_count"],
    }


def preview_delivery_recovery(
    project_dir: Path, candidate: Path | None = None
) -> dict[str, Any]:
    """Read three-way hashes and audit the exact candidate; never change a project."""
    payload: dict[str, Any] = {
        "kind": "sciplot_delivery_recovery_preview",
        "version": 1,
        "status": "blocked",
        "ready_to_apply": False,
        "project": str(project_dir.expanduser().resolve()),
    }
    try:
        state = capture_recovery_state(project_dir, candidate)
        payload.update(state)
        hashes = state["hashes"]
        if hashes["document"] == hashes["candidate"] != hashes["baseline"]:
            raise RecoveryBlocked(
                "already_reconciled",
                "The managed and visible documents already match. Export the current project to refresh its delivery.",
            )
        if hashes["document"] != hashes["baseline"]:
            raise RecoveryBlocked(
                "canonical_diverged",
                "The managed document changed since delivery. Keep both documents; automatic adoption is blocked.",
            )
        if hashes["candidate"] == hashes["baseline"]:
            raise RecoveryBlocked(
                "no_visible_changes", "The visible document has no edits to recover."
            )
        payload["scientific_audit"] = _audit_candidate(
            Path(state["candidate"]), Path(state["document"]).with_name("spec.json")
        )
        if capture_recovery_state(project_dir, candidate) != state:
            raise RecoveryBlocked(
                "changed_during_preview",
                "Recovery inputs changed during the scientific audit; preview again.",
            )
        payload.update(status="ready", ready_to_apply=True)
    except Exception as exc:
        payload.update(
            status="blocked",
            ready_to_apply=False,
            reason_code=exc.code
            if isinstance(exc, RecoveryBlocked)
            else "recovery_validation_failed",
            message=str(exc),
        )
    return payload


def _write_durable(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_document(staged: Path, document: Path) -> None:
    """Small filesystem port used by recovery fault probes."""
    staged.replace(document)


def apply_delivery_recovery(
    project_dir: Path, preview: dict[str, Any]
) -> dict[str, Any]:
    """Revalidate the whole preview, archive the old VSZ and adopt exact candidate bytes.

    A preview is a deterministic state receipt, not an authorization token. No
    caller-provided readiness, source hash or audit result bypasses revalidation.
    The caller owns explicit user confirmation and reopening the current window.
    """
    project = canonical_path(project_dir)
    # Hold exactly one project lock across revalidation and replacement. The
    # internal readers/auditors do not acquire it again (flock is not reentrant).
    with locked_intake_project_manifest(project):
        return _apply_delivery_recovery_locked(project, preview)


def _apply_delivery_recovery_locked(
    project_dir: Path, preview: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(preview, dict) or not isinstance(preview.get("candidate"), str):
        raise ValueError("A complete recovery preview is required.")
    candidate = Path(preview["candidate"])
    fresh = preview_delivery_recovery(project_dir, candidate)
    if fresh != preview:
        raise ValueError(
            "The recovery preview is stale or modified; preview the current project again."
        )
    if fresh.get("ready_to_apply") is not True:
        raise ValueError(str(fresh.get("message") or "This recovery is blocked."))
    project = canonical_path(project_dir)
    document = Path(fresh["document"])
    state = capture_recovery_state(project, candidate)
    expected_state = {key: fresh[key] for key in state}
    if state != expected_state:
        raise ValueError(
            "Recovery inputs changed before adoption; no files were replaced."
        )
    original = _stable_file_snapshot(document, label="recovery managed document")
    original_mode = document.stat().st_mode & 0o777
    adopted = _stable_file_snapshot(candidate, label="recovery visible document")
    if (
        original["sha256"] != state["hashes"]["document"]
        or adopted["sha256"] != state["hashes"]["candidate"]
    ):
        raise ValueError("Recovery document bytes changed before adoption.")
    archive_root = canonical_path(project / ".recovery")
    archive_root.mkdir(mode=0o700, exist_ok=True)
    archive = archive_root / f"delivery_{uuid4().hex}"
    archive.mkdir(parents=True, mode=0o700)
    archived_document = archive / "document.vsz"
    staged: Path | None = None
    replacement_started = False
    try:
        _write_durable(archived_document, original["bytes"])
        _write_durable(
            archive / "preview.json",
            (json.dumps(fresh, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        if file_sha256(archived_document) != original["sha256"]:
            raise OSError("The recovery archive failed its hash check.")
        descriptor, name = tempfile.mkstemp(
            prefix=".document.delivery-recovery-", suffix=".vsz", dir=document.parent
        )
        os.close(descriptor)
        staged = Path(name)
        with staged.open("wb") as handle:
            handle.write(adopted["bytes"])
            handle.flush()
            os.fsync(handle.fileno())
        staged.chmod(original_mode)
        if file_sha256(staged) != adopted["sha256"]:
            raise OSError("The staged recovery document failed its hash check.")
        _assert_snapshot_current(original, label="recovery managed document")
        _assert_snapshot_current(adopted, label="recovery visible document")
        if capture_recovery_state(project, candidate) != state:
            raise ValueError("Recovery inputs changed before replacement.")
        replacement_started = True
        _replace_document(staged, document)
        expected_after = {
            **state,
            "hashes": {**state["hashes"], "document": adopted["sha256"]},
        }
        if capture_recovery_state(project, candidate) != expected_after:
            raise OSError(
                "Recovery inputs or installed document changed during adoption."
            )
    except BaseException:
        if (
            replacement_started
            and archived_document.is_file()
            and existing_file_sha256(document) != original["sha256"]
        ):
            # Preserve an unexpected concurrent document revision as well as the
            # original before rollback; never erase a third writer's only copy.
            if document.is_file() and file_sha256(document) != adopted["sha256"]:
                shutil.copy2(document, archive / "interrupted_document.vsz")
            rollback = document.with_name(
                f".document.delivery-rollback-{uuid4().hex}.vsz"
            )
            try:
                _write_durable(rollback, original["bytes"])
                rollback.chmod(original_mode)
                rollback.replace(document)
                if file_sha256(document) != original["sha256"]:
                    raise OSError(
                        f"Recovery rollback failed; original retained at {archived_document}"
                    )
            finally:
                rollback.unlink(missing_ok=True)
        raise
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return {
        "kind": "sciplot_delivery_recovery_result",
        "version": 1,
        "status": "recovered",
        "project": str(project),
        "document": str(document),
        "candidate": str(candidate.resolve()),
        "archive": str(archived_document),
        "document_sha256": adopted["sha256"],
        "previous_document_sha256": original["sha256"],
        "export_required": True,
    }


__all__ = ["preview_delivery_recovery", "apply_delivery_recovery"]
