from __future__ import annotations

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import transforms
from matplotlib.ticker import FixedFormatter, FixedLocator, NullLocator
from src.data_loader import ReplicateGroup
from src.plot_contract import load_plot_contract
from src.text_normalization import _clean_text, canonicalize_token, normalize_label, normalize_unit

from src import mpl_backend, plot_style  # noqa: F401

LegendMode = str

AxisMode = str

MAX_VISIBLE_Y_MAJOR_TICKS = 7
_SPARSE_MAJOR_TICK_TARGET = 5
_DENSE_MAJOR_TICK_TARGET = 11
_MIN_DENSE_LOG_MAJOR_TICKS = 3
_DENSE_LOG_MANTISSAS = (1.0, 2.0, 5.0)
_DENSE_LOG_FINE_MANTISSAS = (1.0, 1.1, 1.2, 1.3, 1.5, 1.7, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5)

_PLOT_CONTRACT = load_plot_contract()

_HEATMAP_LAYOUT = _PLOT_CONTRACT.special_layouts["heatmap"]

_AXIS_POLICY = _PLOT_CONTRACT.axis_policy

_LINEAR_NICE_STEPS = tuple(float(value) for value in _AXIS_POLICY.linear_nice_steps)

_LOG_DISPLAY_STEPS = tuple(float(value) for value in _AXIS_POLICY.log_display_steps)

_LINEAR_OUTER_PADDING_FRACTION = float(_AXIS_POLICY.linear_outer_padding_fraction)

_FORCE_VISIBLE_LABELED_ENDPOINTS = bool(_AXIS_POLICY.linear_force_visible_labeled_endpoints)

_BAR_ZERO_BASELINE_NO_LOWER_PADDING = bool(_AXIS_POLICY.bar_zero_baseline_no_lower_padding)

_TENSILE_Y_INCLUDE_ZERO = bool(_AXIS_POLICY.tensile_y_include_zero)

_STACKED_X_USE_STANDARD_ENDPOINT_POLICY = bool(_AXIS_POLICY.stacked_x_use_standard_endpoint_policy)

@dataclass
class AxisLimits:
    xlim: tuple[float, float]
    ylim: tuple[float, float]
    raw_xlim: tuple[float, float] | None = None
    raw_ylim: tuple[float, float] | None = None
    x_tick_policy: AxisTickPolicy | None = None
    y_tick_policy: AxisTickPolicy | None = None

@dataclass(frozen=True)
class AxisTickPolicy:
    display_bounds: tuple[float, float]
    labeled_bounds: tuple[float, float]
    major_ticks: tuple[float, ...]

@dataclass(frozen=True)
class SharedAxisLayout:
    display_bounds: tuple[float, float]
    labeled_bounds: tuple[float, float]
    raw_bounds: tuple[float, float]
    visible_ticks: tuple[float, ...]

def compute_group_positions(
    num_groups: int,
    item_width: float,
    spacing_scale: float = 1.0,
) -> np.ndarray:
    """Compute symmetric group centers with density-aware spacing."""
    if num_groups <= 0:
        raise ValueError("num_groups must be positive.")
    if item_width <= 0:
        raise ValueError("item_width must be positive.")
    if spacing_scale <= 0:
        raise ValueError("spacing_scale must be positive.")

    extra_gap = 0.72 - min(num_groups, 8) * 0.055
    if num_groups <= 4:
        extra_gap += 0.08
    extra_gap = max(0.18, extra_gap)

    center_step = item_width + extra_gap * spacing_scale
    offsets = np.arange(num_groups, dtype=float) - (num_groups - 1) / 2
    return offsets * center_step

def _resolved_panel_geometry(
    *,
    width_mm: float | None,
    height_mm: float | None,
    left_margin_mm: float | None,
    right_margin_mm: float | None,
    bottom_margin_mm: float | None,
    top_margin_mm: float | None,
) -> tuple[float, float, float | None, float | None, float | None, float | None]:
    spacing = plot_style.current_spacing()
    return (
        spacing.panel_width_mm if width_mm is None else width_mm,
        spacing.panel_height_mm if height_mm is None else height_mm,
        spacing.left_margin_mm if left_margin_mm is None else left_margin_mm,
        spacing.right_margin_mm if right_margin_mm is None else right_margin_mm,
        spacing.bottom_margin_mm if bottom_margin_mm is None else bottom_margin_mm,
        spacing.top_margin_mm if top_margin_mm is None else top_margin_mm,
    )

def _format_axis_label(
    label: str,
    unit: str,
    *,
    preserve_stress_label: bool = False,
    override_label: str | None = None,
) -> str:
    display_label = _clean_text(override_label) if override_label else normalize_label(label)
    if preserve_stress_label and canonicalize_token(display_label) in {"σ", "sigma"}:
        display_label = "Stress"
    display_unit = normalize_unit(unit)
    return f"{display_label} ({display_unit})" if display_unit else display_label

def _merge_limits(
    computed: tuple[float, float],
    override: tuple[float | None, float | None] | None,
) -> tuple[float, float]:
    if override is None:
        return computed
    low = computed[0] if override[0] is None else override[0]
    high = computed[1] if override[1] is None else override[1]
    return float(low), float(high)

