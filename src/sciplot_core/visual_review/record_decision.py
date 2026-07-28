"""Record one immutable human visual-review decision."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256

from sciplot_core.visual_review.transaction import (
    FINAL_SIZE_VISUAL_REVIEW_VERSION,
    FINAL_SIZE_VISUAL_DECISION_VERSION,
    REVIEW_SURFACE,
    _json_bytes,
    _bytes_sha256,
    _replace_files_transactionally,
)

from sciplot_core.visual_review.report_text import (
    _markdown_text,
    _html_text,
)

from sciplot_core.visual_review.decision_validation import (
    _read_json_object_strict,
    _validate_records,
    _validate_summary,
    _validate_manual_source,
    _validate_contact_sheets,
)

from sciplot_core.visual_review.evidence_binding import (
    _validate_acceptance_binding,
    _validate_evidence_binding,
    _validate_existing_decision,
)


def record_final_size_visual_decision(
    review_json: Path,
    *,
    reviewer: str,
    decision: str,
    notes: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Record a decision about uncalibrated previews after strict run binding."""

    review_path = review_json.expanduser().resolve()
    if (
        review_path.name != "final_size_visual_review.json"
        or review_path.parent.name != "final_size_visual_review"
    ):
        raise ValueError(
            "Visual review must use final_size_visual_review/final_size_visual_review.json."
        )
    normalized_decision = str(decision).strip().casefold()
    if normalized_decision not in {"passed", "failed"}:
        raise ValueError("Visual decision must be `passed` or `failed`.")
    normalized_reviewer = str(reviewer).strip()
    if not normalized_reviewer:
        raise ValueError("Visual decision reviewer must be a non-empty name.")

    project_dir = review_path.parent.parent
    acceptance_path = project_dir / "acceptance_summary.json"
    evidence_path = project_dir / "evidence_status.json"
    decision_path = review_path.parent / "manual_visual_review_decision.json"

    payload = _read_json_object_strict(review_path, label="Visual review JSON")
    acceptance = _read_json_object_strict(acceptance_path, label="Acceptance summary")
    evidence = _read_json_object_strict(evidence_path, label="Evidence status")
    if payload.get("kind") != "sciplot_final_size_visual_review":
        raise ValueError("Not a SciPlot final-size visual review artifact.")
    version = payload.get("version")
    if type(version) is not int or version != FINAL_SIZE_VISUAL_REVIEW_VERSION:
        raise ValueError("Unsupported final-size visual review version.")
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise ValueError("Final-size visual review is missing generated_at.")

    records = _validate_records(payload.get("records"))
    contact_sheets, contact_sheet_sources = _validate_contact_sheets(
        payload,
        review_path=review_path,
    )
    summary = _validate_summary(
        payload.get("summary"),
        records=records,
        contact_sheet_count=len(contact_sheets),
    )
    required_checks = _validate_manual_source(
        payload.get("manual_review"), summary=summary
    )
    if normalized_decision == "passed" and summary["automated_status"] != "passed":
        raise ValueError(
            "Cannot pass preview review while automated artifact checks are not passed."
        )

    source_sha256 = file_sha256(review_path)
    _validate_acceptance_binding(
        acceptance,
        acceptance_path=acceptance_path,
        review_path=review_path,
        review_payload=payload,
        records=records,
        contact_sheets=contact_sheets,
        evidence_path=evidence_path,
        decision_path=decision_path,
        source_sha256=source_sha256,
    )
    _validate_evidence_binding(
        evidence,
        acceptance=acceptance,
        generated_at=generated_at,
        record_ids=[record["rule_id"] for record in records],
    )
    if decision_path.exists():
        existing_decision = _read_json_object_strict(
            decision_path,
            label="Existing manual visual decision",
        )
        _validate_existing_decision(
            existing_decision,
            decision_path=decision_path,
            review_path=review_path,
            acceptance=acceptance,
        )

    reviewed_at = datetime.now(UTC).isoformat()
    reviewed_rules = [
        record["rule_id"] for record in records if record["status"] != "not_run"
    ]
    manual_review = {
        "status": "completed",
        "decision": normalized_decision,
        "reviewed_at": reviewed_at,
        "reviewer": normalized_reviewer,
        "review_surface": REVIEW_SURFACE,
        "required_checks": required_checks,
        "reviewed_rule_ids": reviewed_rules,
        "contact_sheets_inspected": [str(path) for path in contact_sheets],
        "contact_sheet_sources": contact_sheet_sources,
        "checks": {
            check_id: normalized_decision == "passed" for check_id in required_checks
        },
        "notes": [str(note).strip() for note in notes if str(note).strip()],
    }
    updated_payload = deepcopy(payload)
    updated_summary = deepcopy(summary)
    updated_summary["manual_visual_status"] = normalized_decision
    updated_summary["manual_reviewed_at"] = reviewed_at
    updated_payload["manual_review"] = manual_review
    updated_payload["summary"] = updated_summary
    review_bytes = _json_bytes(updated_payload)
    review_sha256_after = _bytes_sha256(review_bytes)

    decision_payload = {
        "kind": "sciplot_final_size_visual_decision",
        "version": FINAL_SIZE_VISUAL_DECISION_VERSION,
        "review_source": str(review_path),
        "review_source_sha256_before_decision": source_sha256,
        "review_source_sha256_after_decision": review_sha256_after,
        "automated_status": updated_summary["automated_status"],
        **manual_review,
        "limitations": [
            "This records inspection of uncalibrated screen previews, not final-size legibility.",
            "Scientific claims, calibrated physical-size inspection, and journal compliance remain separate.",
        ],
    }
    decision_bytes = _json_bytes(decision_payload)

    updated_acceptance = deepcopy(acceptance)
    updated_acceptance["visual_review"] = updated_summary
    updated_artifacts = deepcopy(acceptance["artifacts"])
    updated_artifacts["visual_review_json_sha256"] = review_sha256_after
    updated_artifacts["manual_visual_review_decision"] = str(decision_path)
    updated_artifacts["manual_visual_review_decision_sha256"] = _bytes_sha256(
        decision_bytes
    )
    updated_acceptance["artifacts"] = updated_artifacts
    if normalized_decision == "failed":
        updated_acceptance["state"] = "needs_rule_repair"
        updated_acceptance["selected_state"] = "needs_rule_repair"

    updated_evidence = deepcopy(evidence)
    updated_evidence_summary = deepcopy(evidence["summary"])
    updated_evidence_summary["manual_visual_status"] = normalized_decision
    updated_evidence_summary["manual_reviewed_at"] = reviewed_at
    updated_evidence_summary["review_surface"] = REVIEW_SURFACE
    updated_evidence["summary"] = updated_evidence_summary
    updated_acceptance["evidence_status"] = updated_evidence_summary

    markdown_path = review_path.with_suffix(".md")
    html_path = review_path.with_suffix(".html")
    _replace_files_transactionally(
        {
            review_path: review_bytes,
            markdown_path: _markdown_text(updated_payload).encode("utf-8"),
            html_path: _html_text(
                updated_payload,
                contact_sheets,
                parent=html_path.parent,
            ).encode("utf-8"),
            decision_path: decision_bytes,
            acceptance_path: _json_bytes(updated_acceptance),
            evidence_path: _json_bytes(updated_evidence),
        }
    )
    return {
        "decision": decision_payload,
        "decision_path": str(decision_path),
        "review_path": str(review_path),
        "acceptance_summary": str(acceptance_path),
    }
