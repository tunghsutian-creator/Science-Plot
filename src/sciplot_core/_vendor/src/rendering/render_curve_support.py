from __future__ import annotations

from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
from src.layout_policy import (
    LayoutCandidate,
    LayoutScore,
    choose_layout_candidate,
    empty_layout_decision,
    flag_margin_fallback,
    record_layout_decision,
)
from src.layout_scoring import score_points_against_bbox
from src.plot_contract import qa_profile
from src.plotting_curve_support import _place_series_edge_labels, legend_layout_candidates
from src.rendering.models import RenderedPlot, RenderOptions
from src.rendering.qa import CurveAutofix, recommend_curve_autofix

from src import plot_style


@dataclass(frozen=True)
class CompactCurveEditorialProfile:
    direct_label_inset_fraction: float
    direct_label_offset_pt: float
    direct_label_search_band_fraction: float
    tick_width_scale: float
    tick_length_scale: float
    legend_max_series: int
    legend_columns: int
    legend_font_scale: float
    legend_handlelength: float
    legend_handletextpad: float
    legend_columnspacing: float
    legend_borderpad: float

def _prefer_direct_labels(options: RenderOptions, series_count: int, *, fallback: bool = False) -> bool:
    profile = qa_profile("curve")
    max_series_key = "direct_label_fallback_max_series" if fallback else "direct_label_max_series"
    return bool(
        series_count <= int(profile.get(max_series_key, 4))
        and np.isclose(options.width_mm, float(profile.get("small_panel_width_mm", options.width_mm)), atol=0.05)
        and np.isclose(options.height_mm, float(profile.get("small_panel_height_mm", options.height_mm)), atol=0.05)
    )

def _compact_curve_editorial_profile() -> CompactCurveEditorialProfile:
    profile = qa_profile("curve")
    return CompactCurveEditorialProfile(
        direct_label_inset_fraction=float(profile.get("compact_direct_label_inset_fraction", 0.04)),
        direct_label_offset_pt=float(profile.get("compact_direct_label_offset_pt", 4.0)),
        direct_label_search_band_fraction=float(profile.get("compact_direct_label_search_band_fraction", 0.12)),
        tick_width_scale=float(profile.get("compact_tick_width_scale", 0.82)),
        tick_length_scale=float(profile.get("compact_tick_length_scale", 0.88)),
        legend_max_series=int(profile.get("compact_legend_max_series", 3)),
        legend_columns=int(profile.get("compact_legend_columns", 2)),
        legend_font_scale=float(profile.get("compact_legend_font_scale", 0.92)),
        legend_handlelength=float(profile.get("compact_legend_handlelength", 1.35)),
        legend_handletextpad=float(profile.get("compact_legend_handletextpad", 0.35)),
        legend_columnspacing=float(profile.get("compact_legend_columnspacing", 0.8)),
        legend_borderpad=float(profile.get("compact_legend_borderpad", 0.15)),
    )

def _is_compact_curve_panel(options: RenderOptions) -> bool:
    profile = qa_profile("curve")
    return bool(
        np.isclose(options.width_mm, float(profile.get("small_panel_width_mm", options.width_mm)), atol=0.05)
        and np.isclose(options.height_mm, float(profile.get("small_panel_height_mm", options.height_mm)), atol=0.05)
    )

def _prefer_compact_legend(options: RenderOptions, series_count: int) -> bool:
    profile = _compact_curve_editorial_profile()
    return _is_compact_curve_panel(options) and 1 < series_count <= profile.legend_max_series

def _float_plot_kw(base_kwargs: dict[str, object], key: str, default: float) -> float:
    value = base_kwargs.get(key)
    return float(value) if isinstance(value, (int, float)) else default

def _curve_dense_fix(
    series_list,
    *,
    show_markers: bool,
    scatter: bool,
) -> CurveAutofix:
    total_points = max((len(series.data.index) for series in series_list), default=0)
    return recommend_curve_autofix(
        total_points=total_points,
        has_markers=show_markers,
        has_scatter=scatter,
    )

def _compact_curve_fix(options: RenderOptions) -> CurveAutofix:
    if not _is_compact_curve_panel(options):
        return CurveAutofix()
    profile = _compact_curve_editorial_profile()
    return CurveAutofix(
        tick_width_scale=profile.tick_width_scale,
        tick_length_scale=profile.tick_length_scale,
        autofixes_applied=("compact_tick_hierarchy",),
    )

