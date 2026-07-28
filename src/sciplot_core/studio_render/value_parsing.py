"""Parse rendering sizes, numeric tuples, string lists, and logarithmic minor ticks."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    DEFAULT_LOG_MINOR_MULTIPLIERS,
)


def _size_mm(value: str) -> tuple[int, int]:
    try:
        left, right = value.lower().split("x", maxsplit=1)
        return max(1, int(float(left))), max(1, int(float(right)))
    except Exception:
        return 60, 55


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(entry) for entry in value) if item]


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_tuple(value: Any) -> tuple[float, ...]:
    if not isinstance(value, list | tuple):
        return ()
    parsed = [_optional_float(item) for item in value]
    return tuple(item for item in parsed if item is not None and math.isfinite(item))


def _log_minor_ticks(
    minimum: float | None,
    maximum: float | None,
    *,
    scale: str,
    major_ticks: tuple[float, ...] = (),
) -> list[float]:
    if scale != "log" or minimum is None or maximum is None:
        return []
    low, high = sorted((float(minimum), float(maximum)))
    if not math.isfinite(low) or not math.isfinite(high) or low <= 0 or high <= low:
        return []
    visible_major_ticks = sorted(
        float(value)
        for value in major_ticks
        if math.isfinite(value) and low <= float(value) <= high
    )
    if len(visible_major_ticks) >= 2:
        low, high = visible_major_ticks[0], visible_major_ticks[-1]
    elif len(visible_major_ticks) == 1:
        return []
    start_exponent = math.floor(math.log10(low)) - 1
    end_exponent = math.ceil(math.log10(high)) + 1
    ticks: list[float] = []
    for exponent in range(start_exponent, end_exponent + 1):
        decade = 10.0**exponent
        for multiplier in DEFAULT_LOG_MINOR_MULTIPLIERS:
            value = multiplier * decade
            if low < value < high:
                ticks.append(value)
    return ticks
