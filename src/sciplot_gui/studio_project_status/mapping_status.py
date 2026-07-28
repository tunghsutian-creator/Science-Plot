"""Bind mapping execution evidence to artifact QA."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.data_mapping import resolve_data_mapping_request

from sciplot_gui.studio_project_status.project_runs import (
    _canonical_json_sha256,
)


def _mapping_application_from_run(
    latest_run: dict[str, Any],
) -> dict[str, Any]:
    application = latest_run.get("data_mapping_application")
    if isinstance(application, dict):
        return application
    result = (
        latest_run.get("result") if isinstance(latest_run.get("result"), dict) else {}
    )
    application = result.get("data_mapping_application")
    return application if isinstance(application, dict) else {}


def _mapping_coverage_from_run(
    latest_run: dict[str, Any],
) -> dict[str, Any]:
    coverage = latest_run.get("data_mapping_coverage")
    if isinstance(coverage, dict):
        return coverage
    result = (
        latest_run.get("result") if isinstance(latest_run.get("result"), dict) else {}
    )
    coverage = result.get("data_mapping_coverage")
    return coverage if isinstance(coverage, dict) else {}


def _bind_mapping_to_artifact_qa(
    mapping: dict[str, Any],
    *,
    artifact_qa_current: bool,
) -> dict[str, Any]:
    updated = dict(mapping)
    base_verified = updated.get("verification_base_valid") is True
    evidence_current = bool(base_verified and artifact_qa_current)
    updated["artifact_qa_current"] = bool(artifact_qa_current)
    updated["evidence_current"] = evidence_current
    if updated.get("status") not in {
        "not_applied",
        "invalid",
        "audit_pending",
    }:
        updated["status"] = "verified" if evidence_current else "unverified"
    return updated


def _mapping_status(
    request: dict[str, Any],
    *,
    request_path: Path,
    latest_run: dict[str, Any],
    request_error: str | None,
    artifact_qa_current: bool,
    audit_mapping: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if request_error is not None:
        return (
            {
                "status": "invalid",
                "coverage_status": "invalid",
                "reason": f"The current request is invalid: {request_error}",
                "verification_base_valid": False,
                "artifact_qa_current": False,
                "evidence_current": False,
            },
            request,
        )
    if not request.get("data_mapping_execution"):
        return (
            {
                "status": "not_applied",
                "coverage_status": "not_applicable",
                "reason": "The project uses its confirmed source directly.",
                "verification_base_valid": True,
                "artifact_qa_current": bool(artifact_qa_current),
                "evidence_current": bool(artifact_qa_current),
            },
            request,
        )
    if not audit_mapping:
        return (
            {
                "status": "audit_pending",
                "coverage_status": "not_computed",
                "reason": (
                    "Use Refresh Audit to revalidate the current data-mapping "
                    "application and rendered-source coverage."
                ),
                "verification_base_valid": False,
                "artifact_qa_current": bool(artifact_qa_current),
                "evidence_current": False,
            },
            request,
        )
    try:
        effective, application = resolve_data_mapping_request(
            request,
            base_dir=request_path.parent,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        return (
            {
                "status": "invalid",
                "coverage_status": "unknown",
                "reason": str(exc),
                "verification_base_valid": False,
                "artifact_qa_current": False,
                "evidence_current": False,
            },
            request,
        )
    coverage = _mapping_coverage_from_run(latest_run)
    application_payload = application if isinstance(application, dict) else {}
    run_application = _mapping_application_from_run(latest_run)
    application_status = str(application_payload.get("status") or "validated")
    coverage_status = str(coverage.get("status") or "not_run")
    application_matches = bool(
        application_payload
        and run_application
        and _canonical_json_sha256(application_payload)
        == _canonical_json_sha256(run_application)
    )
    base_verified = bool(
        application_status == "validated"
        and coverage_status == "passed"
        and application_matches
    )
    if application_status != "validated":
        status = "invalid"
        reason = "The current data-mapping application is not validated."
    elif coverage_status != "passed":
        status = "unverified"
        reason = (
            "Current-run mapping coverage has not passed; "
            f"reported status is {coverage_status}."
        )
    elif not application_matches:
        status = "unverified"
        reason = (
            "Current-run coverage is not bound to the current data_mapping_application."
        )
    else:
        status = "unverified"
        reason = "Current mapping evidence is awaiting artifact-QA binding."
    mapping = {
        "status": status,
        "application_status": application_status,
        "coverage_status": coverage_status,
        "proposal_id": application_payload.get("proposal_id"),
        "source_root": application_payload.get("source_root"),
        "effective_input": application_payload.get("effective_input"),
        "application_matches_current_run": application_matches,
        "verification_base_valid": base_verified,
        "reason": reason,
    }
    return (
        _bind_mapping_to_artifact_qa(
            mapping,
            artifact_qa_current=artifact_qa_current,
        ),
        effective,
    )