def _nice_step_ge(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 1.0
    exponent = float(np.floor(np.log10(value)))
    base = 10 ** exponent
    scaled = value / base
    for step in _LINEAR_NICE_STEPS:
        if scaled <= step:
            return float(step * base)
    return float(10.0 * base)

def _linear_target_major_step(span: float) -> float:
    baseline = span if span > 0 else 1.0
    return _nice_step_ge(baseline / 5.0)

def _build_linear_ticks(labeled_min: float, labeled_max: float, step: float) -> tuple[float, ...]:
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
    lower_display_padding_fraction: float | None = _LINEAR_OUTER_PADDING_FRACTION,
    upper_display_padding_fraction: float | None = _LINEAR_OUTER_PADDING_FRACTION,
) -> AxisTickPolicy:
    effective_min = float(data_min)
    effective_max = float(data_max)
    if force_zero_min and effective_min >= 0:
        effective_min = 0.0

    if np.isclose(effective_min, effective_max):
        baseline = max(abs(effective_min), abs(effective_max), 1.0)
        step = _nice_step_ge(baseline)
        labeled_min = effective_min - step
        labeled_max = effective_max + step
        if force_zero_min and data_min >= 0:
            labeled_min = 0.0
    else:
        step = _linear_target_major_step(effective_max - effective_min)
        labeled_min = np.floor(effective_min / step) * step
        labeled_max = np.ceil(effective_max / step) * step
        if force_zero_min and data_min >= 0:
            labeled_min = 0.0
        if np.isclose(labeled_min, labeled_max):
            labeled_max = labeled_min + step

    labeled_span = float(labeled_max - labeled_min)
    if labeled_span <= 0:
        labeled_span = max(abs(labeled_max), 1.0)
    lower_padding = labeled_span * float(lower_display_padding_fraction or 0.0)
    upper_padding = labeled_span * float(upper_display_padding_fraction or 0.0)
    display_min = float(labeled_min - lower_padding)
    display_max = float(labeled_max + upper_padding)
    return AxisTickPolicy(
        display_bounds=(display_min, display_max),
        labeled_bounds=(float(labeled_min), float(labeled_max)),
        major_ticks=_build_linear_ticks(float(labeled_min), float(labeled_max), float(step)),
    )

def _decimal_complexity(value: float) -> int:
    if not np.isfinite(value):
        return 12
    for decimals in range(0, 7):
        if np.isclose(value, round(value, decimals), rtol=0.0, atol=1e-9):
            return decimals
    return 12

def _nice_step_near(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 1.0
    exponent = float(np.floor(np.log10(value)))
    base = 10**exponent
    mantissas = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10.0)
    candidates = [mantissa * base for mantissa in mantissas]
    candidates.extend(mantissa * base * 10.0 for mantissa in mantissas)
    candidates.extend(mantissa * base / 10.0 for mantissa in mantissas)
    return float(min(candidates, key=lambda candidate: abs(np.log(candidate / value))))

def _ticks_for_step(display_min: float, display_max: float, step: float) -> tuple[float, ...]:
    start = np.ceil(display_min / step) * step
    stop = np.floor(display_max / step) * step
    if stop < start:
        return ()
    count = int(np.floor((stop - start) / step)) + 1
    ticks = start + np.arange(max(count, 1), dtype=float) * step
    return tuple(float(np.round(value, decimals=12)) for value in ticks if display_min <= value <= display_max)

def _balanced_linear_ticks(
    data_min: float,
    data_max: float,
    *,
    display_min: float,
    display_max: float,
) -> tuple[float, ...]:
    display_span = float(display_max - display_min)
    candidates: list[tuple[float, tuple[float, ...]]] = []
    for tick_count in (4, 5, 6):
        target_step = display_span / max(tick_count - 1, 1)
        step = _nice_step_near(target_step)
        ticks = _ticks_for_step(display_min, display_max, step)
        if not ticks:
            continue
        visible_count = len(ticks)
        label_complexity = max(_decimal_complexity(value) for value in (*ticks, step))
        tick_count_penalty = 0.0 if 4 <= visible_count <= 6 else abs(visible_count - 5) * 20.0
        preferred_count_penalty = abs(visible_count - 5)
        step_penalty = abs(float(np.log(step / target_step))) if target_step > 0 else 0.0
        score = label_complexity * 10.0 + tick_count_penalty + preferred_count_penalty + step_penalty
        candidates.append((score, ticks))
    if candidates:
        return min(candidates, key=lambda item: item[0])[1]
    return (float(data_min), float(data_max))

def _balanced_linear_display_bounds(
    data_min: float,
    data_max: float,
    *,
    lower_display_padding_fraction: float | None,
    upper_display_padding_fraction: float | None,
) -> tuple[float, float]:
    span = float(data_max - data_min)
    lower_padding = span * float(lower_display_padding_fraction or 0.0)
    upper_padding = span * float(upper_display_padding_fraction or 0.0)
    if data_min > 0:
        zero_anchor_limit = max(span * 0.1, 50.0)
        if data_min <= zero_anchor_limit:
            return 0.0, float(data_max + data_min)
    return float(data_min - lower_padding), float(data_max + upper_padding)

def _solve_linear_balanced_axis_policy(
    data_min: float,
    data_max: float,
    *,
    lower_display_padding_fraction: float | None = _LINEAR_OUTER_PADDING_FRACTION,
    upper_display_padding_fraction: float | None = _LINEAR_OUTER_PADDING_FRACTION,
) -> AxisTickPolicy:
    effective_min = float(data_min)
    effective_max = float(data_max)
    if effective_max < effective_min:
        effective_min, effective_max = effective_max, effective_min
    if np.isclose(effective_min, effective_max):
        return _solve_linear_axis_policy(
            effective_min,
            effective_max,
            lower_display_padding_fraction=lower_display_padding_fraction,
            upper_display_padding_fraction=upper_display_padding_fraction,
        )
    display_bounds = _balanced_linear_display_bounds(
        effective_min,
        effective_max,
        lower_display_padding_fraction=lower_display_padding_fraction,
        upper_display_padding_fraction=upper_display_padding_fraction,
    )
    ticks = _balanced_linear_ticks(
        effective_min,
        effective_max,
        display_min=display_bounds[0],
        display_max=display_bounds[1],
    )
    return AxisTickPolicy(
        display_bounds=display_bounds,
        labeled_bounds=(float(ticks[0]), float(ticks[-1])),
        major_ticks=ticks,
    )

def _snap_log_display_bound(value: float, *, direction: str) -> float:
    if not np.isfinite(value) or value <= 0:
        raise ValueError("Log-scale display bounds require strictly positive values.")
    exponent = int(np.floor(np.log10(value)))
    base = 10**exponent
    scaled = value / base

    if direction == "upper":
        for step in _LOG_DISPLAY_STEPS:
            if scaled <= step:
                return float(step * base)
        return float(10.0 * base)

    for step in reversed(_LOG_DISPLAY_STEPS):
        if scaled >= step:
            return float(step * base)
    return float(_LOG_DISPLAY_STEPS[-1] * (10 ** (exponent - 1)))

