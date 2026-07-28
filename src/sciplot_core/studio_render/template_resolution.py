"""Resolve template identity and robust scalar summaries used by plot contracts."""

from __future__ import annotations

import math
import sys
from typing import Any
from sciplot_core.style_contract import validate_veusz_template_id


def _request_template(request: dict[str, Any]) -> str:
    template = request.get("template")
    if isinstance(template, str) and template.strip():
        return validate_veusz_template_id(template)
    recipe = request.get("recipe")
    if isinstance(recipe, str) and recipe.strip() and recipe.strip() != "auto":
        from sciplot_recipes.contracts import get_recipe_spec

        return validate_veusz_template_id(get_recipe_spec(recipe).default_template)
    return validate_veusz_template_id("curve")


def _looks_like_wavenumber_axis(axis_info: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return "wavenumber" in text or (
        "cm" in text and ("-1" in text or "−1" in text or "^{-1}" in text)
    )


def _looks_like_torque_axis(axis_info: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return "torque" in text or "转矩" in text or "screw" in text


def _looks_like_frequency_axis(axis_info: dict[str, Any]) -> bool:
    # Inspect semantic axis fields only. Runtime paths and hashes are also
    # carried in axis_info; scanning them made a random directory containing
    # the substring "hz" incorrectly force an unrelated heatmap onto a log x
    # axis.
    text = " ".join(
        str(axis_info.get(key) or "")
        for key in (
            "x_label",
            "y_label",
            "x_metric",
            "y_metric",
            "semantic_family",
            "rule_id",
        )
    ).casefold()
    return (
        "frequency" in text
        or "angular" in text
        or "rad/s" in text
        or "rad s⁻¹" in text
        or "hz" in text
    )


def _looks_like_tensile_axis(axis_info: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return (
        ("strain" in text and "stress" in text) or "tensile" in text or "拉伸" in text
    )


def _finite_values(values: tuple[float, ...]) -> list[float]:
    return [float(value) for value in values if math.isfinite(value)]


def _quantile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _robust_peak_height(values: list[float]) -> float:
    if not values:
        return 1.0
    span = _quantile(values, 0.99) - _quantile(values, 0.01)
    if math.isclose(span, 0.0):
        span = max(values) - min(values)
    if math.isclose(span, 0.0):
        span = max(abs(max(values)), 1.0) * 0.15
    return max(float(span), sys.float_info.epsilon)


def _nice_ceiling(value: float) -> float:
    if not math.isfinite(value) or value <= 0.0:
        return 1.0
    exponent = math.floor(math.log10(value))
    base = 10.0**exponent
    for multiplier in (1.0, 2.0, 5.0, 10.0):
        candidate = multiplier * base
        if candidate >= value - 1e-12:
            return float(candidate)
    return float(10.0 * base)


def _mean(values: Any) -> float:
    total = 0.0
    count = 0
    for value in values:
        total += float(value)
        count += 1
    return total / count if count else 0.0