def _merge_curve_fixes(*fixes: CurveAutofix) -> CurveAutofix:
    marker_every = None
    marker_size_scale = 1.0
    tick_width_scale = 1.0
    tick_length_scale = 1.0
    line_width_scale = 1.0
    collection_size_scale = 1.0
    autofixes: list[str] = []
    for fix in fixes:
        if fix.marker_every is not None:
            marker_every = max(marker_every or fix.marker_every, fix.marker_every)
        marker_size_scale *= fix.marker_size_scale
        tick_width_scale *= fix.tick_width_scale
        tick_length_scale *= fix.tick_length_scale
        line_width_scale *= fix.line_width_scale
        collection_size_scale *= fix.collection_size_scale
        autofixes.extend(fix.autofixes_applied)
    return CurveAutofix(
        marker_every=marker_every,
        marker_size_scale=marker_size_scale,
        tick_width_scale=tick_width_scale,
        tick_length_scale=tick_length_scale,
        line_width_scale=line_width_scale,
        collection_size_scale=collection_size_scale,
        autofixes_applied=tuple(dict.fromkeys(autofixes)),
    )

def _post_curve_fix(dense_fix: CurveAutofix, *, include_line_scale: bool) -> CurveAutofix:
    return CurveAutofix(
        tick_width_scale=dense_fix.tick_width_scale,
        tick_length_scale=dense_fix.tick_length_scale,
        line_width_scale=dense_fix.line_width_scale if include_line_scale else 1.0,
        collection_size_scale=dense_fix.collection_size_scale,
        autofixes_applied=dense_fix.autofixes_applied,
    )

def _curve_candidate_key(candidate: tuple[RenderedPlot, str]) -> tuple[float, int, int]:
    rendered, strategy = candidate
    qa = rendered.qa_report
    if qa is None:
        return (0.0, 0, 0)
    unsafe_issue_weights = {
        "series_identification": 80.0,
        "label_out_of_bounds": 45.0,
        "label_collision": 32.0,
        "legend_overlap": 28.0,
        "legend_footprint": 28.0,
        "legend_outside_bounds": 36.0,
        "legend_axes_too_small": 36.0,
        "tick_label_overlap": 30.0,
        "ftir_wavenumber_bounds_missing": 80.0,
    }
    critical_count = sum(1 for issue in qa.issues if issue.severity == "critical")
    direct_bonus = 2 if strategy.startswith("direct") else 1 if strategy == "compact_legend" else 0
    unsafe_penalty = sum(unsafe_issue_weights.get(issue.id, 0.0) for issue in qa.issues)
    return (qa.score - unsafe_penalty, -critical_count, direct_bonus)

def _resolve_visual_edge_target(
    x_values: np.ndarray,
    *,
    reverse_x: bool,
    side: str,
    inset_fraction: float,
) -> float:
    x_min = float(np.min(x_values))
    x_max = float(np.max(x_values))
    span = x_max - x_min
    if np.isclose(span, 0.0):
        return x_min
    if side == "left":
        return x_max - span * inset_fraction if reverse_x else x_min + span * inset_fraction
    return x_min + span * inset_fraction if reverse_x else x_max - span * inset_fraction

def _display_point_offset(fig: plt.Figure, value_pt: float) -> float:
    return max(value_pt, 0.0) * fig.dpi / 72.0

def _measure_label_bbox(
    ax: plt.Axes,
    renderer,
    *,
    label_text: str,
    color: object,
    fontsize: float,
    horizontal_alignment: str,
) -> tuple[float, float]:
    probe = ax.text(
        0.5,
        0.5,
        label_text,
        fontsize=fontsize,
        color=color,
        ha=horizontal_alignment,
        va="center",
        alpha=0.0,
        transform=ax.transAxes,
    )
    bbox = probe.get_window_extent(renderer=renderer)
    probe.remove()
    return float(bbox.width), float(bbox.height)

