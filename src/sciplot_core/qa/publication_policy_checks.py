"""Build stroke/integrity checks and summarize QA coverage limitations."""

from __future__ import annotations

from typing import Any

from sciplot_core.qa.audit_support import _check


def build_stroke_and_integrity_checks(
    *,
    profile: dict[str, Any],
    pdfs: list[dict[str, Any]],
    vsz_strokes: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check partial PDF strokes, complete VSZ strokes, and integrity policy."""

    stroke_profile = (
        profile.get("strokes") if isinstance(profile.get("strokes"), dict) else {}
    )
    stroke_ranges = [pdf["strokes"] for pdf in pdfs]
    minimum_stroke = float(stroke_profile.get("minimum_width_pt") or 0.0)
    maximum_stroke = float(stroke_profile.get("maximum_width_pt") or float("inf"))
    stroke_passed = all(
        stroke["minimum_width_pt"] is None
        or (
            float(stroke["minimum_width_pt"]) >= minimum_stroke - 0.01
            and float(stroke["maximum_width_pt"]) <= maximum_stroke + 0.01
        )
        for stroke in stroke_ranges
    )
    checks = [
        _check(
            "stroke_range_pdf_partial",
            passed=stroke_passed,
            actual=stroke_ranges,
            expected={
                "minimum_pt": minimum_stroke,
                "maximum_pt": maximum_stroke,
            },
            message=(
                "Measured PDF strokes should fit the profile; filled Veusz "
                "curve paths remain a documented limitation."
            ),
            severity="warning",
        ),
        _check(
            "stroke_range_current_vsz_complete",
            passed=bool(vsz_strokes["passed"]),
            actual=vsz_strokes,
            expected=vsz_strokes["expected"],
            message=(
                "All active physical stroke settings in the exact current VSZ "
                "must fit the profile range."
            ),
            severity="error" if vsz_strokes["available"] else "warning",
        ),
    ]
    integrity = (
        profile.get("integrity") if isinstance(profile.get("integrity"), dict) else {}
    )
    checks.append(
        _check(
            "scientific_integrity_policy",
            passed=(
                integrity.get("scientific_outcome_agnostic") is True
                and integrity.get("significance_required") is False
                and integrity.get("silent_data_omission_allowed") is False
            ),
            actual=integrity,
            expected={
                "scientific_outcome_agnostic": True,
                "significance_required": False,
                "silent_data_omission_allowed": False,
            },
            message=(
                "Publication QA must never require a significant, separated, "
                "or visually exciting result."
            ),
        )
    )
    return checks


def publication_coverage_summary(
    *,
    fixed_frame: dict[str, Any],
    accessibility: dict[str, Any],
    semantic_labels: dict[str, Any],
    panel_typography: dict[str, Any],
    scientific_units: dict[str, Any],
    vsz_strokes: dict[str, Any],
) -> tuple[dict[str, bool], list[str], list[str]]:
    """Return coverage flags, unchecked constraints, and reader limitations."""

    coverage = {
        "fixed_frame_current_vsz": bool(fixed_frame["coverage_complete"]),
        "rendered_colour_vision_and_grayscale_accessibility": bool(
            accessibility["coverage_complete"]
        ),
        "semantic_panel_and_required_label_inventory": bool(
            semantic_labels["coverage_complete"]
        )
        and bool(panel_typography["coverage_complete"]),
        "scientific_unit_expression_current_vsz": bool(
            scientific_units["coverage_complete"]
        ),
        "complete_stroke_coverage_for_filled_veusz_paths": bool(
            vsz_strokes["coverage_complete"]
        ),
    }
    unchecked = [
        constraint for constraint, complete in coverage.items() if not complete
    ]
    limitations: list[str] = []
    if not vsz_strokes["coverage_complete"]:
        limitations.append(
            "Complete stroke coverage requires a successfully loaded exact current VSZ document."
        )
    if not accessibility["coverage_complete"]:
        limitations.append(
            "Rendered colour accessibility requires resolved current-VSZ colours confirmed in final PDF "
            "vectors or embedded rasters."
        )
    if not semantic_labels["coverage_complete"]:
        limitations.append(
            "Semantic label coverage requires current-VSZ label inventory and final PDF text objects."
        )
    if not scientific_units["coverage_complete"]:
        limitations.append(
            "Scientific unit-expression coverage requires a successfully "
            "loaded exact-current VSZ semantic-label inventory."
        )
    if not fixed_frame["coverage_complete"]:
        limitations.append(
            "Fixed-frame coverage requires Veusz-computed bounds from the exact current VSZ document."
        )
    return coverage, unchecked, limitations