def _build_decade_ticks(display_min: float, display_max: float) -> tuple[float, ...]:
    low_exp = int(np.ceil(np.log10(display_min)))
    high_exp = int(np.floor(np.log10(display_max)))
    if high_exp < low_exp:
        candidate = 10 ** round((np.log10(display_min) + np.log10(display_max)) / 2.0)
        return (float(candidate),)
    ticks = tuple(float(10**exponent) for exponent in range(low_exp, high_exp + 1))
    return ticks

def _solve_log_axis_policy(
    data_min: float,
    data_max: float,
    *,
    lower_padding: float,
    upper_padding: float,
) -> AxisTickPolicy:
    padded_min, padded_max = _pad_limits_log_curve(
        data_min,
        data_max,
        lower_padding=lower_padding,
        upper_padding=upper_padding,
    )
    display_min = _snap_log_display_bound(padded_min, direction="lower")
    display_max = _snap_log_display_bound(padded_max, direction="upper")
    major_ticks = _build_decade_ticks(data_min, data_max)
    return AxisTickPolicy(
        display_bounds=(display_min, display_max),
        labeled_bounds=(float(major_ticks[0]), float(major_ticks[-1])),
        major_ticks=major_ticks,
    )

def _pad_limits_linear(
    data_min: float,
    data_max: float,
    *,
    lower_padding: float,
    upper_padding: float,
    axis_mode: AxisMode,
    allow_below_zero: bool,
) -> tuple[float, float]:
    if np.isclose(data_min, data_max):
        baseline = abs(data_max) if data_max != 0 else 1.0
        pad = baseline * 0.08
        low, high = data_min - pad, data_max + pad
    else:
        span = data_max - data_min
        low = data_min - span * lower_padding
        high = data_max + span * upper_padding

    if axis_mode == "auto_positive" and data_min >= 0:
        low = 0.0
    elif not allow_below_zero and data_min >= 0:
        low = max(0.0, low)

    if np.isclose(low, high):
        high = low + 1.0
    return low, high

