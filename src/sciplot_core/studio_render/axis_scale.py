"""Resolve axis scale and trim empty terminal logarithmic decades."""

from __future__ import annotations

from typing import Any
from sciplot_core.policy import (
    AUTO_LOG_BOUND_PADDING_FACTOR,
    MAX_AUTO_LOG_EMPTY_RANGE_FACTOR,
)


def _axis_scale(render_options: dict[str, Any], axis: str) -> str:
    value = render_options.get(f"{axis}scale")
    if isinstance(value, str) and value.strip().casefold() == "log":
        return "log"
    return "linear"


def _trim_empty_terminal_log_decades(
    ticks: tuple[float, ...],
    *,
    data_max: float,
) -> tuple[tuple[float, ...], float | None]:
    """Drop an empty terminal decade while retaining useful major ticks."""

    trimmed = tuple(ticks)
    changed = False
    while len(trimmed) > 2 and trimmed[-1] > data_max * MAX_AUTO_LOG_EMPTY_RANGE_FACTOR:
        trimmed = trimmed[:-1]
        changed = True
    return (
        trimmed,
        data_max * AUTO_LOG_BOUND_PADDING_FACTOR if changed else None,
    )
