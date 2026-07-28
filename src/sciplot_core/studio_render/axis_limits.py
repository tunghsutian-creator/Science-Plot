"""Compute numeric display bounds and major ticks for Studio axes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from sciplot_core.policy import (
    BAR_ZERO_BASELINE_NO_LOWER_PADDING,
    LINEAR_NICE_STEPS,
    LINEAR_OUTER_PADDING_FRACTION,
    LOG_DISPLAY_STEPS,
)


@dataclass(frozen=True)
class AxisTickPolicy:
    display_bounds: tuple[float, float]
    labeled_bounds: tuple[float, float]
    major_ticks: tuple[float, ...]


@dataclass(frozen=True)
class AxisLimits:
    xlim: tuple[float, float]
    ylim: tuple[float, float]
    raw_xlim: tuple[float, float] | None = None
    raw_ylim: tuple[float, float] | None = None
    x_tick_policy: AxisTickPolicy | None = None
    y_tick_policy: AxisTickPolicy | None = None


def _nice_step_at_least(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 1.0
    exponent = float(np.floor(np.log10(value)))
    base = 10**exponent
    scaled = value / base
    for step in LINEAR_NICE_STEPS:
        if scaled <= step:
            return float(step * base)
    return float(10.0 * base)


def _build_linear_ticks(
    labeled_min: float,
    labeled_max: float,
    step: float,
) -> tuple[float, ...]:
    tick_count = int(np.floor((labeled_max - labeled_min) / step)) + 1
    ticks = labeled_min + np.arange(max(tick_count, 1), dtype=float) * step
    ticks = ticks[np.isfinite(ticks)]
    if ticks.size == 0:
        ticks = np.asarray([labeled_min, labeled_max], dtype=float)
    if not np.isclose(ticks[0], labeled_min):
        ticks = np.concatenate(([labeled_min], ticks))
    if not np.isclose(ticks[-1], labeled_max):
        ticks = np.concatenate((ticks, [labeled_max]))
    return tuple(float(tick) for tick in np.unique(np.round(ticks, decimals=12)))


def _solve_linear_axis_policy(
    data_min: float,
    data_max: float,
    *,
    force_zero_min: bool = False,
    lower_padding_fraction: float = LINEAR_OUTER_PADDING_FRACTION,
    upper_padding_fraction: float = LINEAR_OUTER_PADDING_FRACTION,
) -> AxisTickPolicy:
    effective_min = float(data_min)
    effective_max = float(data_max)
    if force_zero_min and effective_min >= 0:
        effective_min = 0.0

    if np.isclose(effective_min, effective_max):
        baseline = max(abs(effective_min), abs(effective_max), 1.0)
        step = _nice_step_at_least(baseline)
        labeled_min = effective_min - step
        labeled_max = effective_max + step
        if force_zero_min and data_min >= 0:
            labeled_min = 0.0
    else:
        step = _nice_step_at_least((effective_max - effective_min) / 5.0)
        labeled_min = np.floor(effective_min / step) * step
        labeled_max = np.ceil(effective_max / step) * step
        if force_zero_min and data_min >= 0:
            labeled_min = 0.0
        if np.isclose(labeled_min, labeled_max):
            labeled_max = labeled_min + step

    labeled_span = float(labeled_max - labeled_min)
    if labeled_span <= 0:
        labeled_span = max(abs(labeled_max), 1.0)
    display_min = float(labeled_min - labeled_span * lower_padding_fraction)
    display_max = float(labeled_max + labeled_span * upper_padding_fraction)
    return AxisTickPolicy(
        display_bounds=(display_min, display_max),
        labeled_bounds=(float(labeled_min), float(labeled_max)),
        major_ticks=_build_linear_ticks(
            float(labeled_min),
            float(labeled_max),
            float(step),
        ),
    )


def _pad_log_limits(
    data_min: float,
    data_max: float,
    *,
    lower_padding: float,
    upper_padding: float,
) -> tuple[float, float]:
    if data_min <= 0 or data_max <= 0:
        raise ValueError("Log-scale limits require strictly positive values.")
    if np.isclose(data_min, data_max):
        return data_min / 10**0.08, data_max * 10**0.08
    log_min = np.log10(data_min)
    log_max = np.log10(data_max)
    span = log_max - log_min
    return (
        float(10 ** (log_min - span * max(lower_padding, 0.05))),
        float(10 ** (log_max + span * max(upper_padding, 0.08))),
    )


def _snap_log_bound(value: float, *, direction: str) -> float:
    if not np.isfinite(value) or value <= 0:
        raise ValueError("Log-scale display bounds require strictly positive values.")
    exponent = int(np.floor(np.log10(value)))
    base = 10**exponent
    scaled = value / base
    if direction == "upper":
        for step in LOG_DISPLAY_STEPS:
            if scaled <= step:
                return float(step * base)
        return float(10.0 * base)
    for step in reversed(LOG_DISPLAY_STEPS):
        if scaled >= step:
            return float(step * base)
    return float(LOG_DISPLAY_STEPS[-1] * (10 ** (exponent - 1)))


def _decade_ticks(display_min: float, display_max: float) -> tuple[float, ...]:
    low_exp = int(np.ceil(np.log10(display_min)))
    high_exp = int(np.floor(np.log10(display_max)))
    if high_exp < low_exp:
        middle = round((np.log10(display_min) + np.log10(display_max)) / 2.0)
        return (float(10**middle),)
    return tuple(float(10**exponent) for exponent in range(low_exp, high_exp + 1))


def _solve_log_axis_policy(
    data_min: float,
    data_max: float,
    *,
    lower_padding: float,
    upper_padding: float,
) -> AxisTickPolicy:
    padded_min, padded_max = _pad_log_limits(
        data_min,
        data_max,
        lower_padding=lower_padding,
        upper_padding=upper_padding,
    )
    display_min = _snap_log_bound(padded_min, direction="lower")
    display_max = _snap_log_bound(padded_max, direction="upper")
    major_ticks = _decade_ticks(data_min, data_max)
    return AxisTickPolicy(
        display_bounds=(display_min, display_max),
        labeled_bounds=(float(major_ticks[0]), float(major_ticks[-1])),
        major_ticks=major_ticks,
    )


def _finite_arrays(
    values: Sequence[Sequence[float]],
    *,
    scale: str,
    axis_name: str,
) -> list[np.ndarray]:
    arrays = [np.asarray(series, dtype=float) for series in values]
    arrays = [array[np.isfinite(array)] for array in arrays if array.size]
    if not arrays:
        raise ValueError(f"Cannot compute {axis_name}-axis values for empty data.")
    if scale == "log" and any(np.any(array <= 0) for array in arrays):
        raise ValueError(
            f"{axis_name}-axis uses log scale but contains non-positive values."
        )
    return arrays


def compute_axis_limits(
    values: Sequence[Sequence[float]],
    *,
    kind: str,
    axis_mode: str = "auto",
    legend_mode: str = "inside_best",
    x_values: Sequence[Sequence[float]] | None = None,
    xscale: str = "linear",
    yscale: str = "linear",
    x_padding: float = 0.02,
    y_padding_top: float = 0.12,
    y_padding_bottom: float = 0.06,
    headroom_factor: float | None = None,
) -> AxisLimits:
    """Compute display bounds and tick policies for standard numeric axes."""

    del legend_mode
    y_arrays = _finite_arrays(values, scale=yscale, axis_name="Y")
    y_min = min(float(array.min()) for array in y_arrays)
    y_max = max(float(array.max()) for array in y_arrays)
    effective_y_max = y_max
    if headroom_factor is not None and y_max > 0 and yscale == "linear":
        effective_y_max = max(y_max, y_max * headroom_factor)

    if yscale == "log":
        y_policy = _solve_log_axis_policy(
            y_min,
            effective_y_max,
            lower_padding=max(y_padding_bottom, LINEAR_OUTER_PADDING_FRACTION),
            upper_padding=max(y_padding_top, LINEAR_OUTER_PADDING_FRACTION),
        )
    else:
        is_zero_based_bar = (
            kind == "bar"
            and axis_mode != "manual"
            and y_min >= 0
            and BAR_ZERO_BASELINE_NO_LOWER_PADDING
        )
        if is_zero_based_bar:
            y_policy = _solve_linear_axis_policy(
                0.0,
                effective_y_max,
                force_zero_min=True,
                lower_padding_fraction=0.0,
                upper_padding_fraction=0.0,
            )
        else:
            y_policy = _solve_linear_axis_policy(
                y_min,
                effective_y_max,
                force_zero_min=axis_mode == "auto_positive" and y_min >= 0,
            )

    if x_values is None:
        return AxisLimits(
            xlim=(0.0, 1.0),
            ylim=y_policy.display_bounds,
            raw_ylim=(y_min, y_max),
            y_tick_policy=y_policy,
        )

    x_arrays = _finite_arrays(x_values, scale=xscale, axis_name="X")
    x_min = min(float(array.min()) for array in x_arrays)
    x_max = max(float(array.max()) for array in x_arrays)
    if xscale == "log":
        x_policy = _solve_log_axis_policy(
            x_min,
            x_max,
            lower_padding=max(x_padding, LINEAR_OUTER_PADDING_FRACTION),
            upper_padding=max(x_padding, LINEAR_OUTER_PADDING_FRACTION),
        )
    else:
        x_policy = _solve_linear_axis_policy(
            x_min,
            x_max,
            lower_padding_fraction=max(
                x_padding,
                LINEAR_OUTER_PADDING_FRACTION,
            ),
            upper_padding_fraction=max(
                x_padding,
                LINEAR_OUTER_PADDING_FRACTION,
            ),
        )
    return AxisLimits(
        xlim=x_policy.display_bounds,
        ylim=y_policy.display_bounds,
        raw_xlim=(x_min, x_max),
        raw_ylim=(y_min, y_max),
        x_tick_policy=x_policy,
        y_tick_policy=y_policy,
    )


__all__ = ["AxisLimits", "AxisTickPolicy", "compute_axis_limits"]
