from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import transforms

from src import mpl_backend, plot_style  # noqa: F401
from src.data_loader import CurveSeries
from src.layout_policy import (
    LayoutCandidate,
    LayoutScore,
    choose_layout_candidate,
    empty_layout_decision,
    record_layout_decision,
)
from src.layout_scoring import bbox_overlaps_any, expanded_bbox, proximity_penalty
from src.plot_contract import qa_profile
from src.plotting_primitives import (
    _LINEAR_OUTER_PADDING_FRACTION,
    _STACKED_X_USE_STANDARD_ENDPOINT_POLICY,
    AxisLimits,
    AxisMode,
    AxisTickPolicy,
    LegendMode,
    SharedAxisLayout,
    _solve_linear_axis_policy,
    _solve_log_axis_policy,
    _validate_scale_values,
)

MARKER_STYLE_CYCLE = ("o", "s", "^", "D", "v", "P", "X")

HIDDEN_Y_LABEL_X = -0.167

INSIDE_LEGEND_INSET_FRACTION = 0.025

@dataclass(frozen=True)
class StackedLayout:
    series_list: list[CurveSeries]
    floor: float
    step: float
    max_span: float

@dataclass(frozen=True)
class BaselineLabelWindow:
    points: np.ndarray
    baseline: float
    flatness: float
    peak_height: float
    bbox_left: float
    bbox_right: float
    bbox_width: float
    bbox_height: float
    local_min: float
    local_max: float

@dataclass(frozen=True)
class CurveTemplate:
    xscale: str
    yscale: str
    width_mm: float
    height_mm: float
    left_margin_mm: float | None
    right_margin_mm: float | None
    bottom_margin_mm: float | None
    top_margin_mm: float | None
    legend_mode: LegendMode = "inside_best"
    axis_mode: AxisMode = "auto"
    y_padding_top: float = 0.18
    y_padding_bottom: float = 0.06
    reverse_x: bool = False
    show_markers: bool = True
    stack_mode: str = "none"
    stack_floor_fraction: float = 0.22
    stack_gap_fraction: float = 0.22
    series_label_mode: str = "legend"
    series_label_side: str = "auto"
    label_track_inset_fraction: float = 0.06
    label_offset_pt: float = 5.0
    baseline_mode: str = "none"
    show_y_ticks: bool = True


@dataclass(frozen=True)
class LegendPlacementPolicy:
    candidate_order: tuple[str, ...]
    bias_step: float


CURVE_TEMPLATES: dict[str, CurveTemplate] = {
    "frequency_sweep": CurveTemplate(
        xscale="log",
        yscale="log",
        width_mm=plot_style.PANEL_WIDTH_MM,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
    ),
    "temperature_sweep": CurveTemplate(
        xscale="linear",
        yscale="log",
        width_mm=120,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
    ),
    "stress_relaxation": CurveTemplate(
        xscale="log",
        yscale="linear",
        width_mm=plot_style.PANEL_WIDTH_MM,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
    ),
    "tensile_curve": CurveTemplate(
        xscale="linear",
        yscale="linear",
        width_mm=plot_style.PANEL_WIDTH_MM,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
        axis_mode="auto_positive",
    ),
    "ftir": CurveTemplate(
        xscale="linear",
        yscale="linear",
        width_mm=plot_style.PANEL_WIDTH_MM,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
        y_padding_top=0.08,
        y_padding_bottom=0.04,
        legend_mode="none",
        reverse_x=True,
        show_markers=False,
        stack_mode="auto_vertical",
        series_label_mode="edge",
        show_y_ticks=False,
    ),
    "nmr": CurveTemplate(
        xscale="linear",
        yscale="linear",
        width_mm=plot_style.PANEL_WIDTH_MM,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
        y_padding_top=0.08,
        y_padding_bottom=0.04,
        legend_mode="none",
        reverse_x=True,
        show_markers=False,
        stack_mode="auto_vertical",
        series_label_mode="edge",
        baseline_mode="linear_endpoints",
        show_y_ticks=False,
    ),
    "xrd": CurveTemplate(
        xscale="linear",
        yscale="linear",
        width_mm=plot_style.PANEL_WIDTH_MM,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
        y_padding_top=0.08,
        y_padding_bottom=0.04,
        legend_mode="none",
        show_markers=False,
        stack_mode="auto_vertical",
        series_label_mode="edge",
        show_y_ticks=False,
    ),
    "dsc": CurveTemplate(
        xscale="linear",
        yscale="linear",
        width_mm=plot_style.PANEL_WIDTH_MM,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
        y_padding_top=0.08,
        y_padding_bottom=0.04,
        legend_mode="none",
        show_markers=False,
        stack_mode="auto_vertical",
        series_label_mode="edge",
        baseline_mode="linear_endpoints",
        show_y_ticks=False,
    ),
    "tga": CurveTemplate(
        xscale="linear",
        yscale="linear",
        width_mm=plot_style.PANEL_WIDTH_MM,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
        show_markers=False,
    ),
    "dma": CurveTemplate(
        xscale="linear",
        yscale="linear",
        width_mm=plot_style.PANEL_WIDTH_MM,
        height_mm=plot_style.PANEL_HEIGHT_MM,
        left_margin_mm=None,
        right_margin_mm=None,
        bottom_margin_mm=None,
        top_margin_mm=None,
        show_markers=False,
    ),
}

