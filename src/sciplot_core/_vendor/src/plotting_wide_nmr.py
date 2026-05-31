from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import transforms
from matplotlib.patches import Rectangle

from src import mpl_backend, plot_style  # noqa: F401
from src.data_loader import CurveSeries
from src.layout_policy import (
    LayoutCandidate,
    LayoutScore,
    choose_layout_candidate,
    empty_layout_decision,
    flag_margin_fallback,
    record_layout_decision,
)
from src.layout_scoring import bbox_overlaps_any, expanded_bbox, score_points_against_bbox
from src.plotting_curve_support import (
    StackedLayout,
    _baseline_correct_series,
    _place_series_edge_labels,
    _prepare_stacked_layout,
    _robust_span,
    _stack_retry_scales,
)
from src.plotting_primitives import _apply_axis_tick_filter, _format_axis_label
from src.wide_nmr import (
    WIDE_NMR_STRUCTURE_RESERVED_MM,
    WIDE_NMR_TOTAL_HEIGHT_MM,
    WIDE_NMR_WIDTH_MM,
    WideNMRConfig,
    WideNMRHighlightRegion,
    WideNMRSegment,
)


def _clone_with_sample_name(series: CurveSeries, sample_name: str) -> CurveSeries:
    return CurveSeries(
        sample=sample_name,
        x_label=series.x_label,
        y_label=series.y_label,
        x_unit=series.x_unit,
        y_unit=series.y_unit,
        data=series.data.copy(),
    )

def _prepare_wide_nmr_series(
    series_list: Sequence[CurveSeries],
    config: WideNMRConfig,
) -> tuple[list[str], list[str], list[CurveSeries]]:
    by_sample = {series.sample: series for series in series_list}
    ordered_keys: list[str] = []
    if config.series_order:
        for key in config.series_order:
            if key not in by_sample:
                raise ValueError(f"wide_nmr config references unknown sample {key!r}.")
            ordered_keys.append(key)
    for series in series_list:
        if series.sample not in ordered_keys:
            ordered_keys.append(series.sample)

    display_names = [config.series_labels.get(key, key) for key in ordered_keys]
    ordered_series = [
        _clone_with_sample_name(by_sample[key], display_name)
        for key, display_name in zip(ordered_keys, display_names, strict=True)
    ]
    return ordered_keys, display_names, ordered_series

def _wide_nmr_segment_width_ratios(segments: Sequence[WideNMRSegment]) -> list[float]:
    ratios: list[float] = []
    for segment in segments:
        if segment.width_ratio is not None:
            ratios.append(float(segment.width_ratio))
        else:
            ratios.append(max(abs(segment.x_max - segment.x_min), 0.1))
    return ratios

def _wide_nmr_local_edge_score(
    series_list: Sequence[CurveSeries],
    segment: WideNMRSegment,
    *,
    side: str,
    inset_fraction: float,
) -> float:
    score = 0.0
    seg_low = min(segment.x_min, segment.x_max)
    seg_high = max(segment.x_min, segment.x_max)
    seg_span = max(seg_high - seg_low, 1e-9)
    if side == "left":
        target_x = segment.x_max - seg_span * inset_fraction
    else:
        target_x = segment.x_min + seg_span * inset_fraction
    window = max(seg_span * 0.08, 1e-9)

    for series in series_list:
        x = series.data["x"].to_numpy(dtype=float)
        y = series.data["y"].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y) & (x >= seg_low) & (x <= seg_high)
        if valid.sum() < 4:
            continue
        local_x = x[valid]
        local_y = y[valid]
        mask = np.abs(local_x - target_x) <= window
        if mask.sum() < 4:
            idx = int(np.argmin(np.abs(local_x - target_x)))
            lo = max(0, idx - 2)
            hi = min(len(local_x), idx + 3)
            sample_y = local_y[lo:hi]
        else:
            sample_y = local_y[mask]
        if len(sample_y) < 2:
            continue
        score += _robust_span(sample_y)
        score += abs(float(sample_y[-1] - sample_y[0])) * 0.35
        score += float(np.mean(np.abs(np.diff(sample_y)))) * 0.45
    return score

