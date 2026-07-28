"""Evaluate publication profile checks across all artifacts."""

from __future__ import annotations

from typing import Any

from sciplot_core.qa.accessibility import _series_accessibility_report
from sciplot_core.qa.accessibility_checks import build_accessibility_checks
from sciplot_core.qa.artifact_checks import build_artifact_checks
from sciplot_core.qa.fixed_frame import _fixed_frame_report
from sciplot_core.qa.publication_policy_checks import (
    build_stroke_and_integrity_checks,
    publication_coverage_summary,
)
from sciplot_core.qa.semantic_labels import (
    _panel_typography_report,
    _scientific_unit_expression_report,
    _semantic_label_report,
)
from sciplot_core.qa.stroke_contract import _vsz_stroke_report
from sciplot_core.qa.typography_checks import build_typography_checks


def _publication_qa(
    *,
    profile: dict[str, Any],
    pdfs: list[dict[str, Any]],
    tiffs: list[dict[str, Any]],
    required_formats: dict[str, Any],
    veusz_audit: dict[str, Any] | None,
    publication_intent: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate implemented constraints without claiming journal compliance."""

    fixed_frame = _fixed_frame_report(veusz_audit, publication_intent)
    semantic_labels = _semantic_label_report(
        veusz_audit,
        publication_intent,
        pdfs,
    )
    scientific_units = _scientific_unit_expression_report(veusz_audit)
    panel_typography = _panel_typography_report(semantic_labels, pdfs, profile)
    accessibility = _series_accessibility_report(veusz_audit, pdfs, profile)
    vsz_strokes = _vsz_stroke_report(veusz_audit, profile)

    (
        artifact_checks,
        raster_checks,
        _pairing,
        _width_tolerance,
        _required_set,
    ) = build_artifact_checks(
        profile=profile,
        pdfs=pdfs,
        tiffs=tiffs,
        required_formats=required_formats,
        fixed_frame=fixed_frame,
    )
    checks = artifact_checks
    checks.extend(
        build_typography_checks(
            profile=profile,
            pdfs=pdfs,
            semantic_labels=semantic_labels,
            scientific_units=scientific_units,
            panel_typography=panel_typography,
        )
    )
    checks.extend(raster_checks)
    checks.extend(build_accessibility_checks(accessibility))
    checks.extend(
        build_stroke_and_integrity_checks(
            profile=profile,
            pdfs=pdfs,
            vsz_strokes=vsz_strokes,
        )
    )
    blocking_failures = [
        check
        for check in checks
        if check["status"] == "failed" and check["severity"] == "error"
    ]
    coverage, unchecked_constraints, limitations = publication_coverage_summary(
        fixed_frame=fixed_frame,
        accessibility=accessibility,
        semantic_labels=semantic_labels,
        panel_typography=panel_typography,
        scientific_units=scientific_units,
        vsz_strokes=vsz_strokes,
    )
    coverage_complete = not unchecked_constraints
    return {
        "kind": "sciplot_publication_qa",
        "version": 2,
        "status": "passed" if not blocking_failures else "needs_revision",
        "checked_constraints_passed": not blocking_failures,
        "coverage_complete": coverage_complete,
        "journal_compliance_established": False,
        "journal_compliance_status": (
            "not_established_profile_scope"
            if coverage_complete
            else "not_established_incomplete_coverage"
        ),
        "status_semantics": (
            "passed means only the implemented constraints passed; it is not "
            "a claim of journal compliance"
        ),
        "profile": profile,
        "required_formats": required_formats,
        "checks": checks,
        "blocking_check_ids": [check["id"] for check in blocking_failures],
        "coverage": coverage,
        "veusz_document_audit": veusz_audit,
        "limitations": limitations,
        "unchecked_constraints": unchecked_constraints,
        "invariants": {
            "scientific_outcome_agnostic": True,
            "effect_size_gate_applied": False,
            "significance_gate_applied": False,
        },
    }