_STANDARD_LEGEND_DEFAULT_ORDER = ("upper_right", "lower_right", "upper_left", "lower_left")
_TENSILE_STANDARD_LEGEND_DEFAULT_ORDER = ("lower_right", "upper_right", "lower_left", "upper_left")
_COMPACT_LEGEND_DEFAULT_ORDER = (
    "upper_center",
    "upper_right",
    "lower_right",
    "upper_left",
    "lower_left",
    "lower_center",
)
_TENSILE_COMPACT_LEGEND_DEFAULT_ORDER = (
    "lower_right",
    "upper_right",
    "lower_left",
    "upper_left",
    "upper_center",
    "lower_center",
)


def _legend_inset_pair(inset_fraction: float | tuple[float, float]) -> tuple[float, float]:
    if isinstance(inset_fraction, tuple):
        return inset_fraction
    return inset_fraction, inset_fraction


def absolute_legend_inset_fractions(
    *,
    width_mm: float,
    height_mm: float,
    left_margin_mm: float,
    right_margin_mm: float,
    bottom_margin_mm: float,
    top_margin_mm: float,
    default: float | None = None,
) -> tuple[float, float]:
    spacing = plot_style.current_spacing()
    base_inset = _current_legend_inset(default)
    base_axis_width_mm = max(1.0, spacing.panel_width_mm - spacing.left_margin_mm - spacing.right_margin_mm)
    base_axis_height_mm = max(1.0, spacing.panel_height_mm - spacing.bottom_margin_mm - spacing.top_margin_mm)
    axis_width_mm = max(1.0, width_mm - left_margin_mm - right_margin_mm)
    axis_height_mm = max(1.0, height_mm - bottom_margin_mm - top_margin_mm)
    return (base_inset * base_axis_width_mm / axis_width_mm, base_inset * base_axis_height_mm / axis_height_mm)


def _legend_candidate_specs(
    *,
    inset_fraction: float | tuple[float, float],
) -> dict[str, tuple[tuple[float, float], dict[str, object]]]:
    inset_x, inset_y = _legend_inset_pair(inset_fraction)
    return {
        "upper_left": ((inset_x, 1.0 - inset_y), {"loc": "upper left", "alignment": "left"}),
        "lower_left": ((inset_x, inset_y), {"loc": "lower left", "alignment": "left"}),
        "upper_right": ((1.0 - inset_x, 1.0 - inset_y), {"loc": "upper right", "alignment": "right"}),
        "lower_right": ((1.0 - inset_x, inset_y), {"loc": "lower right", "alignment": "right"}),
        "upper_center": ((0.5, 1.0 - inset_y), {"loc": "upper center", "alignment": "center"}),
        "lower_center": ((0.5, inset_y), {"loc": "lower center", "alignment": "center"}),
    }


def _ordered_legend_candidates(
    *,
    candidate_order: tuple[str, ...],
    bias_step: float,
    inset_fraction: float | tuple[float, float],
) -> list[LayoutCandidate]:
    specs = _legend_candidate_specs(inset_fraction=inset_fraction)
    candidates: list[LayoutCandidate] = []
    for index, candidate_id in enumerate(candidate_order):
        spec = specs.get(candidate_id)
        if spec is None:
            continue
        anchor, payload = spec
        candidates.append(
            LayoutCandidate(
                candidate_id=candidate_id,
                anchor=anchor,
                payload={**payload, "bias": float(index) * float(bias_step)},
                notes="contract-ranked legend candidate",
            )
        )
    return candidates


def curve_legend_policy(
    *,
    preserve_stress_label: bool,
    compact: bool,
) -> LegendPlacementPolicy:
    profile = qa_profile("curve")
    if compact:
        order_key = (
            "tensile_compact_legend_candidate_order"
            if preserve_stress_label
            else "compact_legend_candidate_order"
        )
        default_order = (
            _TENSILE_COMPACT_LEGEND_DEFAULT_ORDER if preserve_stress_label else _COMPACT_LEGEND_DEFAULT_ORDER
        )
        bias_key = (
            "tensile_compact_legend_candidate_bias_step"
            if preserve_stress_label
            else "compact_legend_candidate_bias_step"
        )
        default_bias = 25.0 if preserve_stress_label else 0.75
    else:
        order_key = "tensile_legend_candidate_order" if preserve_stress_label else "legend_candidate_order"
        default_order = (
            _TENSILE_STANDARD_LEGEND_DEFAULT_ORDER if preserve_stress_label else _STANDARD_LEGEND_DEFAULT_ORDER
        )
        bias_key = "tensile_legend_candidate_bias_step" if preserve_stress_label else "legend_candidate_bias_step"
        default_bias = 25.0 if preserve_stress_label else 0.75
    raw_order = profile.get(order_key, default_order)
    candidate_order = tuple(str(item) for item in raw_order) if isinstance(raw_order, (list, tuple)) else default_order
    if not candidate_order:
        candidate_order = default_order
    return LegendPlacementPolicy(
        candidate_order=candidate_order,
        bias_step=float(profile.get(bias_key, default_bias)),
    )


