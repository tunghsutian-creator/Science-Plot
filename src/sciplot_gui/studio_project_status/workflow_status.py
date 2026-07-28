"""Resolve project workflow state and result targets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_gui.studio_project_status.live_document import (
    _evidence_path,
)


def _project_audit_state(status: dict[str, Any]) -> str:
    if status.get("mode") != "project":
        return "not_applicable"
    if status.get("document_scope") == "project_secondary_standalone_receipt":
        return "not_applicable"
    source = status.get("source") if isinstance(status.get("source"), dict) else {}
    mapping = status.get("mapping") if isinstance(status.get("mapping"), dict) else {}
    provenance = (
        status.get("provenance") if isinstance(status.get("provenance"), dict) else {}
    )
    if provenance.get("full_project_evidence_current") is True:
        return "current"
    if provenance.get("primary_figure_evidence_current") is True:
        return "current_primary_figure"
    if provenance.get("delivery_scope_known") is not True:
        return "blocked"
    source_audit = str(source.get("audit_status") or "")
    mapping_status = str(mapping.get("status") or "")
    if source_audit == "audit_failed" or mapping_status in {
        "audit_failed",
        "invalid",
    }:
        return "failed"
    if source_audit == "not_computed" or mapping_status == "audit_pending":
        return "pending"
    return "stale"


def _workflow_status(
    status: dict[str, Any],
    *,
    exporting: bool = False,
) -> dict[str, Any]:
    if exporting:
        state = "exporting"
        message = "Saving and validating the exact-current Veusz document."
    else:
        document = (
            status.get("document") if isinstance(status.get("document"), dict) else {}
        )
        qa = status.get("qa") if isinstance(status.get("qa"), dict) else {}
        provenance = (
            status.get("provenance")
            if isinstance(status.get("provenance"), dict)
            else {}
        )
        result_ready = bool(
            qa.get("artifact_qa_current") is True
            and (
                status.get("mode") == "standalone_vsz"
                or status.get("document_scope")
                == "project_secondary_standalone_receipt"
                or (
                    provenance.get("project_delivery_current") is True
                    and provenance.get("delivery_scope_known") is True
                )
            )
        )
        if result_ready:
            state = "ready"
            message = "Exact-current result artifacts are ready."
        elif (
            document.get("modified") is True
            or qa.get("evidence") is None
            or qa.get("document_hash_current") is False
        ):
            state = "editing"
            message = "Save and export the current Veusz document when ready."
        else:
            state = "needs_fix"
            message = "The current export or delivery needs review."
    return {
        "state": state,
        "result_ready": state == "ready",
        "audit_state": _project_audit_state(status),
        "message": message,
    }


def _result_targets(
    *,
    live_document: dict[str, Any],
    qa: dict[str, Any],
    evidence_path: Path | None,
    delivery: object = None,
    delivery_current: bool = False,
) -> dict[str, dict[str, Any]]:
    pdf_path: Path | None = None
    pdf_sha256: str | None = None
    export_artifacts = (
        qa.get("export_artifacts")
        if isinstance(qa.get("export_artifacts"), dict)
        else {}
    )
    records = (
        export_artifacts.get("records")
        if isinstance(export_artifacts.get("records"), list)
        else []
    )
    evidence_root = (
        evidence_path.parent.expanduser().resolve()
        if evidence_path is not None
        else None
    )
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("format") != "pdf"
            or record.get("current") is not True
            or evidence_root is None
        ):
            continue
        candidate = _evidence_path(
            record.get("path"),
            evidence_root=evidence_root,
        )
        if candidate is not None and candidate.is_file():
            pdf_path = candidate
            pdf_sha256 = (
                str(
                    record.get("expected_sha256") or record.get("actual_sha256") or ""
                ).strip()
                or None
            )
            break

    delivery_root: Path | None = None
    if (
        delivery_current
        and qa.get("artifact_qa_current") is True
        and isinstance(delivery, dict)
        and evidence_root is not None
    ):
        candidate = _evidence_path(
            delivery.get("delivery_root") or delivery.get("path"),
            evidence_root=evidence_root,
        )
        if candidate is not None and candidate.is_dir():
            delivery_root = candidate

    document_value = live_document.get("path")
    document_path = (
        Path(str(document_value)).expanduser().resolve()
        if isinstance(document_value, str) and document_value.strip()
        else None
    )
    return {
        "pdf": {
            "path": str(pdf_path) if pdf_path is not None else None,
            "evidence_root": (
                str(evidence_root) if evidence_root is not None else None
            ),
            "sha256": pdf_sha256,
            "current": bool(
                pdf_path is not None and qa.get("artifact_qa_current") is True
            ),
            "available": False,
        },
        "delivery": {
            "path": (str(delivery_root) if delivery_root is not None else None),
            "evidence_root": (
                str(evidence_root) if evidence_root is not None else None
            ),
            "current": delivery_root is not None,
            "available": False,
        },
        "vsz": {
            "path": (str(document_path) if document_path is not None else None),
            "reveal_path": (
                str(document_path.parent) if document_path is not None else None
            ),
            "evidence_root": (
                str(document_path.parent) if document_path is not None else None
            ),
            "current": bool(document_path is not None and document_path.is_file()),
            "available": False,
        },
    }


def _finalize_status(
    status: dict[str, Any],
    *,
    exporting: bool = False,
) -> dict[str, Any]:
    updated = dict(status)
    workflow = _workflow_status(updated, exporting=exporting)
    updated["workflow"] = workflow
    results = updated.get("results") if isinstance(updated.get("results"), dict) else {}
    finalized_results: dict[str, Any] = {}
    for key in ("pdf", "delivery", "vsz"):
        target = (
            dict(results.get(key))
            if isinstance(results.get(key), dict)
            else {
                "path": None,
                "current": False,
            }
        )
        target["available"] = bool(
            not exporting
            and target.get("current") is True
            and (target.get("reveal_path") if key == "vsz" else target.get("path"))
        )
        finalized_results[key] = target
    updated["results"] = finalized_results
    return updated
