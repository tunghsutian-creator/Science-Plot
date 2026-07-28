"""Build publication checks for rendered color and non-color distinction."""

from __future__ import annotations

from typing import Any

from sciplot_core.qa.audit_support import _check


def build_accessibility_checks(
    accessibility: dict[str, Any],
) -> list[dict[str, Any]]:
    """Translate accessibility evidence into four publication checks."""

    severity = "error" if accessibility["available"] else "warning"
    return [
        _check(
            "series_colors_rendered",
            passed=bool(accessibility["coverage_complete"]),
            actual={
                "unresolved_color_paths": accessibility.get(
                    "unresolved_color_paths", []
                ),
                "colors_not_confirmed_in_pdf": accessibility.get(
                    "colors_not_confirmed_in_pdf", []
                ),
                "series": accessibility.get("series", []),
                "color_scales": accessibility.get("color_scales", []),
            },
            expected=(
                "Every visible semantic series colour or colour scale resolves "
                "from the current VSZ and is confirmed in the PDF."
            ),
            message=(
                "Colour simulations must be bound to colours actually rendered "
                "in the final PDF."
            ),
            severity=severity,
        ),
        _check(
            "non_color_series_distinction",
            passed=bool(accessibility.get("non_color_passed")),
            actual=accessibility.get("pairs", []),
            expected=(
                "Every same-graph series pair has a distinct line/marker "
                "signature, direct labels, or explicit labelled categorical positions."
            ),
            message="Series identity must not depend on colour alone.",
            severity=severity,
        ),
        _check(
            "colour_vision_simulation",
            passed=bool(accessibility.get("colour_vision_passed")),
            actual=accessibility,
            expected=accessibility.get("thresholds", {}),
            message=(
                "Protanopia, deuteranopia, and tritanopia simulations must "
                "retain colour or non-colour separation."
            ),
            severity=severity,
        ),
        _check(
            "grayscale_accessibility",
            passed=bool(accessibility.get("grayscale_passed")),
            actual=accessibility,
            expected=accessibility.get("thresholds", {}),
            message=(
                "Grayscale review must retain luminance or non-colour "
                "separation for every series pair."
            ),
            severity=severity,
        ),
    ]