def legend_layout_candidates(
    *,
    preserve_stress_label: bool,
    compact: bool,
    inset_fraction: float | tuple[float, float],
) -> list[LayoutCandidate]:
    policy = curve_legend_policy(preserve_stress_label=preserve_stress_label, compact=compact)
    return _ordered_legend_candidates(
        candidate_order=policy.candidate_order,
        bias_step=policy.bias_step,
        inset_fraction=inset_fraction,
    )


def _current_legend_inset(default: float | None = None) -> float:
    if default is not None:
        return default
    return plot_style.current_spacing().legend_inset_fraction


def _legend_kwargs(
    legend_mode: LegendMode,
    *,
    inset_fraction: float | tuple[float, float] = INSIDE_LEGEND_INSET_FRACTION,
) -> dict[str, object]:
    if legend_mode == "none":
        return {}
    if legend_mode == "outside":
        return {"loc": "upper left", "bbox_to_anchor": (1.02, 1.0), "borderaxespad": 0.0}
    if legend_mode == "inside_forced":
        return {"loc": "upper right"}
    if legend_mode.startswith("inside_"):
        candidate_id = legend_mode.removeprefix("inside_")
        candidate = _legend_candidate_specs(inset_fraction=inset_fraction).get(candidate_id)
        if candidate is not None:
            anchor, payload = candidate
            return {
                "loc": str(payload.get("loc", "upper right")),
                "bbox_to_anchor": anchor,
                "borderaxespad": 0.0,
                "alignment": str(payload.get("alignment", "right")),
            }
    return {"loc": "upper right"}


def _infer_markevery(length: int) -> int | None:
    if length <= 20:
        return None
    return max(2, int(np.ceil(length / 12)))

def _clone_curve_series(series: CurveSeries, data: pd.DataFrame) -> CurveSeries:
    return CurveSeries(
        sample=series.sample,
        x_label=series.x_label,
        y_label=series.y_label,
        x_unit=series.x_unit,
        y_unit=series.y_unit,
        data=data,
    )

