"""Find, rewrite, and audit scientific unit expressions in plot text."""

from __future__ import annotations

from typing import Any
from sciplot_core.policy import (
    SCIENTIFIC_UNIT_DIVISION_STYLE,
    SCIENTIFIC_UNIT_EXPONENT_STYLE,
    SCIENTIFIC_UNIT_EXPRESSION_CONTRACT_VERSION,
    SCIENTIFIC_UNIT_SOLIDUS_ALLOWED,
)

from sciplot_core.materials_rules.unit_data import (
    _UNIT_TEXT_EDGE_PUNCTUATION,
    _PLOT_TEXT_TOKEN_RE,
    _BRACKET_PAIRS,
    _BRACKET_OPEN_BY_CLOSE,
)

from sciplot_core.materials_rules.unit_formatting import (
    _looks_like_unit_solidus_expression,
    format_unit_label,
)


def _balanced_bracket_spans(value: str) -> list[tuple[int, int]]:
    stack: list[tuple[str, int]] = []
    spans: list[tuple[int, int]] = []
    for index, character in enumerate(value):
        if character in _BRACKET_PAIRS:
            stack.append((character, index))
            continue
        expected_open = _BRACKET_OPEN_BY_CLOSE.get(character)
        if expected_open is None or not stack:
            continue
        open_character, open_index = stack[-1]
        if open_character != expected_open:
            continue
        stack.pop()
        content_start = open_index + 1
        if _looks_like_unit_solidus_expression(value[content_start:index]):
            spans.append((content_start, index))
    return spans


def _trim_unit_text_candidate(
    value: str,
    start: int,
    end: int,
) -> tuple[int, int]:
    while start < end and value[start] in _UNIT_TEXT_EDGE_PUNCTUATION:
        start += 1
    while start < end and value[end - 1] in _UNIT_TEXT_EDGE_PUNCTUATION:
        end -= 1
    return start, end


def _unit_solidus_text_spans(value: object) -> list[tuple[int, int]]:
    """Locate unit-only solidus expressions anywhere in visible plot text."""

    text = str(value or "")
    if not text or "/" not in text:
        return []
    if _looks_like_unit_solidus_expression(text):
        return [(0, len(text))]

    bracket_spans = _balanced_bracket_spans(text)
    # Prefer outer unit-bearing qualifiers.  This lets ``(W/(m K))`` replace
    # the complete outer content instead of leaving denominator parentheses
    # behind, while still supporting a nested ``[K/min]`` qualifier in prose.
    selected: list[tuple[int, int]] = []
    for span in sorted(
        bracket_spans,
        key=lambda item: (item[0], -(item[1] - item[0])),
    ):
        if any(left <= span[0] and span[1] <= right for left, right in selected):
            continue
        selected.append(span)

    tokens = list(_PLOT_TEXT_TOKEN_RE.finditer(text))
    candidates: list[tuple[int, int]] = []
    maximum_window_tokens = 8
    for left_index, left_token in enumerate(tokens):
        for right_index in range(
            left_index,
            min(len(tokens), left_index + maximum_window_tokens),
        ):
            right_token = tokens[right_index]
            start, end = _trim_unit_text_candidate(
                text,
                left_token.start(),
                right_token.end(),
            )
            candidate = text[start:end]
            if (
                "/" not in candidate
                or "\n" in candidate
                or "\t" in candidate
                or not _looks_like_unit_solidus_expression(candidate)
            ):
                continue
            candidates.append((start, end))

    slash_positions = [
        index for index, character in enumerate(text) if character == "/"
    ]
    for slash_position in slash_positions:
        if any(left <= slash_position < right for left, right in selected):
            continue
        covering = [
            span
            for span in candidates
            if span[0] <= slash_position < span[1]
            and not any(
                max(span[0], left) < min(span[1], right) for left, right in selected
            )
        ]
        if not covering:
            continue
        selected.append(
            max(
                covering,
                key=lambda item: (item[1] - item[0], -item[0]),
            )
        )
    return sorted(selected)


def format_plot_text_units(value: object) -> str:
    """Normalize unit qualifiers in plot text without rewriting variable ratios."""

    text = str(value or "")
    for start, end in reversed(_unit_solidus_text_spans(text)):
        text = f"{text[:start]}{format_unit_label(text[start:end])}{text[end:]}"
    return text


def unit_solidus_violations(value: object) -> list[dict[str, str]]:
    """Return every unit-only solidus expression still visible in plot text."""

    text = str(value or "")
    return [
        {
            "expression": text[start:end],
            "replacement": format_unit_label(text[start:end]),
        }
        for start, end in _unit_solidus_text_spans(text)
    ]


def scientific_unit_expression_contract() -> dict[str, Any]:
    """Return the source-controlled unit typography section of the plot contract."""

    return {
        "kind": "sciplot_scientific_unit_expression_contract",
        "version": SCIENTIFIC_UNIT_EXPRESSION_CONTRACT_VERSION,
        "division_style": SCIENTIFIC_UNIT_DIVISION_STYLE,
        "factor_separator": "space",
        "exponent_style": SCIENTIFIC_UNIT_EXPONENT_STYLE,
        "solidus_allowed_in_display_units": SCIENTIFIC_UNIT_SOLIDUS_ALLOWED,
        "input_solidus_compatibility": True,
        "dimensionless_variable_ratios_are_units": False,
        "scope": [
            "axis_labels",
            "colorbar_labels",
            "free_plot_labels",
            "legend_and_key_unit_qualifiers",
            "delivered_plot_data_units",
            "analysis_metric_units",
        ],
        "examples": {
            "kJ/m2": "kJ m⁻²",
            "W/g": "W g⁻¹",
            "%/C": "% °C⁻¹",
            "1/Pa": "Pa⁻¹",
            "rad/s": "rad s⁻¹",
        },
        "excluded_expression_examples": [
            "σ/σ₀",
            "G′/G′ₘ",
        ],
    }