def _resolve_wide_nmr_label_side(
    series_list: Sequence[CurveSeries],
    config: WideNMRConfig,
) -> str:
    if config.label_side in {"left", "right"}:
        return config.label_side
    left_score = _wide_nmr_local_edge_score(
        series_list,
        config.segments[0],
        side="left",
        inset_fraction=config.label_inset_fraction,
    )
    right_score = _wide_nmr_local_edge_score(
        series_list,
        config.segments[-1],
        side="right",
        inset_fraction=config.label_inset_fraction,
    )
    if np.isclose(left_score, right_score):
        return "left"
    return "left" if left_score < right_score else "right"

def _pick_segment_axis_for_region(
    axes: Sequence[plt.Axes],
    segments: Sequence[WideNMRSegment],
    region: WideNMRHighlightRegion,
) -> tuple[plt.Axes, WideNMRSegment]:
    region_mid = (region.x_min + region.x_max) / 2
    for axis, segment in zip(axes, segments, strict=True):
        seg_low = min(segment.x_min, segment.x_max)
        seg_high = max(segment.x_min, segment.x_max)
        if seg_low <= region_mid <= seg_high:
            return axis, segment
    best_idx = 0
    best_overlap = -1.0
    region_low = min(region.x_min, region.x_max)
    region_high = max(region.x_min, region.x_max)
    for idx, segment in enumerate(segments):
        seg_low = min(segment.x_min, segment.x_max)
        seg_high = max(segment.x_min, segment.x_max)
        overlap = max(0.0, min(seg_high, region_high) - max(seg_low, region_low))
        if overlap > best_overlap:
            best_idx = idx
            best_overlap = overlap
    return axes[best_idx], segments[best_idx]

def _wide_nmr_region_matches_series(
    region: WideNMRHighlightRegion,
    raw_name: str,
    display_name: str,
) -> bool:
    if not region.series:
        return True
    return raw_name in region.series or display_name in region.series

def _collect_axis_display_points(ax: plt.Axes, *, max_points: int = 3200) -> np.ndarray:
    point_blocks: list[np.ndarray] = []
    for line in ax.lines:
        x_values = np.asarray(line.get_xdata(), dtype=float)
        y_values = np.asarray(line.get_ydata(), dtype=float)
        valid = np.isfinite(x_values) & np.isfinite(y_values)
        if not np.any(valid):
            continue
        transformed = ax.transData.transform(np.column_stack([x_values[valid], y_values[valid]]))
        if len(transformed) > max_points:
            indices = np.linspace(0, len(transformed) - 1, max_points, dtype=int)
            transformed = transformed[indices]
        point_blocks.append(transformed)
    for collection in ax.collections:
        offsets = np.asarray(collection.get_offsets(), dtype=float)
        if offsets.size == 0:
            continue
        valid = np.isfinite(offsets[:, 0]) & np.isfinite(offsets[:, 1])
        transformed = ax.transData.transform(offsets[valid])
        if len(transformed) > max_points:
            indices = np.linspace(0, len(transformed) - 1, max_points, dtype=int)
            transformed = transformed[indices]
        point_blocks.append(transformed)
    if not point_blocks:
        return np.empty((0, 2), dtype=float)
    stacked = np.vstack(point_blocks)
    if len(stacked) > max_points:
        indices = np.linspace(0, len(stacked) - 1, max_points, dtype=int)
        stacked = stacked[indices]
    return stacked

def _probe_axis_text_bbox(
    ax: plt.Axes,
    *,
    renderer: Any,
    x: float,
    y: float,
    text: str,
    color: str,
    fontsize: float,
    ha: str,
    va: str,
    clip_on: bool,
) -> transforms.Bbox:
    probe = ax.text(
        x,
        y,
        text,
        color=color,
        ha=ha,
        va=va,
        fontsize=fontsize,
        clip_on=clip_on,
        alpha=0.0,
        zorder=3.0,
    )
    bbox = probe.get_window_extent(renderer=renderer)
    probe.remove()
    return bbox

