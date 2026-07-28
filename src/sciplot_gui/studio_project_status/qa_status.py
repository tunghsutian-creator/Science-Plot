"""Evaluate standalone and managed-run QA status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_gui.studio_project_status.export_status import (
    _verify_export_artifacts,
    _standalone_qa_report_current,
)


def _qa_display_status(
    *,
    artifact_status: str,
    ready: bool,
    current_document: bool,
    exports_current: bool,
) -> tuple[str, bool]:
    artifact_qa_current = bool(
        current_document
        and exports_current
        and artifact_status in {"passed", "not_required"}
    )
    if not current_document:
        status = "stale_for_current_document"
    elif not exports_current:
        status = "stale_or_invalid_export_artifacts"
    elif ready and artifact_qa_current:
        status = "passed_for_current_document"
    else:
        status = "failed_for_current_document"
    return status, artifact_qa_current


def _qa_status(
    *,
    evidence: dict[str, Any],
    evidence_path: Path | None,
    saved_sha256: str | None,
    modified: bool,
    standalone: bool,
) -> dict[str, Any]:
    if not evidence:
        return {
            "status": "not_run",
            "artifact_status": "not_run",
            "ready_to_use": False,
            "current_document": False,
            "exports_current": False,
            "qa_report_current": False,
            "artifact_qa_current": False,
            "export_artifacts": {
                "status": "not_run",
                "current": False,
                "issues": [],
            },
            "evidence": None,
        }
    qa = (
        evidence.get("artifact_qa")
        if standalone and isinstance(evidence.get("artifact_qa"), dict)
        else evidence.get("qa")
        if isinstance(evidence.get("qa"), dict)
        else {}
    )
    artifact_status = str(qa.get("status") or "not_run")
    evidence_hash = (
        evidence.get("document_sha256")
        if standalone
        else evidence.get("exported_document_hash")
        or (
            evidence.get("document_state", {}).get("current_hash")
            if isinstance(evidence.get("document_state"), dict)
            else None
        )
    )
    ready = (
        evidence.get("export_ready") is True
        if standalone
        else evidence.get("ready_to_use") is True
    )
    document_hash_current = bool(
        not modified
        and saved_sha256
        and evidence_hash
        and saved_sha256 == evidence_hash
    )
    export_artifacts = _verify_export_artifacts(
        evidence=evidence,
        evidence_path=evidence_path,
        standalone=standalone,
    )
    qa_report_current = (
        _standalone_qa_report_current(
            evidence=evidence,
            evidence_path=evidence_path,
            embedded_qa=qa,
        )
        if standalone
        else True
    )
    evidence_artifacts_current = bool(
        export_artifacts["current"] is True and qa_report_current
    )
    current_document = bool(document_hash_current and evidence_artifacts_current)
    status, artifact_qa_current = _qa_display_status(
        artifact_status=artifact_status,
        ready=bool(ready),
        current_document=current_document,
        exports_current=evidence_artifacts_current,
    )
    return {
        "status": status,
        "artifact_status": artifact_status,
        "ready_to_use": bool(ready),
        "current_document": current_document,
        "document_hash_current": document_hash_current,
        "exports_current": export_artifacts["current"] is True,
        "qa_report_current": qa_report_current,
        "artifact_qa_current": artifact_qa_current,
        "scope": "exact_current_artifact_qa",
        "evidence_document_sha256": evidence_hash,
        "evidence": str(evidence_path) if evidence_path is not None else None,
        "export_artifacts": export_artifacts,
        "state": evidence.get("state"),
    }
