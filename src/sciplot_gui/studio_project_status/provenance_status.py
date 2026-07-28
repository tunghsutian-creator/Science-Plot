"""Evaluate source, request, document, and evidence provenance."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.delivery import verify_delivery_package
from sciplot_core.policy import DELIVERY_DIR
from sciplot_core.studio_figure_set_contract import (
    is_primary_figure_set_export_scope as _is_primary_figure_set_export_scope,
)
from sciplot_core.study_model import verify_output_package_contract

from sciplot_gui.studio_project_status.live_document import (
    _evidence_path,
)


def _nonempty_evidence_path(
    value: object,
    *,
    evidence_root: Path,
) -> bool:
    candidate = _evidence_path(value, evidence_root=evidence_root)
    if candidate is None:
        return False
    try:
        if candidate.is_file():
            return candidate.stat().st_size > 0
        if candidate.is_dir():
            return any(item.is_file() for item in candidate.rglob("*"))
    except OSError:
        return False
    return False


def _provenance_status(
    *,
    latest_path: Path | None,
    latest_run: dict[str, Any],
    transform_status: str,
    raw_archive_path: Path | None,
    package: object,
    delivery: object,
    mapping: dict[str, Any],
    qa: dict[str, Any],
    source: dict[str, Any],
    figure_set_export_scope: object = None,
    figure_set_scope_status: str = "unknown",
) -> dict[str, Any]:
    evidence_root = latest_path.parent if latest_path is not None else None
    raw_archive_current = bool(
        evidence_root is not None
        and raw_archive_path is not None
        and _nonempty_evidence_path(
            str(raw_archive_path),
            evidence_root=evidence_root,
        )
    )
    package_verification = (
        verify_output_package_contract(
            package,
            output_dir=evidence_root,
            manifest=latest_run,
        )
        if evidence_root is not None
        else {"passed": False, "failed_checks": ["evidence_root_missing"]}
    )
    delivery_verification = (
        verify_delivery_package(
            delivery,
            expected_root=evidence_root / DELIVERY_DIR,
        )
        if evidence_root is not None
        else {"passed": False, "failed_checks": ["evidence_root_missing"]}
    )
    package_current = package_verification.get("passed") is True
    delivery_current = delivery_verification.get("passed") is True
    run_evidence_complete = bool(
        latest_path is not None
        and transform_status in {"runtime_recorded", "confirmed"}
        and raw_archive_current
        and package_current
        and delivery_current
    )
    mapping_current = mapping.get("status") in {
        "not_applied",
        "verified",
    }
    source_current = source.get("audit_status") == "matches_last_run_lineage"
    current_evidence = bool(
        run_evidence_complete
        and source_current
        and mapping_current
        and qa.get("artifact_qa_current") is True
    )
    normalized_figure_scope = (
        dict(figure_set_export_scope)
        if _is_primary_figure_set_export_scope(figure_set_export_scope)
        else None
    )
    full_figure_set_scope = bool(
        normalized_figure_scope is not None
        and figure_set_scope_status in {"persisted", "recomputed_current_project"}
    )
    full_project_scope = bool(
        figure_set_scope_status == "not_applicable" or full_figure_set_scope
    )
    delivery_scope_known = full_project_scope
    primary_figure_evidence_current = bool(current_evidence and full_figure_set_scope)
    full_project_evidence_current = bool(current_evidence and full_project_scope)
    audit_pending = bool(
        source.get("audit_status") == "not_computed"
        or mapping.get("status") == "audit_pending"
    )
    current_result_awaiting_audit = bool(
        run_evidence_complete
        and qa.get("artifact_qa_current") is True
        and audit_pending
        and delivery_scope_known
    )
    return {
        "status": (
            "unknown_or_incomplete_figure_set_scope"
            if not delivery_scope_known
            else "current_full_project_evidence"
            if full_project_evidence_current
            else "current_primary_figure_evidence"
            if primary_figure_evidence_current
            else "audit_pending_for_current_project"
            if current_result_awaiting_audit
            else "incomplete_or_stale_project_evidence"
        ),
        "complete": full_project_evidence_current,
        "full_project_evidence_current": full_project_evidence_current,
        "primary_figure_evidence_current": primary_figure_evidence_current,
        "figure_set_export_scope": json_safe(normalized_figure_scope),
        "figure_set_export_scope_status": figure_set_scope_status,
        "delivery_scope_known": delivery_scope_known,
        "delivery_scope": (
            "full_figure_set_project_delivery"
            if full_figure_set_scope
            else "project_delivery"
            if full_project_scope
            else "unknown"
        ),
        "full_figure_set_delivery_complete": (True if full_figure_set_scope else None),
        "audit_pending": current_result_awaiting_audit,
        "run_evidence_complete": run_evidence_complete,
        "request_snapshot_current": latest_path is not None,
        "source_current": source_current,
        "artifact_qa_current": qa.get("artifact_qa_current") is True,
        "mapping_current": mapping_current,
        "transform_status": transform_status,
        "raw_archive": (
            str(raw_archive_path) if raw_archive_path is not None else None
        ),
        "raw_archive_current": raw_archive_current,
        "package_complete": (
            isinstance(package, dict) and package.get("complete") is True
        ),
        "package_current": package_current,
        "package_verification": json_safe(package_verification),
        "project_delivery_complete": (
            isinstance(delivery, dict) and delivery.get("complete") is True
        ),
        "project_delivery_current": delivery_current,
        "delivery_verification": json_safe(delivery_verification),
        "primary_figure_delivery_current": bool(
            delivery_current and full_figure_set_scope
        ),
        "full_project_delivery_current": bool(delivery_current and full_project_scope),
    }
