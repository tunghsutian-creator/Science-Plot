"""Shared value projections for scientific-transform contracts."""

from __future__ import annotations

import math
from typing import Any


def transform_exclusion_counts(diagnostics: dict[str, Any]) -> dict[str, int]:
    return {
        "empty_pair": int(diagnostics.get("excluded_empty_pair_count") or 0),
        "partial_or_nonnumeric": int(
            diagnostics.get("excluded_partial_or_nonnumeric_pair_count") or 0
        ),
        "nonfinite": int(diagnostics.get("excluded_nonfinite_pair_count") or 0),
    }


def transform_axis_compatibility(
    values: list[float],
    *,
    scale: str,
    require_values: bool = False,
) -> dict[str, Any]:
    finite = (bool(values) or not require_values) and all(
        math.isfinite(value) for value in values
    )
    nonpositive = sum(value <= 0.0 for value in values if math.isfinite(value))
    return {
        "registered_scale": scale,
        "finite_compatible": finite,
        "log_compatible": finite and nonpositive == 0,
        "nonpositive_count": nonpositive,
    }


__all__ = ["transform_axis_compatibility", "transform_exclusion_counts"]