def _spread_label_centers(
    desired: np.ndarray,
    heights: np.ndarray,
    *,
    lower: float,
    upper: float,
    gap_px: float,
) -> np.ndarray | None:
    if desired.size == 0:
        return np.array([], dtype=float)
    order = np.argsort(desired)
    ordered_desired = desired[order]
    ordered_heights = heights[order]
    centers = ordered_desired.copy()
    lower_bounds = lower + ordered_heights / 2.0
    upper_bounds = upper - ordered_heights / 2.0
    centers[0] = np.clip(centers[0], lower_bounds[0], upper_bounds[0])
    for idx in range(1, len(centers)):
        required_gap = (ordered_heights[idx - 1] + ordered_heights[idx]) / 2.0 + gap_px
        centers[idx] = max(np.clip(centers[idx], lower_bounds[idx], upper_bounds[idx]), centers[idx - 1] + required_gap)
    overflow = max(centers[-1] - upper_bounds[-1], 0.0)
    if overflow > 0:
        centers -= overflow
    for idx in range(len(centers) - 2, -1, -1):
        required_gap = (ordered_heights[idx] + ordered_heights[idx + 1]) / 2.0 + gap_px
        centers[idx] = min(centers[idx], centers[idx + 1] - required_gap)
    underflow = max(lower_bounds[0] - centers[0], 0.0)
    if underflow > 0:
        centers += underflow
    for idx in range(1, len(centers)):
        required_gap = (ordered_heights[idx - 1] + ordered_heights[idx]) / 2.0 + gap_px
        centers[idx] = max(centers[idx], centers[idx - 1] + required_gap)
    if np.any(centers < lower_bounds - 1e-6) or np.any(centers > upper_bounds + 1e-6):
        return None
    result = np.empty_like(centers)
    result[order] = centers
    return result

def _series_display_colors(ax: plt.Axes, series_count: int) -> list[object]:
    if len(ax.lines) >= series_count:
        return [line.get_color() for line in ax.lines[:series_count]]
    if len(ax.collections) >= series_count:
        colors: list[object] = []
        for collection in ax.collections[:series_count]:
            facecolors = collection.get_facecolors()
            colors.append(tuple(facecolors[0]) if len(facecolors) else "black")
        return colors
    return list(plot_style.get_categorical_palette(n_colors=series_count))

def _plan_endpoint_direct_labels(
    ax: plt.Axes,
    series_list,
    *,
    reverse_x: bool,
    side: str,
    inset_fraction: float,
    label_offset_pt: float,
    fontsize: float,
) -> tuple[list[tuple[float, float, str, object]] | None, float, str]:
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes_bbox = ax.get_window_extent(renderer=renderer)
    colors = _series_display_colors(ax, len(series_list))
    offset_px = _display_point_offset(fig, max(label_offset_pt, 3.5))
    gap_px = _display_point_offset(fig, 3.8)
    margin_px = 1.5

    desired_y: list[float] = []
    widths: list[float] = []
    heights: list[float] = []
    anchor_x: list[float] = []
    labels: list[str] = []
    text_colors: list[object] = []

    alignment = "right" if side == "left" else "left"
    curve_anchor_x: list[float] = []

    for series, color in zip(series_list, colors, strict=True):
        x = series.data["x"].to_numpy(dtype=float)
        y = series.data["y"].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        x = x[valid]
        y = y[valid]
        if len(x) < 2:
            return None, float("inf"), "insufficient_points"
        order = np.argsort(x)
        x = x[order]
        y = y[order]
        target_x = _resolve_visual_edge_target(x, reverse_x=reverse_x, side=side, inset_fraction=inset_fraction)
        target_y = float(np.interp(target_x, x, y))
        curve_px = ax.transData.transform((target_x, target_y))
        label_text = str(series.sample)
        width_px, height_px = _measure_label_bbox(
            ax,
            renderer,
            label_text=label_text,
            color=color,
            fontsize=fontsize,
            horizontal_alignment=alignment,
        )
        if width_px > axes_bbox.width - 2.0 * margin_px:
            return None, float("inf"), "label_too_wide_for_axes"
        if side == "left":
            anchor = min(curve_px[0] - offset_px, axes_bbox.x1 - margin_px)
            anchor = max(anchor, axes_bbox.x0 + width_px + margin_px)
            if anchor - width_px < axes_bbox.x0 + margin_px - 1e-6:
                return None, float("inf"), "left_margin_overflow"
        else:
            anchor = max(curve_px[0] + offset_px, axes_bbox.x0 + margin_px)
            anchor = min(anchor, axes_bbox.x1 - width_px - margin_px)
            if anchor + width_px > axes_bbox.x1 - margin_px + 1e-6:
                return None, float("inf"), "right_margin_overflow"
        desired_y.append(float(curve_px[1]))
        widths.append(width_px)
        heights.append(height_px)
        anchor_x.append(float(anchor))
        curve_anchor_x.append(float(curve_px[0]))
        labels.append(label_text)
        text_colors.append(color)

    centers = _spread_label_centers(
        np.asarray(desired_y, dtype=float),
        np.asarray(heights, dtype=float),
        lower=float(axes_bbox.y0 + margin_px),
        upper=float(axes_bbox.y1 - margin_px),
        gap_px=gap_px,
    )
    if centers is None:
        return None, float("inf"), "vertical_spread_failed"

    inverse = ax.transData.inverted()
    planned_labels: list[tuple[float, float, str, object]] = []
    horizontal_offset = 0.0
    for anchor_value, curve_value in zip(anchor_x, curve_anchor_x, strict=True):
        horizontal_offset += abs(anchor_value - curve_value)
    vertical_adjustment = float(np.mean(np.abs(np.asarray(desired_y, dtype=float) - centers)))
    for x_px, y_px, label_text, color in zip(anchor_x, centers, labels, text_colors, strict=True):
        data_x, data_y = inverse.transform((x_px, y_px))
        planned_labels.append(
            (
                float(data_x),
                float(data_y),
                label_text,
                color,
            )
        )
    score = horizontal_offset / max(len(planned_labels), 1) + vertical_adjustment * 0.45
    reason = (
        f"endpoint plan side={side}; horizontal_offset={horizontal_offset:.3f}; "
        f"vertical_adjustment={vertical_adjustment:.3f}"
    )
    return planned_labels, score, reason

