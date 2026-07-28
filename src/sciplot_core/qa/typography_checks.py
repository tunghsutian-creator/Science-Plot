"""Build publication checks for fonts, semantic labels, units, and panel text."""

from __future__ import annotations

from typing import Any

from sciplot_core.qa.audit_support import (
    _check,
    _font_allowed,
    _font_embedding_evidence,
)


def build_typography_checks(
    *,
    profile: dict[str, Any],
    pdfs: list[dict[str, Any]],
    semantic_labels: dict[str, Any],
    scientific_units: dict[str, Any],
    panel_typography: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check PDF text preservation and exact-current semantic text contracts."""

    typography = (
        profile.get("typography") if isinstance(profile.get("typography"), dict) else {}
    )
    checks = [
        _check(
            "text_objects_preserved",
            passed=all(
                bool(pdf["text_objects"]["text_objects_preserved"]) for pdf in pdfs
            ),
            actual=[pdf["text_objects"]["character_count"] for pdf in pdfs],
            expected="extractable text objects",
            message=(
                "Figure labels must remain PDF text objects rather than "
                "outlined or raster-only text."
            ),
        )
    ]
    embedded_fonts = [
        evidence for pdf in pdfs for evidence in _font_embedding_evidence(pdf)
    ]
    checks.append(
        _check(
            "fonts_embedded",
            passed=bool(embedded_fonts)
            and all(bool(evidence["embedded"]) for evidence in embedded_fonts),
            actual=embedded_fonts,
            expected=True,
            message=(
                "Every visible PDF text face used by the figure must map to "
                "an embedded font resource."
            ),
        )
    )
    allowed_fonts = [
        str(value) for value in typography.get("allowed_font_families", [])
    ]
    used_fonts = sorted({font for pdf in pdfs for font in pdf["text_objects"]["fonts"]})
    checks.append(
        _check(
            "font_families",
            passed=bool(used_fonts)
            and all(_font_allowed(font, allowed_fonts) for font in used_fonts),
            actual=used_fonts,
            expected=allowed_fonts,
            message="PDF text must use one of the profile's approved font families.",
        )
    )
    checks.append(_text_size_check(typography=typography, pdfs=pdfs))
    checks.extend(
        [
            _check(
                "semantic_label_inventory",
                passed=bool(semantic_labels["passed"]),
                actual=semantic_labels,
                expected=(
                    "All labels required by the exact VSZ and publication "
                    "intent are present as PDF text."
                ),
                message=(
                    "Axis, key, direct, exact, and confirmed panel labels must "
                    "survive into the final PDF."
                ),
                severity="error" if semantic_labels["available"] else "warning",
            ),
            _check(
                "scientific_unit_expression",
                passed=bool(scientific_units["passed"]),
                actual=scientific_units,
                expected=(
                    "Visible units use multiplication and negative exponents "
                    "without a solidus; mathematical variable ratios remain unchanged."
                ),
                message=(
                    "Axis, colorbar, free, and key unit expressions must follow "
                    "the global negative-exponent product contract."
                ),
                severity="error" if scientific_units["available"] else "warning",
            ),
            _check(
                "panel_label_typography",
                passed=bool(panel_typography["passed"]),
                actual=panel_typography,
                expected=panel_typography.get("expected") or "not applicable",
                message=(
                    "Multipart panel labels must use their role-specific "
                    "final-size typography."
                ),
                severity="error" if panel_typography["applicable"] else "warning",
            ),
        ]
    )
    return checks


def _text_size_check(
    *,
    typography: dict[str, Any],
    pdfs: list[dict[str, Any]],
) -> dict[str, Any]:
    minimum_size = float(typography.get("minimum_text_size_pt") or 0.0)
    minimum_math_script_size = float(
        typography.get("minimum_math_script_size_pt") or minimum_size
    )
    maximum_size = float(typography.get("maximum_text_size_pt") or float("inf"))
    minima = [pdf["text_objects"]["ordinary_minimum_size_pt"] for pdf in pdfs]
    script_minima = [pdf["text_objects"]["math_script_minimum_size_pt"] for pdf in pdfs]
    maxima = [pdf["text_objects"]["maximum_size_pt"] for pdf in pdfs]
    passed = all(
        minimum is not None
        and maximum is not None
        and float(minimum) >= minimum_size - 0.01
        and float(maximum) <= maximum_size + 0.01
        and (
            script_minimum is None
            or float(script_minimum) >= minimum_math_script_size - 0.01
        )
        for minimum, script_minimum, maximum in zip(
            minima,
            script_minima,
            maxima,
            strict=True,
        )
    )
    return _check(
        "text_size_range",
        passed=passed,
        actual={
            "ordinary_minimum_pt": minima,
            "math_script_minimum_pt": script_minima,
            "maximum_pt": maxima,
        },
        expected={
            "ordinary_minimum_pt": minimum_size,
            "math_script_minimum_pt": minimum_math_script_size,
            "maximum_pt": maximum_size,
        },
        message=(
            "Ordinary PDF text and reduced mathematical scripts must stay "
            "within final-size ranges."
        ),
    )