def _baseline_correct_series(
    series_list: Sequence[CurveSeries],
    *,
    baseline_mode: str = "none",
) -> list[CurveSeries]:
    if baseline_mode == "none":
        return list(series_list)

    corrected: list[CurveSeries] = []
    for series in series_list:
        x = series.data["x"].to_numpy(dtype=float)
        y = series.data["y"].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        if valid.sum() < 3:
            corrected.append(_clone_curve_series(series, series.data.copy()))
            continue

        x_valid = x[valid]
        y_valid = y[valid]
        n_edge = max(3, min(len(x_valid) // 12, 30))
        x_start = float(np.mean(x_valid[:n_edge]))
        y_start = float(np.mean(y_valid[:n_edge]))
        x_end = float(np.mean(x_valid[-n_edge:]))
        y_end = float(np.mean(y_valid[-n_edge:]))

        if np.isclose(x_start, x_end):
            baseline = np.full_like(y, y_start, dtype=float)
        else:
            slope = (y_end - y_start) / (x_end - x_start)
            baseline = y_start + slope * (x - x_start)

        shifted = series.data.copy()
        shifted["y"] = shifted["y"] - baseline
        corrected.append(_clone_curve_series(series, shifted))

    return corrected

def _robust_span(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 1.0
    q05, q95 = np.quantile(finite, [0.05, 0.95])
    span = float(q95 - q05)
    if np.isclose(span, 0.0):
        span = float(finite.max() - finite.min())
    if np.isclose(span, 0.0):
        span = max(abs(float(finite.max())), 1.0) * 0.15
    return span

def _prepare_stacked_layout(
    series_list: Sequence[CurveSeries],
    *,
    stack_floor_fraction: float,
    stack_gap_fraction: float,
    step_scale: float = 1.0,
) -> StackedLayout:
    if len(series_list) <= 1:
        single_spans = [
            _robust_span(series.data["y"].to_numpy(dtype=float))
            for series in series_list
        ]
        max_span = max(single_spans) if single_spans else 1.0
        return StackedLayout(list(series_list), 0.0, max_span, max_span)

    prepared: list[tuple[CurveSeries, pd.DataFrame, float, float]] = []
    spans: list[float] = []
    peak_heights: list[float] = []
    for series in series_list:
        y = series.data["y"].to_numpy(dtype=float)
        finite = y[np.isfinite(y)]
        shifted = series.data.copy()
        if finite.size:
            shifted["y"] = shifted["y"] - float(finite.min())
        span = _robust_span(shifted["y"].to_numpy(dtype=float))
        peak_height = float(np.nanmax(shifted["y"].to_numpy(dtype=float))) if finite.size else 0.0
        prepared.append((series, shifted, span, peak_height))
        spans.append(span)
        peak_heights.append(peak_height)

    max_span = max(spans) if spans else 1.0
    max_peak_height = max(peak_heights) if peak_heights else max_span
    scale = max(step_scale, 1.0)
    floor = max(
        max_span * stack_floor_fraction * scale,
        max_peak_height * 0.16 * scale,
    )
    step = max_span * (1.0 + stack_gap_fraction) * scale
    # Stacked spectra need enough room for the whole peak envelope to clear the
    # next series baseline, not just enough room for labels.
    peak_clearance = max(
        max_span * max(stack_gap_fraction, 0.16) * 0.95,
        max_peak_height * 0.24,
    )
    minimum_step = (max_peak_height + peak_clearance) * scale
    step = max(step, minimum_step)

    stacked: list[CurveSeries] = []
    for idx, (series, shifted, _, _) in enumerate(prepared):
        final = shifted.copy()
        final["y"] = final["y"] + floor + idx * step
        stacked.append(_clone_curve_series(series, final))

    return StackedLayout(stacked, floor, step, max_span)

def _stack_retry_scales() -> tuple[float, ...]:
    base = 1.15
    return tuple(base**index for index in range(5))

def _compute_x_limits(
    x_values: Sequence[np.ndarray] | Sequence[Sequence[float]],
    *,
    xscale: str,
    x_padding: float = 0.02,
) -> tuple[AxisTickPolicy, tuple[float, float]]:
    x_arrays = _validate_scale_values(x_values, scale=xscale, axis_name="X")
    x_min = min(float(arr.min()) for arr in x_arrays)
    x_max = max(float(arr.max()) for arr in x_arrays)
    if xscale == "log":
        policy = _solve_log_axis_policy(
            x_min,
            x_max,
            lower_padding=max(x_padding, _LINEAR_OUTER_PADDING_FRACTION),
            upper_padding=max(x_padding, _LINEAR_OUTER_PADDING_FRACTION),
        )
    else:
        policy = _solve_linear_axis_policy(
            x_min,
            x_max,
            lower_display_padding_fraction=max(x_padding, _LINEAR_OUTER_PADDING_FRACTION),
            upper_display_padding_fraction=max(x_padding, _LINEAR_OUTER_PADDING_FRACTION),
        )
    return policy, (x_min, x_max)

def compute_shared_curve_x_layout(
    x_values: Sequence[np.ndarray] | Sequence[Sequence[float]],
    *,
    xscale: str,
    x_padding: float = 0.02,
) -> SharedAxisLayout:
    policy, raw_bounds = _compute_x_limits(
        x_values,
        xscale=xscale,
        x_padding=x_padding,
    )
    return SharedAxisLayout(
        display_bounds=policy.display_bounds,
        labeled_bounds=policy.labeled_bounds,
        raw_bounds=raw_bounds,
        visible_ticks=policy.major_ticks,
    )

def _compute_stacked_axis_limits(
    layout: StackedLayout,
    *,
    xscale: str,
    y_padding_top: float,
    x_padding: float = 0.02,
) -> AxisLimits:
    x_policy, raw_xlim = _compute_x_limits(
        [series.data["x"].to_numpy(dtype=float) for series in layout.series_list],
        xscale=xscale,
        x_padding=x_padding,
    )
    xlim = x_policy.display_bounds if _STACKED_X_USE_STANDARD_ENDPOINT_POLICY else x_policy.labeled_bounds
    y_arrays = _validate_scale_values(
        [series.data["y"].to_numpy(dtype=float) for series in layout.series_list],
        scale="linear",
        axis_name="Y",
    )
    y_min = min(float(arr.min()) for arr in y_arrays)
    y_max = max(float(arr.max()) for arr in y_arrays)
    # Labels may force a larger stack step during retries. Headroom has to
    # follow the actual stack spacing, otherwise retries only spread the traces
    # apart but still leave no room for text near the top edge.
    label_headroom = max(layout.max_span * 0.58, layout.step * 0.52)
    y_high = y_max + layout.max_span * max(y_padding_top, 0.08) + label_headroom
    return AxisLimits(
        xlim=xlim,
        ylim=(0.0, y_high),
        raw_xlim=raw_xlim,
        raw_ylim=(y_min, y_max),
        x_tick_policy=x_policy if _STACKED_X_USE_STANDARD_ENDPOINT_POLICY else None,
    )

def _resolve_visual_edge_target(x: np.ndarray, reverse_x: bool, side: str, inset_fraction: float = 0.06) -> float:
    x_min = float(np.min(x))
    x_max = float(np.max(x))
    span = x_max - x_min
    if np.isclose(span, 0.0):
        return x_min
    if side == "left":
        return x_max - span * inset_fraction if reverse_x else x_min + span * inset_fraction
    return x_min + span * inset_fraction if reverse_x else x_max - span * inset_fraction

def _score_series_label_side(
    series_list: Sequence[CurveSeries],
    reverse_x: bool,
    side: str,
    *,
    inset_fraction: float,
) -> float:
    score = 0.0
    for series in series_list:
        x = series.data["x"].to_numpy(dtype=float)
        y = series.data["y"].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        x = x[valid]
        y = y[valid]
        if len(x) < 4:
            continue
        order = np.argsort(x)
        x = x[order]
        y = y[order]
        target_x = _resolve_visual_edge_target(x, reverse_x, side, inset_fraction=inset_fraction)
        window = max((x.max() - x.min()) * 0.08, 1e-9)
        mask = np.abs(x - target_x) <= window
        if mask.sum() < 4:
            idx = int(np.argmin(np.abs(x - target_x)))
            lo = max(0, idx - 2)
            hi = min(len(x), idx + 3)
            local_y = y[lo:hi]
        else:
            local_y = y[mask]
        if len(local_y) < 2:
            continue
        score += _robust_span(local_y)
        score += abs(float(local_y[-1] - local_y[0])) * 0.35
        score += float(np.mean(np.abs(np.diff(local_y)))) * 0.45
    return score

def _resolve_series_label_side(
    series_list: Sequence[CurveSeries],
    reverse_x: bool,
    series_label_side: str,
    *,
    inset_fraction: float,
) -> str:
    if series_label_side in {"left", "right"}:
        return series_label_side
    left_score = _score_series_label_side(series_list, reverse_x, "left", inset_fraction=inset_fraction)
    right_score = _score_series_label_side(series_list, reverse_x, "right", inset_fraction=inset_fraction)
    if np.isclose(left_score, right_score):
        return "left" if reverse_x else "right"
    return "left" if left_score < right_score else "right"

def _display_points_for_series(ax: plt.Axes, series_list: Sequence[CurveSeries]) -> list[np.ndarray]:
    def _densify_polyline(points: np.ndarray, max_step_px: float = 3.0) -> np.ndarray:
        if len(points) < 2:
            return points
        dense_parts: list[np.ndarray] = [points[:1]]
        for start, end in zip(points[:-1], points[1:], strict=True):
            delta = end - start
            segment_length = float(max(abs(delta[0]), abs(delta[1])))
            steps = max(int(np.ceil(segment_length / max_step_px)), 1)
            if steps == 1:
                dense_parts.append(end[None, :])
                continue
            fractions = np.linspace(0.0, 1.0, steps + 1, dtype=float)[1:]
            segment = start + fractions[:, None] * delta[None, :]
            dense_parts.append(segment)
        return np.vstack(dense_parts)

    display_points: list[np.ndarray] = []
    for series in series_list:
        x = series.data["x"].to_numpy(dtype=float)
        y = series.data["y"].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        if valid.sum() == 0:
            display_points.append(np.empty((0, 2)))
            continue
        points = ax.transData.transform(np.column_stack([x[valid], y[valid]]))
        dense = _densify_polyline(points)
        if len(dense) > 3000:
            indices = np.linspace(0, len(dense) - 1, 3000, dtype=int)
            dense = dense[indices]
        display_points.append(dense)
    return display_points

def _point_to_display_pixels(fig: plt.Figure, points: float) -> float:
    return points * fig.dpi / 72.0

def _display_band_points(
    points: np.ndarray,
    bbox_left: float,
    bbox_right: float,
    *,
    fallback_x: float | None = None,
    margin_px: float | None = None,
) -> np.ndarray:
    if points.size == 0:
        return np.empty((0, 2))
    band_width = max(bbox_right - bbox_left, 1.0)
    band_margin = margin_px if margin_px is not None else max(band_width * 0.08, 4.0)
    band = (points[:, 0] >= bbox_left - band_margin) & (points[:, 0] <= bbox_right + band_margin)
    if np.any(band):
        return points[band]
    target_x = fallback_x if fallback_x is not None else (bbox_left + bbox_right) / 2.0
    nearest_idx = int(np.argmin(np.abs(points[:, 0] - target_x)))
    lo = max(0, nearest_idx - 6)
    hi = min(len(points), nearest_idx + 7)
    return points[lo:hi]

def _exact_band_points(
    points: np.ndarray,
    bbox_left: float,
    bbox_right: float,
) -> np.ndarray:
    if points.size == 0:
        return np.empty((0, 2))
    band = (points[:, 0] >= bbox_left) & (points[:, 0] <= bbox_right)
    return points[band]

def _flat_window_score(points: np.ndarray) -> float:
    if len(points) < 3:
        return float("inf")
    x = points[:, 0]
    y = points[:, 1]
    q10, q25, q50, q75, q90 = np.quantile(y, [0.10, 0.25, 0.50, 0.75, 0.90])
    dx = max(float(np.max(x) - np.min(x)), 1.0)
    slope = abs(float(y[-1] - y[0])) / dx
    flat_span = float(q75 - q25)
    peak_penalty = float(q90 - q50)
    roughness = float(np.median(np.abs(np.diff(y)))) if len(y) > 1 else 0.0
    return flat_span * 0.9 + peak_penalty * 1.45 + slope * 20.0 + roughness * 2.4

def _baseline_level(points: np.ndarray) -> float:
    if len(points) == 0:
        return 0.0
    local_y = np.sort(points[:, 1])
    cutoff = max(int(np.ceil(len(local_y) * 0.45)), 1)
    return float(np.median(local_y[:cutoff]))

def _stacked_label_y_candidates(
    lower_bound: float,
    upper_bound: float,
    *,
    bbox_height: float,
) -> np.ndarray:
    if upper_bound <= lower_bound:
        return np.array([], dtype=float)
    corridor_mid = float((lower_bound + upper_bound) / 2.0)
    preferred_offsets = np.array(
        [
            0.0,
            max(min(bbox_height * 0.10, 5.0), 2.5),
            -max(min(bbox_height * 0.10, 5.0), 2.5),
            max(min(bbox_height * 0.18, 8.0), 4.0),
            -max(min(bbox_height * 0.18, 8.0), 4.0),
        ],
        dtype=float,
    )
    candidates = corridor_mid + preferred_offsets
    candidates = candidates[(candidates >= lower_bound - 1e-6) & (candidates <= upper_bound + 1e-6)]
    if candidates.size == 0:
        return np.array([lower_bound], dtype=float)
    return np.unique(np.clip(candidates, lower_bound, upper_bound))

def _label_rail_candidates(
    axes_bbox: transforms.Bbox,
    *,
    side: str,
    inset_fraction: float,
    search_band_fraction: float,
    max_label_width: float,
    num_candidates: int = 36,
) -> list[tuple[float, float]]:
    positions: list[tuple[float, float]] = []
    side_pad = axes_bbox.width * inset_fraction
    search_width = max(axes_bbox.width * max(search_band_fraction, 0.01), max_label_width * 3.2)
    search_width = min(search_width, axes_bbox.width * 0.55)
    interior_guard = axes_bbox.width * 0.06

    if side == "left":
        start = float(axes_bbox.x0 + side_pad + max_label_width + 2.0)
        end = float(min(start + search_width, axes_bbox.x1 - interior_guard))
        rail_positions = np.linspace(start, end, num_candidates, dtype=float)
    else:
        start = float(axes_bbox.x1 - side_pad - max_label_width - 2.0)
        end = float(max(start - search_width, axes_bbox.x0 + interior_guard))
        rail_positions = np.linspace(start, end, num_candidates, dtype=float)

    for display_x in rail_positions:
        edge_distance = (
            float(display_x - axes_bbox.x0 - max_label_width)
            if side == "left"
            else float(axes_bbox.x1 - display_x - max_label_width)
        )
        positions.append((float(display_x), edge_distance))
    return positions

def _find_flat_label_windows(
    display_points: Sequence[np.ndarray],
    label_records: Sequence[tuple[int, str, tuple[float, float, float] | str, float, float]],
    *,
    axes_bbox: transforms.Bbox,
    side: str,
    inset_fraction: float,
    search_band_fraction: float,
    min_samples: int = 3,
) -> list[tuple[float, float, dict[int, BaselineLabelWindow]]]:
    rail_plans: list[tuple[float, float, dict[int, BaselineLabelWindow]]] = []
    max_label_width = max((record[3] for record in label_records), default=0.0)
    for rail_x, rail_offset in _label_rail_candidates(
        axes_bbox,
        side=side,
        inset_fraction=inset_fraction,
        search_band_fraction=search_band_fraction,
        max_label_width=max_label_width,
    ):
        per_series: dict[int, BaselineLabelWindow] = {}
        total_score = rail_offset * 0.18
        valid = True
        for series_index, _, _, bbox_width, bbox_height in label_records:
            bbox_left = rail_x - bbox_width if side == "left" else rail_x
            bbox_right = bbox_left + bbox_width
            exact_points = _exact_band_points(
                display_points[series_index],
                bbox_left,
                bbox_right,
            )
            local_points = exact_points
            if len(local_points) < min_samples:
                local_points = _display_band_points(
                    display_points[series_index],
                    bbox_left,
                    bbox_right,
                    fallback_x=rail_x,
                    margin_px=max(bbox_width * 0.18, 8.0),
                )
            if len(local_points) < min_samples:
                valid = False
                break
            baseline = _baseline_level(local_points)
            flatness = _flat_window_score(local_points)
            peak_height = max(float(np.max(local_points[:, 1])) - baseline, 0.0)
            local_min = float(np.min(local_points[:, 1]))
            local_max = float(np.max(local_points[:, 1]))
            local_span = max(local_max - local_min, 0.0)
            upper_quartile_penalty = max(float(np.quantile(local_points[:, 1], 0.75)) - baseline, 0.0)
            per_series[series_index] = BaselineLabelWindow(
                points=local_points,
                baseline=baseline,
                flatness=flatness,
                peak_height=peak_height,
                bbox_left=bbox_left,
                bbox_right=bbox_right,
                bbox_width=bbox_width,
                bbox_height=bbox_height,
                local_min=local_min,
                local_max=local_max,
            )
            # Strongly prefer rails that sit on flat baseline segments rather
            # than near peaks. The rail is shared by all series, so the score
            # needs to punish even a single peaky local window quite hard.
            total_score += (
                flatness * 1.0
                + upper_quartile_penalty * 7.5
                + peak_height * 13.5
                + local_span * 4.5
            )
        if valid and len(per_series) == len(label_records):
            rail_plans.append((total_score, rail_x, per_series))
    rail_plans.sort(key=lambda item: item[0])
    return rail_plans

def _choose_baseline_label_rail(
    display_points: Sequence[np.ndarray],
    label_records: Sequence[tuple[int, str, tuple[float, float, float] | str, float, float]],
    *,
    axes_bbox: transforms.Bbox,
    side: str,
    inset_fraction: float,
    search_band_fraction: float,
) -> list[tuple[str, float, float, dict[int, BaselineLabelWindow]]]:
    candidate_sides = [side] if side in {"left", "right"} else ["left", "right"]
    ranked_plans: list[
        tuple[str, float, float, dict[int, BaselineLabelWindow]]
    ] = []
    for visual_side in candidate_sides:
        for flatness_score, rail_x, per_series in _find_flat_label_windows(
            display_points,
            label_records,
            axes_bbox=axes_bbox,
            side=visual_side,
            inset_fraction=inset_fraction,
            search_band_fraction=search_band_fraction,
        ):
            ranked_plans.append((visual_side, flatness_score, rail_x, per_series))
    ranked_plans.sort(key=lambda item: (item[1], 0 if item[0] == "right" else 1))
    return ranked_plans

def _place_labels_on_baseline_rail(
    ax: plt.Axes,
    label_records: Sequence[tuple[int, str, tuple[float, float, float] | str, float, float]],
    *,
    axes_bbox: transforms.Bbox,
    all_curve_points: np.ndarray,
    visual_side: str,
    rail_x: float,
    per_series: dict[int, BaselineLabelWindow],
    label_gap: float,
    pixel_offset: float,
) -> tuple[float, list[tuple[float, float, str, tuple[float, float, float] | str]]] | None:
    placed_bboxes: list[transforms.Bbox] = []
    planned_labels: list[tuple[float, float, str, tuple[float, float, float] | str]] = []
    total_score = 0.0
    previous_label_top: float | None = None
    for series_index, label_text, color, _, _ in sorted(label_records, key=lambda item: item[0], reverse=True):
        window = per_series[series_index]
        bbox_height = window.bbox_height
        # Use the local baseline as the primary anchor so labels sit above the
        # flat rail rather than near peaks. Curve/label collisions are still
        # handled by bbox scoring against all rendered points.
        lower_bound = max(
            window.baseline + max(pixel_offset, window.bbox_height * 0.18),
            float(axes_bbox.y0 + label_gap),
        )
        upper_bound = float(axes_bbox.y1 - label_gap - bbox_height)
        if series_index + 1 < len(label_records) and (series_index + 1) in per_series:
            upper_window = per_series[series_index + 1]
            upper_bound = min(
                upper_bound,
                upper_window.baseline - max(pixel_offset * 0.55, label_gap) - bbox_height,
            )
        if previous_label_top is not None:
            upper_bound = min(upper_bound, previous_label_top - label_gap - bbox_height)
        if upper_bound <= lower_bound:
            return None

        y_candidates = _stacked_label_y_candidates(
            lower_bound,
            upper_bound,
            bbox_height=bbox_height,
        )
        best_candidate: tuple[float, transforms.Bbox] | None = None
        best_bottom: float | None = None
        for candidate_bottom in y_candidates:
            candidate_bbox = transforms.Bbox.from_bounds(
                window.bbox_left,
                float(candidate_bottom),
                window.bbox_width,
                window.bbox_height,
            )
            candidate_score = _score_label_bbox(
                candidate_bbox,
                axes_bbox=axes_bbox,
                all_curve_points=all_curve_points,
                placed_bboxes=placed_bboxes,
                rail_penalty=window.flatness * 1.0
                + window.peak_height * 1.6
                + float(candidate_bottom - lower_bound) * 0.65,
            )
            if candidate_score >= 1_000_000_000.0:
                continue
            if best_candidate is None or candidate_score < best_candidate[0]:
                best_candidate = (candidate_score, candidate_bbox)
                best_bottom = float(candidate_bottom)

        if best_candidate is None or best_bottom is None:
            return None

        candidate_score, candidate_bbox = best_candidate
        candidate_data_x = float(ax.transData.inverted().transform((rail_x, axes_bbox.y0))[0])
        candidate_data_y = float(ax.transData.inverted().transform((rail_x, best_bottom))[1])
        total_score += candidate_score
        planned_labels.append((candidate_data_x, candidate_data_y, label_text, color))
        placed_bboxes.append(candidate_bbox.expanded(1.03, 1.08))
        previous_label_top = float(candidate_bbox.y0)
    return total_score, planned_labels

def _score_label_bbox(
    bbox: transforms.Bbox,
    *,
    axes_bbox: transforms.Bbox,
    all_curve_points: np.ndarray,
    placed_bboxes: Sequence[transforms.Bbox],
    rail_penalty: float,
) -> float:
    score = rail_penalty
    if bbox.x0 < axes_bbox.x0 or bbox.x1 > axes_bbox.x1 or bbox.y0 < axes_bbox.y0 or bbox.y1 > axes_bbox.y1:
        return 1_000_000_000.0

    expanded = expanded_bbox(bbox, x_scale=1.03, y_scale=1.10)
    if placed_bboxes and bbox_overlaps_any(expanded, placed_bboxes):
        return 1_000_000_000.0

    x_margin = max(bbox.width * 0.25, 10.0)
    local_band = (all_curve_points[:, 0] >= bbox.x0 - x_margin) & (all_curve_points[:, 0] <= bbox.x1 + x_margin)
    local_points = all_curve_points[local_band] if np.any(local_band) else all_curve_points
    inside = (
        (local_points[:, 0] >= expanded.x0)
        & (local_points[:, 0] <= expanded.x1)
        & (local_points[:, 1] >= expanded.y0)
        & (local_points[:, 1] <= expanded.y1)
    )
    if np.any(inside):
        return 1_000_000_000.0

    score += proximity_penalty(
        local_points,
        expanded,
        radius=11.0,
        weight=18.0,
        normalize=False,
    )
    return score

def _place_stacked_labels(
    ax: plt.Axes,
    series_list: Sequence[CurveSeries],
    colors: Sequence[tuple[float, float, float] | str],
    *,
    reverse_x: bool,
    side: str,
    inset_fraction: float,
    label_offset_pt: float,
    labels: Sequence[str] | None = None,
    search_band_fraction: float = 0.10,
    fontsize: float = 6.0,
) -> bool:
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    display_points = _display_points_for_series(ax, series_list)
    axes_bbox = ax.get_window_extent(renderer=renderer)
    label_gap = _point_to_display_pixels(fig, 3.5)
    pixel_offset = _point_to_display_pixels(fig, max(label_offset_pt, 6.0))
    all_points = [points for points in display_points if points.size]
    if not all_points:
        return True
    all_curve_points = np.vstack(all_points)
    label_texts = list(labels) if labels is not None else [series.sample for series in series_list]

    def _measure_text_bbox(
        label_text: str,
        color: tuple[float, float, float] | str,
        visual_side: str,
    ) -> tuple[float, float]:
        text = ax.text(
            0.5,
            0.5,
            label_text,
            ha="right" if visual_side == "left" else "left",
            va="bottom",
            color=color,
            fontsize=fontsize,
            alpha=0.0,
            transform=ax.transAxes,
        )
        bbox = text.get_window_extent(renderer=renderer)
        text.remove()
        return float(bbox.width), float(bbox.height)

    label_records: list[tuple[int, str, tuple[float, float, float] | str, float, float]] = []
    for series_index, (label_text, color) in enumerate(zip(label_texts, colors, strict=True)):
        bbox_width, bbox_height = _measure_text_bbox(label_text, color, "left")
        label_records.append((series_index, label_text, color, bbox_width, bbox_height))

    plan_candidates: list[LayoutCandidate] = []
    for candidate_index, (visual_side, flatness_score, rail_x, per_series) in enumerate(
        _choose_baseline_label_rail(
            display_points,
            label_records,
            axes_bbox=axes_bbox,
            side=side,
            inset_fraction=inset_fraction,
            search_band_fraction=search_band_fraction,
        )
    ):
        plan = _place_labels_on_baseline_rail(
            ax,
            label_records,
            axes_bbox=axes_bbox,
            all_curve_points=all_curve_points,
            visual_side=visual_side,
            rail_x=rail_x,
            per_series=per_series,
            label_gap=label_gap,
            pixel_offset=pixel_offset,
        )
        if plan is None:
            continue
        total_score, planned_labels = plan
        total_score += flatness_score
        plan_candidates.append(
            LayoutCandidate(
                candidate_id=f"{visual_side}_rail_{candidate_index}",
                anchor=(float(rail_x), 0.0),
                standoff_pt=float(label_offset_pt),
                payload={
                    "score": float(total_score),
                    "planned_labels": planned_labels,
                    "visual_side": visual_side,
                    "flatness": float(flatness_score),
                },
                notes="stacked label rail candidate",
            )
        )

    if not plan_candidates:
        record_layout_decision(
            fig,
            empty_layout_decision("series_labels", reason="no_feasible_label_plan"),
            context={"path": "stacked_label_rail", "phase": "no_plan"},
        )
        return False

    def _score_plan(candidate: LayoutCandidate) -> LayoutScore:
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        score = float(payload.get("score", float("inf")))
        flatness = float(payload.get("flatness", 0.0))
        return LayoutScore(
            score=score,
            blocked=not np.isfinite(score),
            reason=f"stacked_label_score={score:.4f}; flatness={flatness:.4f}",
        )

    decision = choose_layout_candidate(
        object_kind="series_labels",
        candidates=plan_candidates,
        score_hook=_score_plan,
    )
    record_layout_decision(
        fig,
        decision,
        context={"path": "stacked_label_rail", "phase": "candidate_selection"},
    )
    chosen = decision.chosen_candidate
    if chosen is None or not isinstance(chosen.payload, dict):
        return False

    planned_labels = chosen.payload.get("planned_labels")
    visual_side = chosen.payload.get("visual_side")
    if not isinstance(planned_labels, list) or visual_side not in {"left", "right"}:
        return False

    for x_pos, y_pos, label_text, color in planned_labels:
        ax.text(
            x_pos,
            y_pos,
            label_text,
            ha="right" if visual_side == "left" else "left",
            va="bottom",
            color=color,
            fontsize=fontsize,
            clip_on=True,
            transform=ax.transData,
        )
    return True

def _validate_curve_series_input(series_list: Sequence[CurveSeries]) -> None:
    if not series_list:
        raise ValueError("No curve series were provided for plotting.")
    for index, series in enumerate(series_list, start=1):
        if not {"x", "y"}.issubset(series.data.columns):
            raise ValueError(f"Curve series {index} is missing required x/y columns.")
        if series.data.empty:
            raise ValueError(f"Curve series {index} ({series.sample!r}) does not contain any data.")
        numeric = series.data[["x", "y"]].apply(pd.to_numeric, errors="coerce")
        if numeric.dropna(how="all").empty:
            raise ValueError(f"Curve series {index} ({series.sample!r}) does not contain numeric x/y data.")

def _place_series_edge_labels(
    ax: plt.Axes,
    series_list: Sequence[CurveSeries],
    colors: Sequence[tuple[float, float, float] | str],
    *,
    reverse_x: bool,
    side: str,
    inset_fraction: float,
    label_offset_pt: float,
    labels: Sequence[str] | None = None,
    search_band_fraction: float = 0.16,
    fontsize: float = 6.0,
) -> bool:
    return _place_stacked_labels(
        ax,
        series_list,
        colors,
        reverse_x=reverse_x,
        side=side,
        inset_fraction=inset_fraction,
        label_offset_pt=label_offset_pt,
        labels=labels,
        search_band_fraction=search_band_fraction,
        fontsize=fontsize,
    )