def _apply_endpoint_direct_label_plan(
    ax: plt.Axes,
    *,
    planned_labels: list[tuple[float, float, str, object]],
    side: str,
    fontsize: float,
) -> None:
    alignment = "right" if side == "left" else "left"
    for x_pos, y_pos, label_text, color in planned_labels:
        ax.text(
            x_pos,
            y_pos,
            label_text,
            ha=alignment,
            va="center",
            color=color,
            fontsize=fontsize,
            clip_on=True,
            zorder=4.5,
        )

def _ensure_direct_labels(
    ax: plt.Axes,
    series_list,
    *,
    options: RenderOptions,
    reverse_x: bool,
    side: str,
    fontsize: float = 6.0,
) -> bool:
    existing = [text for text in ax.texts if text.get_visible() and str(text.get_text()).strip()]
    if len(existing) == len(series_list):
        return True
    for text in tuple(ax.texts):
        text.remove()
    profile = _compact_curve_editorial_profile()
    dense_direct_labels = len(series_list) > int(profile.legend_max_series)
    if dense_direct_labels:
        fontsize = min(fontsize, float(qa_profile("curve").get("direct_label_dense_font_size_pt", fontsize)))
    colors = _series_display_colors(ax, len(series_list))
    if not dense_direct_labels and _place_series_edge_labels(
        ax,
        series_list,
        colors,
        reverse_x=reverse_x,
        side=side,
        inset_fraction=profile.direct_label_inset_fraction,
        label_offset_pt=profile.direct_label_offset_pt,
        search_band_fraction=profile.direct_label_search_band_fraction,
        fontsize=fontsize,
    ):
        return True
    if not _is_compact_curve_panel(options):
        record_layout_decision(
            ax.figure,
            empty_layout_decision("endpoint_direct_labels", reason="not_compact_panel"),
            context={"path": "render_direct_labels", "phase": "fallback_gate"},
        )
        return False
    side_candidates = [side] if side in {"left", "right"} else ["right", "left"]
    if len(side_candidates) == 1:
        alternate = "right" if side_candidates[0] == "left" else "left"
        side_candidates.append(alternate)

    plan_cache: dict[str, tuple[list[tuple[float, float, str, object]] | None, float, str]] = {}
    candidates = [
        LayoutCandidate(
            candidate_id=f"endpoint_{candidate_side}",
            payload={"side": candidate_side, "bias": 0.0 if candidate_side == side_candidates[0] else 22.0},
            standoff_pt=float(profile.direct_label_offset_pt),
            notes="endpoint direct-label fallback candidate",
        )
        for candidate_side in side_candidates
    ]

    def _score(candidate: LayoutCandidate) -> LayoutScore:
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        candidate_side = str(payload.get("side", side_candidates[0]))
        bias = float(payload.get("bias", 0.0))
        plan, plan_score, reason = _plan_endpoint_direct_labels(
            ax,
            series_list,
            reverse_x=reverse_x,
            side=candidate_side,
            inset_fraction=profile.direct_label_inset_fraction,
            label_offset_pt=profile.direct_label_offset_pt,
            fontsize=fontsize,
        )
        plan_cache[candidate.candidate_id] = (plan, plan_score, reason)
        if plan is None:
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason=reason)
        return LayoutScore(
            score=float(plan_score + bias),
            blocked=False,
            reason=f"{reason}; bias={bias:.3f}",
        )

    decision = choose_layout_candidate(
        object_kind="endpoint_direct_labels",
        candidates=candidates,
        score_hook=_score,
    )
    chosen = decision.chosen_candidate
    if chosen is None:
        record_layout_decision(
            ax.figure,
            flag_margin_fallback(
                decision,
                action="endpoint_labels_unavailable",
                reason="both sides failed compact endpoint fallback",
            ),
            context={"path": "render_direct_labels", "phase": "endpoint_policy"},
        )
        return False
    chosen_plan, _chosen_score, chosen_reason = plan_cache.get(
        chosen.candidate_id,
        (None, float("inf"), "missing_plan"),
    )
    if chosen_plan is None:
        record_layout_decision(
            ax.figure,
            flag_margin_fallback(
                decision,
                action="endpoint_labels_missing_plan",
                reason=chosen_reason,
            ),
            context={"path": "render_direct_labels", "phase": "endpoint_policy"},
        )
        return False

    chosen_payload = chosen.payload if isinstance(chosen.payload, dict) else {}
    chosen_side = str(chosen_payload.get("side", side_candidates[0]))
    if chosen_side != side_candidates[0]:
        decision = flag_margin_fallback(
            decision,
            action=f"switch_side:{chosen_side}",
            reason=f"preferred side '{side_candidates[0]}' failed endpoint plan",
        )
    record_layout_decision(
        ax.figure,
        decision,
        context={"path": "render_direct_labels", "phase": "endpoint_policy"},
    )
    _apply_endpoint_direct_label_plan(
        ax,
        planned_labels=chosen_plan,
        side=chosen_side,
        fontsize=fontsize,
    )
    return True

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