def _wide_nmr_region_label_candidates(
    *,
    region_mid: float,
    y_lows: Sequence[float],
    y_highs: Sequence[float],
    step: float,
    preferred_position: str,
) -> list[LayoutCandidate]:
    top_outside = max(y_highs) + step * 0.04
    bottom_outside = min(y_lows) - step * 0.04
    top_inside = max(y_highs) - step * 0.03
    bottom_inside = min(y_lows) + step * 0.03
    center_inside = (max(y_highs) + min(y_lows)) * 0.5

    top_candidate = LayoutCandidate(
        candidate_id="top_outside",
        standoff_pt=step * 0.04,
        payload={
            "x": region_mid,
            "y": top_outside,
            "ha": "center",
            "va": "bottom",
            "clip_on": False,
            "bias": 0.0 if preferred_position == "top" else 5.2,
        },
        notes="outside-top label candidate",
    )
    bottom_candidate = LayoutCandidate(
        candidate_id="bottom_outside",
        standoff_pt=step * 0.04,
        payload={
            "x": region_mid,
            "y": bottom_outside,
            "ha": "center",
            "va": "top",
            "clip_on": False,
            "bias": 0.0 if preferred_position == "bottom" else 5.2,
        },
        notes="outside-bottom label candidate",
    )
    inside_top_candidate = LayoutCandidate(
        candidate_id="top_inside",
        standoff_pt=step * 0.03,
        payload={
            "x": region_mid,
            "y": top_inside,
            "ha": "center",
            "va": "top",
            "clip_on": True,
            "bias": 2.4,
        },
        notes="inside-top fallback candidate",
    )
    inside_bottom_candidate = LayoutCandidate(
        candidate_id="bottom_inside",
        standoff_pt=step * 0.03,
        payload={
            "x": region_mid,
            "y": bottom_inside,
            "ha": "center",
            "va": "bottom",
            "clip_on": True,
            "bias": 2.6,
        },
        notes="inside-bottom fallback candidate",
    )
    center_candidate = LayoutCandidate(
        candidate_id="center_inside",
        standoff_pt=0.0,
        payload={
            "x": region_mid,
            "y": center_inside,
            "ha": "center",
            "va": "center",
            "clip_on": True,
            "bias": 4.2,
        },
        notes="center fallback candidate",
    )
    if preferred_position == "bottom":
        return [
            bottom_candidate,
            top_candidate,
            inside_bottom_candidate,
            inside_top_candidate,
            center_candidate,
        ]
    return [
        top_candidate,
        bottom_candidate,
        inside_top_candidate,
        inside_bottom_candidate,
        center_candidate,
    ]