def _nice_linear_padding(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 1.0
    exponent = float(np.floor(np.log10(value)))
    base = 10 ** exponent
    scaled = value / base
    if scaled <= 1:
        nice = 1
    elif scaled <= 2:
        nice = 2
    elif scaled <= 5:
        nice = 5
    else:
        nice = 10
    return float(nice * base)

def _pad_limits_linear_curve(
    data_min: float,
    data_max: float,
    *,
    padding_fraction: float = 0.05,
) -> tuple[float, float]:
    span = data_max - data_min
    baseline = span if span > 0 else max(abs(data_min), abs(data_max), 1.0)
    padding = _nice_linear_padding(baseline * padding_fraction)
    low = data_min - padding
    high = data_max + padding
    if np.isclose(low, high):
        high = low + padding * 2
    return low, high

def _pad_limits_log(
    data_min: float,
    data_max: float,
    *,
    lower_padding: float,
    upper_padding: float,
) -> tuple[float, float]:
    if data_min <= 0 or data_max <= 0:
        raise ValueError("Log-scale limits require strictly positive values.")

    if np.isclose(data_min, data_max):
        low = data_min / 10**0.08
        high = data_max * 10**0.08
        return low, high

    log_min = np.log10(data_min)
    log_max = np.log10(data_max)
    span = log_max - log_min
    low = 10 ** (log_min - span * lower_padding)
    high = 10 ** (log_max + span * upper_padding)
    return low, high

def _pad_limits_log_curve(
    data_min: float,
    data_max: float,
    *,
    lower_padding: float,
    upper_padding: float,
) -> tuple[float, float]:
    return _pad_limits_log(
        data_min,
        data_max,
        lower_padding=max(lower_padding, 0.05),
        upper_padding=max(upper_padding, 0.08),
    )

def _validate_scale_values(
    values: Sequence[np.ndarray] | Sequence[Sequence[float]],
    *,
    scale: str,
    axis_name: str,
) -> list[np.ndarray]:
    arrays = [np.asarray(series, dtype=float) for series in values]
    arrays = [arr[np.isfinite(arr)] for arr in arrays if np.asarray(arr).size]
    if not arrays:
        raise ValueError(f"Cannot compute {axis_name}-axis values for empty data.")

    if scale == "log":
        bad = [arr for arr in arrays if np.any(arr <= 0)]
        if bad:
            raise ValueError(f"{axis_name}-axis uses log scale but contains non-positive values.")
    return arrays

def compute_axis_limits(
    values: Sequence[np.ndarray] | Sequence[Sequence[float]],
    *,
    kind: str,
    axis_mode: AxisMode = "auto",
    legend_mode: LegendMode = "inside_best",
    x_values: Sequence[np.ndarray] | Sequence[Sequence[float]] | None = None,
    xscale: str = "linear",
    yscale: str = "linear",
    x_padding: float = 0.02,
    y_padding_top: float = 0.12,
    y_padding_bottom: float = 0.06,
    headroom_factor: float | None = None,
) -> AxisLimits:
    """Compute display bounds and tick policies for standard numeric axes."""
    y_arrays = _validate_scale_values(values, scale=yscale, axis_name="Y")

    y_min = min(float(arr.min()) for arr in y_arrays)
    y_max = max(float(arr.max()) for arr in y_arrays)
    effective_y_max = y_max
    if headroom_factor is not None and y_max > 0 and yscale == "linear":
        effective_y_max = max(y_max, y_max * headroom_factor)

    if yscale == "log":
        y_policy = _solve_log_axis_policy(
            y_min,
            effective_y_max,
            lower_padding=max(y_padding_bottom, _LINEAR_OUTER_PADDING_FRACTION),
            upper_padding=max(y_padding_top, _LINEAR_OUTER_PADDING_FRACTION),
        )
    else:
        is_bar = kind == "bar" and axis_mode != "manual" and y_min >= 0 and _BAR_ZERO_BASELINE_NO_LOWER_PADDING
        force_zero_min = axis_mode == "auto_positive" and y_min >= 0
        if is_bar:
            y_policy = _solve_linear_axis_policy(
                0.0,
                effective_y_max,
                force_zero_min=True,
                lower_display_padding_fraction=0.0,
                upper_display_padding_fraction=0.0,
            )
        else:
            y_policy = _solve_linear_axis_policy(
                y_min,
                effective_y_max,
                force_zero_min=force_zero_min,
                lower_display_padding_fraction=_LINEAR_OUTER_PADDING_FRACTION,
                upper_display_padding_fraction=_LINEAR_OUTER_PADDING_FRACTION,
            )

    if x_values is None:
        return AxisLimits(
            xlim=(0.0, 1.0),
            ylim=y_policy.display_bounds,
            raw_ylim=(y_min, y_max),
            y_tick_policy=y_policy,
        )

    x_arrays = _validate_scale_values(x_values, scale=xscale, axis_name="X")

    x_min = min(float(arr.min()) for arr in x_arrays)
    x_max = max(float(arr.max()) for arr in x_arrays)
    if xscale == "log":
        x_policy = _solve_log_axis_policy(
            x_min,
            x_max,
            lower_padding=max(x_padding, _LINEAR_OUTER_PADDING_FRACTION),
            upper_padding=max(x_padding, _LINEAR_OUTER_PADDING_FRACTION),
        )
    else:
        x_policy = _solve_linear_axis_policy(
            x_min,
            x_max,
            lower_display_padding_fraction=max(x_padding, _LINEAR_OUTER_PADDING_FRACTION),
            upper_display_padding_fraction=max(x_padding, _LINEAR_OUTER_PADDING_FRACTION),
        )
    return AxisLimits(
        xlim=x_policy.display_bounds,
        ylim=y_policy.display_bounds,
        raw_xlim=(x_min, x_max),
        raw_ylim=(y_min, y_max),
        x_tick_policy=x_policy,
        y_tick_policy=y_policy,
    )

def _wrap_tick_label(text: str, width: int = 10) -> str:
    cleaned = str(text).strip()
    if not cleaned:
        return cleaned
    return "\n".join(textwrap.wrap(cleaned, width=width, break_long_words=False, break_on_hyphens=False))

def _style_categorical_ticklabels(ax: plt.Axes, labels: Sequence[str]) -> None:
    wrapped = [_wrap_tick_label(label) for label in labels]
    ax.set_xticklabels(wrapped)

    max_line = max(
        (max((len(line) for line in label.split("\n")), default=0) for label in wrapped),
        default=0,
    )
    has_unbreakable = any(" " not in label and len(label) > 12 for label in labels)
    fontsize = plot_style.current_typography().font_size_pt
    rotation = 0
    ha = "center"

    if has_unbreakable or max_line > 10:
        fontsize = 6
    if max_line > 14 or any(" " not in label and len(label) > 16 for label in labels):
        rotation = 15
        ha = "right"

    for tick in ax.get_xticklabels():
        tick.set_fontsize(fontsize)
        tick.set_rotation(rotation)
        tick.set_rotation_mode("anchor")
        tick.set_ha(ha)
        tick.set_va("top")

def _override_complete(bounds: tuple[float | None, float | None] | None) -> bool:
    return bool(bounds is not None and bounds[0] is not None and bounds[1] is not None)

def _filter_ticks_to_raw_bounds(
    ticks: np.ndarray,
    raw_bounds: tuple[float, float],
    *,
    scale: str,
) -> np.ndarray:
    ticks = np.asarray(ticks, dtype=float)
    ticks = ticks[np.isfinite(ticks)]
    if ticks.size == 0:
        return ticks

    low, high = raw_bounds
    if scale == "log":
        mask = (ticks >= low * (1 - 1e-9)) & (ticks <= high * (1 + 1e-9))
    else:
        tol = max(abs(low), abs(high), abs(high - low), 1.0) * 1e-9
        mask = (ticks >= low - tol) & (ticks <= high + tol)
    filtered = ticks[mask]
    if filtered.size == 0:
        return filtered
    return np.unique(filtered)

def _cap_visible_major_ticks(
    ticks: np.ndarray,
    *,
    scale: str,
    max_major_ticks: int = 7,
) -> np.ndarray:
    ticks = np.asarray(ticks, dtype=float)
    ticks = ticks[np.isfinite(ticks)]
    if ticks.size <= max_major_ticks:
        return ticks
    if ticks.size <= 2:
        return ticks
    first = ticks[0]
    last = ticks[-1]
    middle = ticks[1:-1]
    keep_middle = max(max_major_ticks - 2, 0)
    if keep_middle <= 0:
        return np.asarray([first, last], dtype=float)
    step = max(int(np.ceil(middle.size / keep_middle)), 1)
    trimmed = middle[::step][:keep_middle]
    return np.concatenate(([first], trimmed, [last]))

def _validate_group_input(groups: Sequence[ReplicateGroup], *, chart_name: str) -> None:
    if not groups:
        raise ValueError(f"No replicate groups were provided for {chart_name}.")
    for index, group in enumerate(groups, start=1):
        if group.data.empty:
            raise ValueError(f"{chart_name} group {index} ({group.group!r}) does not contain any replicate values.")

def _set_axis_locator_from_filtered_ticks(axis, ticks: np.ndarray, *, which: str) -> None:
    if ticks.size == 0:
        return
    locator = FixedLocator(ticks.tolist())
    if which == "major":
        axis.set_major_locator(locator)
    else:
        axis.set_minor_locator(locator)

def _apply_explicit_major_ticks(axis, ticks: Sequence[float], *, max_major_ticks: int | None = None) -> None:
    values = np.asarray(ticks, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return
    if max_major_ticks is not None:
        values = _cap_visible_major_ticks(values, scale="linear", max_major_ticks=max_major_ticks)
    axis.set_major_locator(FixedLocator(values.tolist()))


def _axis_view_bounds(axis) -> tuple[float, float] | None:
    bounds = np.asarray(axis.get_view_interval(), dtype=float)
    bounds = bounds[np.isfinite(bounds)]
    if bounds.size != 2:
        return None
    low, high = sorted(float(value) for value in bounds)
    return low, high


def _major_tick_step(values: Sequence[float] | np.ndarray) -> float | None:
    ticks = _normalized_tick_values(values)
    if ticks.size < 2:
        return None
    deltas = np.diff(ticks)
    deltas = deltas[np.isfinite(deltas) & (deltas > 1e-9)]
    if deltas.size == 0:
        return None
    return float(np.min(deltas))


def _recompute_linear_major_ticks_for_view_bounds(
    *,
    view_bounds: tuple[float, float] | None,
    policy_ticks: Sequence[float] | None,
    max_major_ticks: int | None = None,
) -> np.ndarray:
    if view_bounds is None:
        return _normalized_tick_values(policy_ticks or ())

    low, high = view_bounds
    if not np.isfinite(low) or not np.isfinite(high):
        return _normalized_tick_values(policy_ticks or ())
    if np.isclose(low, high):
        return np.asarray([float(low)], dtype=float)

    target_count = max(2, max_major_ticks or MAX_VISIBLE_Y_MAJOR_TICKS)
    target_step = _nice_step_ge((high - low) / max(target_count - 1, 1))
    policy_step = _major_tick_step(policy_ticks or ())
    step = max(policy_step or 0.0, target_step)
    tolerance = max(abs(step) * 1e-9, 1e-9)

    start = np.ceil((low - tolerance) / step) * step
    stop = np.floor((high + tolerance) / step) * step
    if start > stop + tolerance:
        midpoint = low + ((high - low) / 2.0)
        snapped_midpoint = round(midpoint / step) * step
        if low - tolerance <= snapped_midpoint <= high + tolerance:
            return np.asarray([float(snapped_midpoint)], dtype=float)
        return np.asarray([float(midpoint)], dtype=float)

    tick_count = int(np.floor(((stop - start) / step) + tolerance)) + 1
    ticks = start + np.arange(max(tick_count, 1), dtype=float) * step
    ticks = ticks[(ticks >= low - tolerance) & (ticks <= high + tolerance)]
    ticks = _normalized_tick_values(ticks)
    if max_major_ticks is not None and ticks.size > max_major_ticks:
        ticks = _cap_visible_major_ticks(ticks, scale="linear", max_major_ticks=max_major_ticks)
    return ticks


def _is_log_decade(value: float) -> bool:
    if not np.isfinite(value) or value <= 0:
        return False
    exponent = round(float(np.log10(value)))
    return bool(np.isclose(value, 10.0 ** exponent, rtol=1e-9, atol=0.0))


def _cap_log_major_ticks_preserving_edges(
    ticks: np.ndarray,
    *,
    max_major_ticks: int,
) -> np.ndarray:
    values = _normalized_tick_values(ticks)
    if values.size <= max_major_ticks or max_major_ticks < 2:
        return values
    indices = np.rint(np.linspace(0, values.size - 1, max_major_ticks)).astype(int)
    return values[np.unique(indices)]


def _recompute_log_major_ticks_for_view_bounds(
    *,
    view_bounds: tuple[float, float] | None,
    policy_ticks: Sequence[float] | None,
    max_major_ticks: int | None = None,
) -> np.ndarray:
    if view_bounds is None:
        return _normalized_tick_values(policy_ticks or ())

    low, high = view_bounds
    if not np.isfinite(low) or not np.isfinite(high) or low <= 0 or high <= 0:
        return _normalized_tick_values(policy_ticks or ())
    if np.isclose(low, high):
        return np.asarray([float(low)], dtype=float)

    low_log = float(np.log10(low))
    high_log = float(np.log10(high))
    start_exp = int(np.ceil(low_log - 1e-9))
    stop_exp = int(np.floor(high_log + 1e-9))
    ticks = [10.0 ** exponent for exponent in range(start_exp, stop_exp + 1)]
    if _is_log_decade(low):
        ticks.append(float(low))
    if _is_log_decade(high):
        ticks.append(float(high))
    values = _normalized_tick_values(ticks)
    values = values[(values >= low * (1 - 1e-9)) & (values <= high * (1 + 1e-9))]
    if values.size == 0:
        return _normalized_tick_values(policy_ticks or ())
    if max_major_ticks is not None and values.size > max_major_ticks:
        values = _cap_log_major_ticks_preserving_edges(values, max_major_ticks=max_major_ticks)
    return values


def _resolved_major_ticks_with_override(
    *,
    axis,
    policy_ticks: Sequence[float] | None,
    override: tuple[float | None, float | None] | None,
    scale: str,
    max_major_ticks: int | None = None,
) -> np.ndarray:
    if scale == "linear" and override is not None:
        return _recompute_linear_major_ticks_for_view_bounds(
            view_bounds=_axis_view_bounds(axis),
            policy_ticks=policy_ticks,
            max_major_ticks=max_major_ticks,
        )
    if scale == "log" and override is not None:
        return _recompute_log_major_ticks_for_view_bounds(
            view_bounds=_axis_view_bounds(axis),
            policy_ticks=policy_ticks,
            max_major_ticks=max_major_ticks,
        )

    values = (
        np.asarray(policy_ticks, dtype=float)
        if policy_ticks is not None
        else np.array([], dtype=float)
    )
    values = values[np.isfinite(values)]

    if values.size == 0:
        return values
    values = np.unique(np.round(values, decimals=12))
    if max_major_ticks is not None:
        values = _cap_visible_major_ticks(values, scale=scale, max_major_ticks=max_major_ticks)
    return values

def _apply_major_ticks_with_override(
    axis,
    *,
    policy_ticks: Sequence[float] | None,
    override: tuple[float | None, float | None] | None,
    scale: str,
    max_major_ticks: int | None = None,
) -> None:
    values = _resolved_major_ticks_with_override(
        axis=axis,
        policy_ticks=policy_ticks,
        override=override,
        scale=scale,
        max_major_ticks=max_major_ticks,
    )
    if values.size == 0:
        return
    axis.set_major_locator(FixedLocator(values.tolist()))


def _normalized_tick_density(value: str | None) -> str:
    cleaned = str(value or "auto").strip().lower()
    if cleaned not in {"auto", "sparse", "dense"}:
        raise ValueError(f"Unsupported tick density: {value!r}")
    return cleaned


def _normalized_tick_edge_labels(value: str | None) -> str:
    cleaned = str(value or "auto").strip().lower()
    if cleaned not in {"auto", "hide_min", "hide_max", "hide_both"}:
        raise ValueError(f"Unsupported tick edge label mode: {value!r}")
    return cleaned


def _normalized_tick_values(ticks: Sequence[float] | np.ndarray) -> np.ndarray:
    values = np.asarray(ticks, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return values
    return np.unique(np.round(values, decimals=12))


def _sparsify_major_ticks(
    ticks: np.ndarray,
    *,
    target_count: int,
) -> np.ndarray:
    values = _normalized_tick_values(ticks)
    if values.size <= target_count:
        return values

    anchor_indices: set[int] = {0, values.size - 1}
    zero_indices = np.flatnonzero(np.isclose(values, 0.0, atol=1e-9))
    if zero_indices.size:
        anchor_indices.add(int(zero_indices[0]))

    keep_indices = set(anchor_indices)
    while len(keep_indices) < target_count and len(keep_indices) < values.size:
        best_index: int | None = None
        best_distance = -1
        for index in range(values.size):
            if index in keep_indices:
                continue
            distance = min(abs(index - kept) for kept in keep_indices)
            if distance > best_distance:
                best_distance = distance
                best_index = index
        if best_index is None:
            break
        keep_indices.add(best_index)
    return values[sorted(keep_indices)]


def _densify_linear_major_ticks(
    ticks: np.ndarray,
    *,
    target_count: int,
) -> np.ndarray:
    values = _normalized_tick_values(ticks)
    if values.size < 2 or values.size >= target_count:
        return values

    dense_values = values.tolist()
    candidate_midpoints = sorted(
        (
            (abs(float(high - low)), float((low + high) / 2.0))
            for low, high in zip(values[:-1], values[1:], strict=True)
            if not np.isclose(low, high)
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    for _, midpoint in candidate_midpoints:
        if len(dense_values) >= target_count:
            break
        if any(np.isclose(existing, midpoint, atol=1e-9) for existing in dense_values):
            continue
        dense_values.append(midpoint)
    return _normalized_tick_values(dense_values)


def _densify_log_major_ticks(
    ticks: np.ndarray,
    *,
    view_bounds: tuple[float, float] | None,
    max_major_ticks: int | None,
) -> np.ndarray:
    values = _normalized_tick_values(ticks)
    if view_bounds is None:
        return values

    low, high = view_bounds
    if not np.isfinite(low) or not np.isfinite(high) or low <= 0 or high <= 0 or np.isclose(low, high):
        return values

    low, high = sorted((float(low), float(high)))
    low_log = float(np.log10(low))
    high_log = float(np.log10(high))
    mantissas = _DENSE_LOG_FINE_MANTISSAS if (high_log - low_log) < 0.45 else _DENSE_LOG_MANTISSAS
    candidates: list[float] = []
    start_exp = int(np.floor(low_log)) - 1
    stop_exp = int(np.ceil(high_log)) + 1
    for exponent in range(start_exp, stop_exp + 1):
        base = 10.0 ** exponent
        for mantissa in mantissas:
            candidate = float(mantissa * base)
            if low * (1 - 1e-9) <= candidate <= high * (1 + 1e-9):
                candidates.append(candidate)

    dense_values = _normalized_tick_values(candidates)
    if dense_values.size < _MIN_DENSE_LOG_MAJOR_TICKS:
        fallback = np.geomspace(low, high, num=_MIN_DENSE_LOG_MAJOR_TICKS)
        dense_values = _normalized_tick_values(np.concatenate((dense_values, fallback)))
    if max_major_ticks is not None and dense_values.size > max_major_ticks:
        dense_values = _cap_visible_major_ticks(dense_values, scale="log", max_major_ticks=max_major_ticks)
    return dense_values if dense_values.size else values


def _resolved_major_ticks_for_density(
    ticks: Sequence[float] | np.ndarray,
    *,
    scale: str,
    density: str | None,
    max_major_ticks: int | None = None,
    view_bounds: tuple[float, float] | None = None,
) -> np.ndarray:
    values = _normalized_tick_values(ticks)
    density_mode = _normalized_tick_density(density)
    if values.size == 0 or density_mode == "auto":
        return values
    if density_mode == "sparse":
        target_count = max(
            2,
            min(
                values.size,
                min(max_major_ticks or _SPARSE_MAJOR_TICK_TARGET, _SPARSE_MAJOR_TICK_TARGET),
            ),
        )
        return _sparsify_major_ticks(values, target_count=target_count)
    if scale == "log":
        return _densify_log_major_ticks(
            values,
            view_bounds=view_bounds,
            max_major_ticks=max_major_ticks,
        )
    if scale != "linear":
        return values
    return _densify_linear_major_ticks(
        values,
        target_count=max_major_ticks or _DENSE_MAJOR_TICK_TARGET,
    )


def _linear_minor_ticks_from_major_ticks(ticks: np.ndarray) -> np.ndarray:
    values = _normalized_tick_values(ticks)
    if values.size < 2:
        return np.array([], dtype=float)
    return _normalized_tick_values((values[:-1] + values[1:]) / 2.0)


def _log_minor_ticks_from_major_ticks(ticks: np.ndarray) -> np.ndarray:
    values = _normalized_tick_values(ticks)
    if values.size < 2:
        return np.array([], dtype=float)
    minors: list[float] = []
    for low, high in zip(values[:-1], values[1:], strict=True):
        if low <= 0 or high <= 0:
            continue
        ratio = high / low
        if np.isclose(ratio, 10.0, atol=1e-6, rtol=1e-6):
            for factor in (2.0, 5.0):
                candidate = low * factor
                if candidate < high * (1 - 1e-9):
                    minors.append(candidate)
    return _normalized_tick_values(minors)


def _apply_minor_tick_locator(axis, *, scale: str, major_ticks: np.ndarray) -> None:
    values = _normalized_tick_values(major_ticks)
    if values.size < 2:
        axis.set_minor_locator(NullLocator())
        return
    if scale == "log":
        minor_ticks = _log_minor_ticks_from_major_ticks(values)
        axis.set_minor_locator(FixedLocator(minor_ticks.tolist()) if minor_ticks.size else NullLocator())
        return
    minor_ticks = _linear_minor_ticks_from_major_ticks(values)
    axis.set_minor_locator(FixedLocator(minor_ticks.tolist()) if minor_ticks.size else NullLocator())


def _apply_tick_edge_label_visibility(
    axis,
    *,
    ticks: np.ndarray,
    edge_labels: str | None,
) -> None:
    mode = _normalized_tick_edge_labels(edge_labels)
    if mode == "auto":
        return
    values = _normalized_tick_values(ticks)
    if values.size == 0:
        return
    hide_lower = mode in {"hide_min", "hide_both"}
    hide_upper = mode in {"hide_max", "hide_both"}
    base_formatter = axis.get_major_formatter()
    if hasattr(base_formatter, "set_locs"):
        base_formatter.set_locs(values.tolist())
    labels = [str(base_formatter(value, position)) for position, value in enumerate(values)]
    if hide_lower:
        labels[0] = ""
    if hide_upper:
        labels[-1] = ""
    axis.set_major_formatter(FixedFormatter(labels))


def _format_dense_log_tick_label(value: float) -> str:
    if not np.isfinite(value) or value <= 0:
        return ""
    if 0.1 <= abs(value) < 1000:
        return f"{value:g}"

    exponent = int(np.floor(np.log10(value)))
    base = 10.0 ** exponent
    mantissa = float(value / base)
    for candidate in (*_DENSE_LOG_FINE_MANTISSAS, 10.0):
        if np.isclose(mantissa, candidate, rtol=1e-7, atol=1e-9):
            mantissa = candidate
            break
    if np.isclose(mantissa, 10.0, rtol=1e-7, atol=1e-9):
        mantissa = 1.0
        exponent += 1
    if np.isclose(mantissa, 1.0, rtol=1e-7, atol=1e-9):
        return rf"$10^{{{exponent}}}$"
    return rf"${mantissa:g}\times10^{{{exponent}}}$"


def _apply_numeric_axis_tick_preferences(
    axis,
    *,
    scale: str,
    tick_density: str | None = None,
    tick_edge_labels: str | None = None,
    max_major_ticks: int | None = None,
) -> None:
    major_ticks = _resolved_major_ticks_for_density(
        axis.get_majorticklocs(),
        scale=scale,
        density=tick_density,
        max_major_ticks=max_major_ticks,
        view_bounds=_axis_view_bounds(axis),
    )
    if major_ticks.size:
        axis.set_major_locator(FixedLocator(major_ticks.tolist()))
        if scale == "log" and _normalized_tick_density(tick_density) == "dense":
            axis.set_major_formatter(FixedFormatter([_format_dense_log_tick_label(tick) for tick in major_ticks]))
    _apply_minor_tick_locator(axis, scale=scale, major_ticks=major_ticks)
    _apply_tick_edge_label_visibility(
        axis,
        ticks=major_ticks,
        edge_labels=tick_edge_labels,
    )


def _clear_categorical_x_minor_ticks(ax: plt.Axes) -> None:
    ax.xaxis.set_minor_locator(NullLocator())
    ax.tick_params(axis="x", which="minor", bottom=False, top=False, length=0)

def _uses_positive_zero_origin(
    *,
    axis_mode: AxisMode,
    scale: str,
    raw_bounds: tuple[float, float] | None,
) -> bool:
    return (
        axis_mode == "auto_positive"
        and scale == "linear"
        and raw_bounds is not None
        and float(raw_bounds[0]) >= 0
    )

def _tick_bounds_with_zero_origin(
    raw_bounds: tuple[float, float] | None,
    *,
    axis_mode: AxisMode,
    scale: str,
) -> tuple[float, float] | None:
    if not _uses_positive_zero_origin(axis_mode=axis_mode, scale=scale, raw_bounds=raw_bounds):
        return raw_bounds
    assert raw_bounds is not None
    return (0.0, float(raw_bounds[1]))

def _pin_positive_zero_origin(
    ax: plt.Axes,
    *,
    axis_mode: AxisMode,
    scale: str,
    raw_bounds: tuple[float, float] | None,
) -> None:
    if not _uses_positive_zero_origin(axis_mode=axis_mode, scale=scale, raw_bounds=raw_bounds):
        return
    assert raw_bounds is not None
    y_low, y_high = ax.get_ylim()
    upper = max(float(raw_bounds[1]), float(max(y_low, y_high)))
    if y_low <= y_high:
        ax.set_ylim(0.0, upper)
    else:
        ax.set_ylim(upper, 0.0)

def _ensure_visible_linear_lower_tick(
    ax: plt.Axes,
    *,
    max_major_ticks: int = MAX_VISIBLE_Y_MAJOR_TICKS,
) -> None:
    y_low, y_high = ax.get_ylim()
    lower = float(min(y_low, y_high))
    upper = float(max(y_low, y_high))
    ticks = np.asarray(ax.get_yticks(), dtype=float)
    ticks = ticks[np.isfinite(ticks)]
    visible = ticks[(ticks >= lower) & (ticks <= upper)]
    if np.any(np.isclose(visible, lower)):
        return

    if visible.size == 0:
        combined = np.asarray([lower], dtype=float)
    else:
        combined = np.unique(np.concatenate(([lower], visible)))
        if combined.size > max_major_ticks:
            tail = combined[1:]
            keep_tail = max_major_ticks - 1
            if keep_tail <= 0:
                combined = np.asarray([lower], dtype=float)
            else:
                step = max(int(np.ceil(tail.size / keep_tail)), 1)
                tail = tail[::step][:keep_tail]
                combined = np.concatenate(([lower], tail))
    ax.yaxis.set_major_locator(FixedLocator(combined))

def _apply_axis_tick_filter(
    axis,
    *,
    raw_bounds: tuple[float, float] | None,
    display_bounds: tuple[float, float],
    scale: str,
    include_minor: bool = True,
    max_major_ticks: int | None = None,
) -> None:
    if raw_bounds is None:
        return

    for which, locator_getter in (("major", axis.get_major_locator), ("minor", axis.get_minor_locator)):
        if which == "minor" and not include_minor:
            continue
        try:
            ticks = locator_getter().tick_values(*display_bounds)
        except Exception:
            continue
        bounds_for_ticks: tuple[float, float] = (
            (float(min(display_bounds)), float(max(display_bounds)))
            if scale == "log"
            else raw_bounds
        )
        filtered = _filter_ticks_to_raw_bounds(ticks, bounds_for_ticks, scale=scale)
        if which == "major" and scale == "log" and raw_bounds is not None and filtered.size > 1:
            raw_low = float(min(raw_bounds))
            if filtered[0] < raw_low:
                filtered = filtered[1:]
        if which == "major" and max_major_ticks is not None:
            filtered = _cap_visible_major_ticks(filtered, scale=scale, max_major_ticks=max_major_ticks)
        _set_axis_locator_from_filtered_ticks(axis, filtered, which=which)

def _apply_visible_y_tick_policy(
    ax: plt.Axes,
    *,
    scale: str,
    raw_bounds: tuple[float, float] | None,
) -> None:
    bounds = tuple(sorted(ax.get_ylim()))
    display_bounds = ax.get_ylim()
    effective_raw_bounds = raw_bounds if raw_bounds is not None else bounds
    tick_raw_bounds = effective_raw_bounds

    try:
        major_ticks = ax.yaxis.get_major_locator().tick_values(*display_bounds)
    except Exception:
        major_ticks = np.array([], dtype=float)

    bounds_for_ticks = tuple(sorted(display_bounds)) if scale == "log" else effective_raw_bounds
    filtered_major = _filter_ticks_to_raw_bounds(major_ticks, bounds_for_ticks, scale=scale)

    if (
        raw_bounds is not None
        and filtered_major.size <= 3
        and filtered_major.size > 0
        and float(filtered_major.max()) < float(raw_bounds[1])
    ):
        y_low, y_high = ax.get_ylim()
        if scale == "log" and bounds[0] > 0 and bounds[1] > 0:
            expanded_upper = 10 ** np.ceil(np.log10(bounds[1]))
            if expanded_upper <= bounds[1]:
                expanded_upper *= 10
        else:
            if filtered_major.size >= 2:
                step = float(np.median(np.diff(filtered_major)))
            else:
                step = max(abs(float(bounds[1] - bounds[0])) * 0.2, 1.0)
            expanded_upper = max(float(bounds[1]), float(filtered_major.max()) + step)
            tick_raw_bounds = (effective_raw_bounds[0], expanded_upper)

        if y_low <= y_high:
            ax.set_ylim(y_low, expanded_upper)
        else:
            ax.set_ylim(expanded_upper, y_high)
        display_bounds = ax.get_ylim()

    _apply_axis_tick_filter(
        ax.yaxis,
        raw_bounds=tick_raw_bounds,
        display_bounds=display_bounds,
        scale=scale,
        max_major_ticks=MAX_VISIBLE_Y_MAJOR_TICKS,
    )

def _compute_heatmap_cax_geometry(
    position: transforms.Bbox,
    *,
    layout_overrides: dict[str, float] | None = None,
) -> tuple[list[float], list[float]]:
    layout = dict(_HEATMAP_LAYOUT)
    if layout_overrides:
        layout.update(layout_overrides)
    if str(layout.get("frame_envelope_mode") or "") == "standard_graph":
        colorbar_height = max(
            position.height * float(layout["colorbar_height_fraction"]),
            0.010,
        )
        colorbar_top = position.y0 + position.height * float(layout.get("colorbar_top_edge_fraction", 1.0))
        colorbar_y0 = colorbar_top - colorbar_height
        main_gap = position.height * float(layout.get("colorbar_main_gap_fraction", 0.1))
        heatmap_top = max(colorbar_y0 - main_gap, position.y0 + position.height * 0.55)
        colorbar_x0 = position.x0 + position.width * float(layout["colorbar_x_offset_fraction"])
        colorbar_width = min(
            position.width * float(layout["colorbar_width_fraction"]),
            position.x1 - colorbar_x0,
        )
        heatmap_rect = [position.x0, position.y0, position.width, heatmap_top - position.y0]
        cax_rect = [colorbar_x0, colorbar_y0, colorbar_width, colorbar_height]
        return heatmap_rect, cax_rect

    available_height = max(1.0 - position.y1, 1e-6)
    cbar_y0 = position.y1 + min(
        max(
            available_height * float(layout["colorbar_y_offset_fraction"]),
            float(layout["colorbar_y_offset_min"]),
        ),
        available_height * float(layout["colorbar_y_offset_max_fraction"]),
    )
    cbar_height = min(
        max(
            available_height * float(layout["colorbar_height_fraction"]),
            float(layout["colorbar_height_min"]),
        ),
        max(
            available_height
            - (cbar_y0 - position.y1)
            - float(layout["colorbar_bottom_gap"]),
            0.010,
        ),
    )
    cbar_x0 = position.x0 + position.width * float(layout["colorbar_x_offset_fraction"])
    cbar_width = position.width * float(layout["colorbar_width_fraction"])
    heatmap_rect = [position.x0, position.y0, position.width, position.height]
    cax_rect = [
        cbar_x0,
        cbar_y0,
        cbar_width,
        cbar_height,
    ]
    return heatmap_rect, cax_rect
