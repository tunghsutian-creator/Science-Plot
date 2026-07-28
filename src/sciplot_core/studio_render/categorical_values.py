"""Normalize categorical labels, positions, summary values, and component columns."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any
import pandas as pd
from sciplot_core.materials_rules import (
    format_plot_text_units,
    format_unit_label,
)

from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
)


def _veusz_axis_label(value: object) -> str:
    """Translate abstract/Matplotlib labels into unambiguous Veusz text."""

    label = format_plot_text_units(str(value or "").replace("$", ""))
    superscript_map = str.maketrans(
        {
            "0": "⁰",
            "1": "¹",
            "2": "²",
            "3": "³",
            "4": "⁴",
            "5": "⁵",
            "6": "⁶",
            "7": "⁷",
            "8": "⁸",
            "9": "⁹",
            "+": "⁺",
            "-": "⁻",
            "−": "⁻",
        }
    )
    # Unit powers are ordinary Unicode typography at the renderer boundary.
    # This prevents Veusz markup scope from swallowing following punctuation,
    # as in ``Wavenumber (cm^{-1})`` where the closing parenthesis was reduced.
    label = re.sub(
        r"\^\{([+\-−]?\d+)\}",
        lambda match: match.group(1).translate(superscript_map),
        label,
    )
    # Veusz can keep an unbraced numeric subscript active for the following
    # punctuation (for example, ``\sigma_0)`` rendered ``0)`` at script size).
    # Group the common single-digit form so only the intended glyph is reduced.
    return re.sub(r"_(\d)", r"_{\1}", label)


def _category_axis_label(value: object) -> str:
    """Compact a trailing millimetre qualifier while preserving its meaning."""

    text = str(value or "").strip()
    match = re.fullmatch(r"(.+?)\s+(\([^()]+\))", text)
    if match is None or len(text) < 10:
        return text
    qualifier = match.group(2).strip("()")
    millimetre = re.fullmatch(r"(\d+(?:\.\d+)?)\s*mm", qualifier, flags=re.IGNORECASE)
    if millimetre is not None:
        return f"{match.group(1)}/{millimetre.group(1)}"
    return text


def _clean_studio_cell(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _categorical_metric_label(value: object) -> str:
    label = _clean_studio_cell(value)
    return re.sub(r"\.\d+$", "", label).strip()


def _categorical_axis_label(metric: str, unit: str) -> str:
    if not metric:
        metric = "Value"
    normalized_unit = format_unit_label(unit.strip())
    if normalized_unit.casefold() in {"", "1", "a.u.", "au"}:
        return metric
    return f"{metric} ({normalized_unit})"


def _deterministic_category_positions(
    center: float,
    count: int,
    *,
    fraction: float,
    seed_key: str = "",
) -> tuple[float, ...]:
    if count <= 1:
        return (center,)
    bounded = min(max(float(fraction), 0.0), 0.35)
    even_offsets = [-1.0 + 2.0 * index / float(count - 1) for index in range(count)]
    stable_key = f"{seed_key}|{center:.12g}|{count}"
    row_indices = sorted(
        range(count),
        key=lambda index: hashlib.sha256(
            f"{stable_key}|{index}".encode("utf-8")
        ).digest(),
    )
    assigned_offsets = [0.0] * count
    for offset, row_index in zip(even_offsets, row_indices, strict=True):
        assigned_offsets[row_index] = offset
    return tuple(center + bounded * offset for offset in assigned_offsets)


def _mean_and_sample_sd(values: tuple[float, ...] | list[float]) -> tuple[float, float]:
    """Return arithmetic mean and the categorical bar contract's sample SD."""

    mean = math.fsum(float(value) for value in values) / len(values)
    error = (
        math.sqrt(
            math.fsum((float(value) - mean) ** 2 for value in values)
            / (len(values) - 1)
        )
        if len(values) >= 2
        else 0.0
    )
    return mean, error


def _categorical_component_column(
    frame: pd.DataFrame,
    *,
    aliases: set[str],
) -> Any | None:
    matches = [
        column
        for column in frame.columns
        if re.sub(r"[^a-z0-9]+", "", str(column).strip().casefold()) in aliases
    ]
    if len(matches) > 1:
        raise StudioPreparationBlocked(
            "ambiguous_categorical_component_columns",
            "Stacked-component bar input repeats a required categorical column: "
            + ", ".join(str(value) for value in matches),
        )
    return matches[0] if matches else None