def _place_wide_nmr_region_label_with_policy(
    *,
    axis: plt.Axes,
    region: WideNMRHighlightRegion,
    region_index: int,
    region_mid: float,
    y_lows: Sequence[float],
    y_highs: Sequence[float],
    layout: StackedLayout,
    placed_label_bboxes: list[transforms.Bbox],
) -> bool:
    fig = axis.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox = axis.get_window_extent(renderer=renderer)
    figure_bbox = fig.bbox
    points = _collect_axis_display_points(axis)
    existing_text_bboxes = [
        text.get_window_extent(renderer=renderer)
        for text in axis.texts
        if text.get_visible() and str(text.get_text()).strip()
    ]
    candidates = _wide_nmr_region_label_candidates(
        region_mid=region_mid,
        y_lows=y_lows,
        y_highs=y_highs,
        step=layout.step,
        preferred_position=region.label_position,
    )
    candidate_bboxes: dict[str, transforms.Bbox] = {}
    candidate_payloads: dict[str, dict[str, Any]] = {}

    def _score(candidate: LayoutCandidate) -> LayoutScore:
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        x_pos = float(payload.get("x", region_mid))
        y_pos = float(payload.get("y", max(y_highs)))
        ha = str(payload.get("ha", "center"))
        va = str(payload.get("va", "bottom"))
        clip_on = bool(payload.get("clip_on", False))
        bias = float(payload.get("bias", 0.0))

        bbox = _probe_axis_text_bbox(
            axis,
            renderer=renderer,
            x=x_pos,
            y=y_pos,
            text=region.label,
            color=region.color,
            fontsize=plot_style.current_typography().font_size_pt,
            ha=ha,
            va=va,
            clip_on=clip_on,
        )
        candidate_bboxes[candidate.candidate_id] = bbox
        candidate_payloads[candidate.candidate_id] = payload

        if bbox.width >= axes_bbox.width * 0.98:
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="label_too_wide_for_axis")
        margin_px = 2.0
        if (
            bbox.x0 < figure_bbox.x0 + margin_px
            or bbox.x1 > figure_bbox.x1 - margin_px
            or bbox.y0 < figure_bbox.y0 + margin_px
            or bbox.y1 > figure_bbox.y1 - margin_px
        ):
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="outside_figure_margin")
        axis_margin_px = 1.0
        if (
            bbox.x0 < axes_bbox.x0 + axis_margin_px
            or bbox.x1 > axes_bbox.x1 - axis_margin_px
            or bbox.y0 < axes_bbox.y0 + axis_margin_px
            or bbox.y1 > axes_bbox.y1 - axis_margin_px
        ):
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="outside_axis_bounds")

        expanded = expanded_bbox(bbox, x_scale=1.02, y_scale=1.08)
        if placed_label_bboxes and bbox_overlaps_any(expanded, placed_label_bboxes):
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="overlap_existing_annotation")
        if existing_text_bboxes and bbox_overlaps_any(expanded, existing_text_bboxes):
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="overlap_existing_text")

        point_metrics = score_points_against_bbox(
            points,
            bbox,
            inside_weight=12.0,
            near_radius=max(9.0, bbox.height * 0.85),
            near_weight=1.6,
        )
        score = point_metrics.total + bias
        reason = (
            f"inside={point_metrics.inside_count}; near={point_metrics.near_score:.3f}; bias={bias:.3f}"
        )
        return LayoutScore(score=float(score), reason=reason)

    decision = choose_layout_candidate(
        object_kind="annotation_textbox",
        candidates=candidates,
        score_hook=_score,
    )
    chosen = decision.chosen_candidate
    if chosen is None:
        record_layout_decision(
            fig,
            empty_layout_decision("annotation_textbox", reason="no_feasible_region_label_candidate"),
            context={
                "path": "wide_nmr_annotation",
                "phase": "candidate_selection",
                "annotation_kind": "highlight_region_label",
                "region_index": region_index,
                "label": region.label,
            },
        )
        return False
    chosen_payload = candidate_payloads.get(chosen.candidate_id, {})
    chosen_bbox = candidate_bboxes.get(chosen.candidate_id)
    if chosen.candidate_id not in {
        "top_outside" if region.label_position != "bottom" else "bottom_outside"
    }:
        decision = flag_margin_fallback(
            decision,
            action=f"region_label_fallback:{chosen.candidate_id}",
            reason=f"preferred_position={region.label_position}",
        )
    record_layout_decision(
        fig,
        decision,
        context={
            "path": "wide_nmr_annotation",
            "phase": "candidate_selection",
            "annotation_kind": "highlight_region_label",
            "region_index": region_index,
            "label": region.label,
        },
    )
    axis.text(
        float(chosen_payload.get("x", region_mid)),
        float(chosen_payload.get("y", max(y_highs))),
        region.label,
        color=region.color,
        ha=str(chosen_payload.get("ha", "center")),
        va=str(chosen_payload.get("va", "bottom")),
        fontsize=plot_style.current_typography().font_size_pt,
        clip_on=bool(chosen_payload.get("clip_on", False)),
        zorder=3,
    )
    if chosen_bbox is not None:
        placed_label_bboxes.append(expanded_bbox(chosen_bbox, x_scale=1.04, y_scale=1.12))
    return True

def _probe_figure_text_bbox(
    fig: plt.Figure,
    *,
    renderer: Any,
    x: float,
    y: float,
    text: str,
    fontsize: float,
    ha: str,
    va: str,
) -> transforms.Bbox:
    probe = fig.text(
        x,
        y,
        text,
        ha=ha,
        va=va,
        fontsize=fontsize,
        alpha=0.0,
    )
    bbox = probe.get_window_extent(renderer=renderer)
    probe.remove()
    return bbox