def _apply_compact_inside_legend(
    ax: plt.Axes,
    *,
    series_count: int,
    preserve_stress_label: bool = False,
) -> bool:
    if series_count < 2:
        record_layout_decision(
            ax.figure,
            empty_layout_decision("compact_legend", reason="series_count<2"),
            context={"path": "render_compact_legend", "phase": "candidate_selection"},
        )
        return False
    handles, labels = ax.get_legend_handles_labels()
    visible_labels = [label for label in labels if not str(label).startswith("_")]
    if len(visible_labels) < 2:
        record_layout_decision(
            ax.figure,
            empty_layout_decision("compact_legend", reason="insufficient_visible_labels"),
            context={"path": "render_compact_legend", "phase": "candidate_selection"},
        )
        return False
    profile = _compact_curve_editorial_profile()
    inset = plot_style.current_spacing().legend_inset_fraction
    candidates = legend_layout_candidates(
        preserve_stress_label=preserve_stress_label,
        compact=True,
        inset_fraction=inset,
    )
    data_points = _collect_axis_display_points(ax)

    def _score(candidate: LayoutCandidate) -> LayoutScore:
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        anchor = candidate.anchor if candidate.anchor is not None else (0.5, 1.0 - inset)
        legend = ax.legend(
            handles,
            labels,
            loc=str(payload.get("loc", "upper center")),
            bbox_to_anchor=anchor,
            bbox_transform=ax.transAxes,
            borderaxespad=0.0,
            alignment=str(payload.get("alignment", "center")),
            frameon=False,
            ncol=min(profile.legend_columns, len(visible_labels)),
            fontsize=plot_style.current_typography().legend_font_size_pt * profile.legend_font_scale,
            handlelength=profile.legend_handlelength,
            handletextpad=profile.legend_handletextpad,
            columnspacing=profile.legend_columnspacing,
            labelspacing=0.25,
            borderpad=profile.legend_borderpad,
        )
        ax.figure.canvas.draw()
        renderer = ax.figure.canvas.get_renderer()
        axes_bbox = ax.get_window_extent(renderer=renderer)
        legend_bbox = legend.get_window_extent(renderer=renderer)
        legend.remove()
        if (
            legend_bbox.x0 < axes_bbox.x0
            or legend_bbox.x1 > axes_bbox.x1
            or legend_bbox.y0 < axes_bbox.y0
            or legend_bbox.y1 > axes_bbox.y1
        ):
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="legend_out_of_axes")
        overlap_metrics = score_points_against_bbox(
            data_points,
            legend_bbox,
            inside_weight=12.0,
            near_radius=11.0,
            near_weight=1.0,
            normalize_near=True,
        )
        axes_area = max(float(axes_bbox.width) * float(axes_bbox.height), 1.0)
        legend_area = max(float(legend_bbox.width) * float(legend_bbox.height), 0.0)
        footprint = legend_area / axes_area
        bias = float(payload.get("bias", 0.0))
        score = overlap_metrics.total + footprint * 40.0 + bias
        return LayoutScore(
            score=score,
            blocked=False,
            reason=(
                f"compact overlap={overlap_metrics.total:.4f}; footprint={footprint:.4f}; "
                f"bias={bias:.3f}"
            ),
        )

    decision = choose_layout_candidate(
        object_kind="compact_legend",
        candidates=candidates,
        score_hook=_score,
    )
    chosen = decision.chosen_candidate
    if chosen is None:
        record_layout_decision(
            ax.figure,
            flag_margin_fallback(
                decision,
                action="compact_legend_rejected",
                reason="no in-axes compact legend candidate remained viable",
            ),
            context={"path": "render_compact_legend", "phase": "candidate_selection"},
        )
        return False
    chosen_payload = chosen.payload if isinstance(chosen.payload, dict) else {}
    chosen_anchor = chosen.anchor if chosen.anchor is not None else (0.5, 1.0 - inset)
    ax.legend(
        handles,
        labels,
        loc=str(chosen_payload.get("loc", "upper center")),
        bbox_to_anchor=chosen_anchor,
        bbox_transform=ax.transAxes,
        borderaxespad=0.0,
        alignment=str(chosen_payload.get("alignment", "center")),
        frameon=False,
        ncol=min(profile.legend_columns, len(visible_labels)),
        fontsize=plot_style.current_typography().legend_font_size_pt * profile.legend_font_scale,
        handlelength=profile.legend_handlelength,
        handletextpad=profile.legend_handletextpad,
        columnspacing=profile.legend_columnspacing,
        labelspacing=0.25,
        borderpad=profile.legend_borderpad,
    )
    if chosen.candidate_id != "upper_center":
        decision = flag_margin_fallback(
            decision,
            action=f"compact_anchor:{chosen.candidate_id}",
            reason="primary compact anchor downgraded by collision/footprint score",
        )
    record_layout_decision(
        ax.figure,
        decision,
        context={"path": "render_compact_legend", "phase": "candidate_selection"},
    )
    ax.figure.canvas.draw()
    renderer = ax.figure.canvas.get_renderer()
    axes_bbox = ax.get_window_extent(renderer=renderer)
    legend = ax.get_legend()
    if legend is None:
        return False
    legend_bbox = legend.get_window_extent(renderer=renderer)
    if (
        legend_bbox.x0 < axes_bbox.x0
        or legend_bbox.x1 > axes_bbox.x1
        or legend_bbox.y0 < axes_bbox.y0
        or legend_bbox.y1 > axes_bbox.y1
    ):
        legend.remove()
        record_layout_decision(
            ax.figure,
            empty_layout_decision("compact_legend", reason="post_apply_bbox_validation_failed"),
            context={"path": "render_compact_legend", "phase": "post_validation"},
        )
        return False
    return True