def _place_wide_nmr_panel_label_with_policy(
    *,
    fig: plt.Figure,
    panel_label: str,
    axes: Sequence[plt.Axes],
    left_margin_mm: float,
    right_margin_mm: float,
    width_mm: float,
) -> None:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    figure_bbox = fig.bbox
    axis_bboxes = [axis.get_window_extent(renderer=renderer) for axis in axes]
    existing_text_bboxes: list[transforms.Bbox] = []
    for axis in axes:
        for text in axis.texts:
            if text.get_visible():
                existing_text_bboxes.append(text.get_window_extent(renderer=renderer))
    for text in fig.texts:
        if text.get_visible():
            existing_text_bboxes.append(text.get_window_extent(renderer=renderer))

    left_anchor = float(left_margin_mm / width_mm)
    right_anchor = float(1.0 - right_margin_mm / width_mm)
    candidates = [
        LayoutCandidate(
            candidate_id="top_left",
            anchor=(left_anchor, 0.985),
            standoff_pt=2.0,
            payload={"x": left_anchor, "y": 0.985, "ha": "left", "va": "top", "bias": 0.0},
            notes="primary top-left panel label candidate",
        ),
        LayoutCandidate(
            candidate_id="top_right",
            anchor=(right_anchor, 0.985),
            standoff_pt=2.0,
            payload={"x": right_anchor, "y": 0.985, "ha": "right", "va": "top", "bias": 1.8},
            notes="top-right fallback panel label candidate",
        ),
        LayoutCandidate(
            candidate_id="top_center",
            anchor=(0.5, 0.985),
            standoff_pt=2.0,
            payload={"x": 0.5, "y": 0.985, "ha": "center", "va": "top", "bias": 2.8},
            notes="top-center fallback panel label candidate",
        ),
        LayoutCandidate(
            candidate_id="left_inner",
            anchor=(left_anchor, 0.94),
            standoff_pt=4.0,
            payload={"x": left_anchor, "y": 0.94, "ha": "left", "va": "top", "bias": 3.6},
            notes="inner fallback panel label candidate",
        ),
    ]
    candidate_bboxes: dict[str, transforms.Bbox] = {}
    candidate_payloads: dict[str, dict[str, Any]] = {}

    def _score(candidate: LayoutCandidate) -> LayoutScore:
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        x_pos = float(payload.get("x", left_anchor))
        y_pos = float(payload.get("y", 0.985))
        ha = str(payload.get("ha", "left"))
        va = str(payload.get("va", "top"))
        bias = float(payload.get("bias", 0.0))

        bbox = _probe_figure_text_bbox(
            fig,
            renderer=renderer,
            x=x_pos,
            y=y_pos,
            text=panel_label,
            fontsize=10.0,
            ha=ha,
            va=va,
        )
        candidate_bboxes[candidate.candidate_id] = bbox
        candidate_payloads[candidate.candidate_id] = payload

        margin_px = 2.0
        if (
            bbox.x0 < figure_bbox.x0 + margin_px
            or bbox.x1 > figure_bbox.x1 - margin_px
            or bbox.y0 < figure_bbox.y0 + margin_px
            or bbox.y1 > figure_bbox.y1 - margin_px
        ):
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="outside_figure_margin")
        if bbox.width >= figure_bbox.width * 0.95:
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="panel_label_too_wide")

        expanded = expanded_bbox(bbox, x_scale=1.03, y_scale=1.10)
        if existing_text_bboxes and bbox_overlaps_any(expanded, existing_text_bboxes):
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="overlap_existing_text")

        axis_overlap_penalty = 0.0
        if bbox_overlaps_any(expanded, axis_bboxes):
            axis_overlap_penalty = 4.0
        top_distance_penalty = max(0.0, (figure_bbox.y1 - bbox.y1) / max(figure_bbox.height, 1.0) * 3.0)
        score = axis_overlap_penalty + top_distance_penalty + bias
        reason = (
            f"axis_overlap_penalty={axis_overlap_penalty:.3f}; "
            f"top_distance_penalty={top_distance_penalty:.3f}; bias={bias:.3f}"
        )
        return LayoutScore(score=float(score), reason=reason)

    decision = choose_layout_candidate(
        object_kind="annotation_textbox",
        candidates=candidates,
        score_hook=_score,
    )
    chosen = decision.chosen_candidate
    if chosen is None:
        record_layout_decision(
            fig,
            empty_layout_decision("annotation_textbox", reason="no_feasible_panel_label_candidate"),
            context={
                "path": "wide_nmr_panel_label",
                "phase": "candidate_selection",
                "annotation_kind": "panel_label",
            },
        )
        return
    if chosen.candidate_id != "top_left":
        decision = flag_margin_fallback(
            decision,
            action=f"panel_label_fallback:{chosen.candidate_id}",
            reason="top_left candidate blocked or scored worse",
        )
    record_layout_decision(
        fig,
        decision,
        context={
            "path": "wide_nmr_panel_label",
            "phase": "candidate_selection",
            "annotation_kind": "panel_label",
        },
    )
    chosen_payload = candidate_payloads.get(chosen.candidate_id, {})
    fig.text(
        float(chosen_payload.get("x", left_anchor)),
        float(chosen_payload.get("y", 0.985)),
        panel_label,
        ha=str(chosen_payload.get("ha", "left")),
        va=str(chosen_payload.get("va", "top")),
        fontsize=10,
    )

def _add_wide_nmr_highlights(
    axes: Sequence[plt.Axes],
    segments: Sequence[WideNMRSegment],
    layout: StackedLayout,
    raw_names: Sequence[str],
    display_names: Sequence[str],
    config: WideNMRConfig,
) -> None:
    placed_label_bboxes: list[transforms.Bbox] = []
    for region_index, region in enumerate(config.highlight_regions):
        label_axis, _ = _pick_segment_axis_for_region(axes, segments, region)
        region_label_drawn = False
        for axis, segment in zip(axes, segments, strict=True):
            seg_low = min(segment.x_min, segment.x_max)
            seg_high = max(segment.x_min, segment.x_max)
            overlap_low = max(seg_low, min(region.x_min, region.x_max))
            overlap_high = min(seg_high, max(region.x_min, region.x_max))
            if overlap_high <= overlap_low:
                continue

            y_lows: list[float] = []
            y_highs: list[float] = []
            for raw_name, display_name, series in zip(
                raw_names,
                display_names,
                layout.series_list,
                strict=True,
            ):
                if not _wide_nmr_region_matches_series(region, raw_name, display_name):
                    continue
                x = series.data["x"].to_numpy(dtype=float)
                y = series.data["y"].to_numpy(dtype=float)
                mask = np.isfinite(x) & np.isfinite(y) & (x >= overlap_low) & (x <= overlap_high)
                if mask.sum() == 0:
                    continue
                local_y = y[mask]
                y_low = float(np.min(local_y) - layout.step * 0.08)
                y_high = float(np.max(local_y) + layout.step * 0.08)
                axis.add_patch(
                    Rectangle(
                        (overlap_low, y_low),
                        overlap_high - overlap_low,
                        y_high - y_low,
                        facecolor=region.color,
                        edgecolor="none",
                        alpha=min(region.alpha, plot_style.current_stroke().max_fill_alpha),
                        zorder=0.2,
                    )
                )
                y_lows.append(y_low)
                y_highs.append(y_high)

            if region.label and y_lows and axis is label_axis and not region_label_drawn:
                region_mid = (overlap_low + overlap_high) / 2
                region_label_drawn = _place_wide_nmr_region_label_with_policy(
                    axis=axis,
                    region=region,
                    region_index=region_index,
                    region_mid=region_mid,
                    y_lows=y_lows,
                    y_highs=y_highs,
                    layout=layout,
                    placed_label_bboxes=placed_label_bboxes,
                )

def _draw_wide_nmr_break_marks(left_ax: plt.Axes, right_ax: plt.Axes) -> None:
    d = 0.015
    kwargs_left = dict(transform=left_ax.transAxes, color="black", clip_on=False, linewidth=1.0)
    kwargs_right = dict(transform=right_ax.transAxes, color="black", clip_on=False, linewidth=1.0)
    left_ax.plot((1 - d, 1 + d), (-d, +d), **kwargs_left)
    left_ax.plot((1 - d, 1 + d), (-3 * d, -d), **kwargs_left)
    right_ax.plot((-d, +d), (-d, +d), **kwargs_right)
    right_ax.plot((-d, +d), (-3 * d, -d), **kwargs_right)

def plot_wide_nmr(
    series_list: Sequence[CurveSeries],
    config: WideNMRConfig,
    *,
    width_mm: float = WIDE_NMR_WIDTH_MM,
    height_mm: float = WIDE_NMR_TOTAL_HEIGHT_MM,
    left_margin_mm: float | None = None,
    right_margin_mm: float | None = None,
    bottom_margin_mm: float | None = None,
    top_margin_mm: float = 0.0,
    structure_reserved_mm: float = WIDE_NMR_STRUCTURE_RESERVED_MM,
    reverse_x: bool = True,
    baseline_mode: str = "linear_endpoints",
) -> tuple[plt.Figure, plt.Axes]:
    stroke = plot_style.current_stroke()
    spacing = plot_style.current_spacing()
    left_margin_mm = spacing.left_margin_mm if left_margin_mm is None else left_margin_mm
    right_margin_mm = spacing.right_margin_mm if right_margin_mm is None else right_margin_mm
    bottom_margin_mm = spacing.bottom_margin_mm if bottom_margin_mm is None else bottom_margin_mm
    raw_names, display_names, ordered_series = _prepare_wide_nmr_series(series_list, config)
    corrected_series = _baseline_correct_series(ordered_series, baseline_mode=baseline_mode)

    fig = plt.figure(
        figsize=(plot_style.mm_to_inch(width_mm), plot_style.mm_to_inch(height_mm)),
        constrained_layout=False,
    )
    reserved_top_mm = structure_reserved_mm + top_margin_mm
    plot_body_height_mm = max(height_mm - bottom_margin_mm - reserved_top_mm, 1e-9)
    root_grid = fig.add_gridspec(
        2,
        1,
        left=left_margin_mm / width_mm,
        right=1 - right_margin_mm / width_mm,
        bottom=bottom_margin_mm / height_mm,
        top=1.0,
        height_ratios=[reserved_top_mm, plot_body_height_mm],
        hspace=0.0,
    )
    spectrum_grid = root_grid[1].subgridspec(
        1,
        len(config.segments),
        width_ratios=_wide_nmr_segment_width_ratios(config.segments),
        wspace=config.segment_gap,
    )

    axes: list[plt.Axes] = []
    for idx, _segment in enumerate(config.segments):
        axis = fig.add_subplot(spectrum_grid[0, idx], sharey=axes[0] if axes else None)
        axes.append(axis)
    stacked_layout: StackedLayout | None = None
    preferred_label_side = _resolve_wide_nmr_label_side(corrected_series, config)
    for step_scale in _stack_retry_scales():
        stacked_layout = _prepare_stacked_layout(
            corrected_series,
            stack_floor_fraction=config.stack_floor_fraction,
            stack_gap_fraction=config.stack_gap_fraction,
            step_scale=step_scale,
        )
        y_arrays = [series.data["y"].to_numpy(dtype=float) for series in stacked_layout.series_list]
        y_max = max(float(np.nanmax(values)) for values in y_arrays)
        y_high = y_max + stacked_layout.max_span * (0.18 + 0.58)

        for axis, segment in zip(axes, config.segments, strict=True):
            axis.cla()
            for series in stacked_layout.series_list:
                axis.plot(
                    series.data["x"],
                    series.data["y"],
                    color="black",
                    linewidth=stroke.line_width_pt,
                    zorder=2,
                )

            if reverse_x:
                axis.set_xlim(segment.x_max, segment.x_min)
            else:
                axis.set_xlim(segment.x_min, segment.x_max)
            axis.set_ylim(0.0, y_high)
            axis.tick_params(axis="y", left=False, labelleft=False, which="both")
            axis.spines["left"].set_visible(False)
            axis.spines["top"].set_visible(False)
            axis.spines["right"].set_visible(False)
            seg_low = min(segment.x_min, segment.x_max)
            seg_high = max(segment.x_min, segment.x_max)
            _apply_axis_tick_filter(
                axis.xaxis,
                raw_bounds=(seg_low, seg_high),
                display_bounds=(seg_low, seg_high),
                scale="linear",
                include_minor=False,
            )

        candidate_sides = (
            [config.label_side]
            if config.label_side in {"left", "right"}
            else [preferred_label_side, "right" if preferred_label_side == "left" else "left"]
        )
        label_success = False
        for candidate_side in candidate_sides:
            target_axis = axes[0] if candidate_side == "left" else axes[-1]
            if _place_series_edge_labels(
                target_axis,
                stacked_layout.series_list,
                ["black"] * len(stacked_layout.series_list),
                reverse_x=reverse_x,
                side=candidate_side,
                inset_fraction=config.label_inset_fraction,
                label_offset_pt=config.label_offset_pt,
                labels=display_names,
                search_band_fraction=0.18,
                fontsize=6.4,
            ):
                label_success = True
                break
        if not label_success:
            continue
        _add_wide_nmr_highlights(
            axes,
            config.segments,
            stacked_layout,
            raw_names,
            display_names,
            config,
        )
        break

    for left_axis, right_axis in zip(axes[:-1], axes[1:], strict=True):
        _draw_wide_nmr_break_marks(left_axis, right_axis)

    first = series_list[0]
    fig.supxlabel(_format_axis_label(first.x_label, first.x_unit), x=1 - right_margin_mm / width_mm, ha="right")
    if config.panel_label:
        _place_wide_nmr_panel_label_with_policy(
            fig=fig,
            panel_label=config.panel_label,
            axes=axes,
            left_margin_mm=left_margin_mm,
            right_margin_mm=right_margin_mm,
            width_mm=width_mm,
        )

    return fig, axes[0]
