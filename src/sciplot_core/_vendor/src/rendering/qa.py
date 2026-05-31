from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import transforms

from src.plot_contract import qa_profile
from src.rendering.models import QAIssue, QAReport, RenderOptions
from src.rendering.template_lifecycle import template_family_ids
from src.wide_nmr import WIDE_NMR_STRUCTURE_RESERVED_MM

_CURVE_QA_TEMPLATES = {
    "curve",
    "function_curve",
    "point_line",
    "area_curve",
    "step_line",
    "stacked_area",
    "scatter",
    "bubble_scatter",
    *template_family_ids("scatter_fit"),
    *template_family_ids("mean_band"),
}
_STATS_QA_TEMPLATES = {
    *template_family_ids("bar"),
    "box",
    "box_strip",
    "violin",
    "violin_box",
    "point_error",
    "lollipop_error",
    "histogram_density",
    "density_area",
}


@dataclass(frozen=True)
class CurveAutofix:
    marker_every: int | None = None
    marker_size_scale: float = 1.0
    tick_width_scale: float = 1.0
    tick_length_scale: float = 1.0
    line_width_scale: float = 1.0
    collection_size_scale: float = 1.0
    autofixes_applied: tuple[str, ...] = ()


def _draw_renderer(fig: plt.Figure):
    fig.canvas.draw()
    return fig.canvas.get_renderer()


def _grade_for_score(score: float) -> str:
    if score >= 90.0:
        return "excellent"
    if score >= 75.0:
        return "solid"
    return "needs_cleanup"


def _issue_penalty(severity: str) -> float:
    return {
        "info": 3.0,
        "warning": 8.0,
        "critical": 18.0,
    }.get(severity, 8.0)


def _finalize_report(
    issues: list[QAIssue],
    *,
    autofixes_applied: Iterable[str] = (),
) -> QAReport:
    penalty = sum(_issue_penalty(issue.severity) for issue in issues)
    score = max(0.0, min(100.0, 100.0 - penalty))
    return QAReport(
        score=round(score, 1),
        grade=_grade_for_score(score),
        issues=tuple(issues),
        autofixes_applied=tuple(dict.fromkeys(str(item) for item in autofixes_applied if item)),
    )


def _is_small_panel(options: RenderOptions, profile_name: str) -> bool:
    profile = qa_profile(profile_name)
    return bool(
        np.isclose(
            options.width_mm,
            float(profile.get("small_panel_width_mm", options.width_mm)),
            atol=0.05,
        )
        and np.isclose(
            options.height_mm,
            float(profile.get("small_panel_height_mm", options.height_mm)),
            atol=0.05,
        )
    )


def recommend_curve_autofix(
    *,
    total_points: int,
    has_markers: bool,
    has_scatter: bool,
) -> CurveAutofix:
    profile = qa_profile("curve")
    threshold = int(profile.get("dense_marker_point_threshold", 24))
    if total_points < threshold:
        return CurveAutofix()

    min_markevery = int(profile.get("dense_markevery_min", 2))
    max_markevery = int(profile.get("dense_markevery_max", 6))
    marker_scale = float(profile.get("dense_marker_scale", 0.88))
    tick_width_scale = float(profile.get("dense_tick_width_scale", 0.85))
    tick_length_scale = float(profile.get("dense_tick_length_scale", 0.9))
    line_width_scale = float(profile.get("dense_line_width_scale", 0.96))
    marker_every = max(min_markevery, min(max_markevery, int(np.ceil(total_points / threshold))))

    autofixes = ["dense_point_spacing"]
    if has_markers:
        autofixes.append("marker_size_reduced")
    if has_markers or has_scatter:
        autofixes.append("tick_stroke_deemphasized")

    return CurveAutofix(
        marker_every=marker_every if has_markers else None,
        marker_size_scale=marker_scale if has_markers else 1.0,
        tick_width_scale=tick_width_scale if has_markers or has_scatter else 1.0,
        tick_length_scale=tick_length_scale if has_markers or has_scatter else 1.0,
        line_width_scale=line_width_scale if has_markers else 1.0,
        collection_size_scale=marker_scale if has_scatter else 1.0,
        autofixes_applied=tuple(autofixes),
    )


def apply_curve_autofix(
    ax: plt.Axes,
    fix: CurveAutofix,
) -> tuple[str, ...]:
    applied = list(fix.autofixes_applied)
    if fix.tick_width_scale != 1.0 or fix.tick_length_scale != 1.0:
        for axis_name in ("x", "y"):
            major_length = (
                plt.rcParams["xtick.major.size"]
                if axis_name == "x"
                else plt.rcParams["ytick.major.size"]
            )
            minor_width = (
                plt.rcParams["xtick.minor.width"]
                if axis_name == "x"
                else plt.rcParams["ytick.minor.width"]
            )
            minor_length = (
                plt.rcParams["xtick.minor.size"]
                if axis_name == "x"
                else plt.rcParams["ytick.minor.size"]
            )
            ax.tick_params(
                axis=axis_name,
                which="major",
                width=ax.xaxis.get_ticklines()[0].get_markeredgewidth() * fix.tick_width_scale
                if ax.xaxis.get_ticklines()
                else None,
                length=major_length * fix.tick_length_scale,
            )
            ax.tick_params(
                axis=axis_name,
                which="minor",
                width=minor_width * fix.tick_width_scale,
                length=minor_length * fix.tick_length_scale,
            )
    for line in ax.lines:
        if fix.line_width_scale != 1.0:
            line.set_linewidth(float(line.get_linewidth()) * fix.line_width_scale)
        if fix.marker_every is not None and line.get_marker() not in {None, "", "None", " "}:
            line.set_markevery(fix.marker_every)
            line.set_markersize(float(line.get_markersize()) * fix.marker_size_scale)
    for collection in ax.collections:
        sizes = np.asarray(collection.get_sizes(), dtype=float)
        if sizes.size and fix.collection_size_scale != 1.0:
            collection.set_sizes(sizes * (fix.collection_size_scale**2))
    return tuple(applied)


def _bbox_area(bbox: transforms.Bbox) -> float:
    return max(float(bbox.width), 0.0) * max(float(bbox.height), 0.0)


def _text_bboxes(
    texts: Sequence[plt.Text],
    renderer,
) -> list[tuple[plt.Text, transforms.Bbox]]:
    bboxes: list[tuple[plt.Text, transforms.Bbox]] = []
    for text in texts:
        if not text.get_visible() or not str(text.get_text()).strip():
            continue
        bboxes.append((text, text.get_window_extent(renderer=renderer)))
    return bboxes


def _overlap_count(bboxes: Sequence[transforms.Bbox], *, margin_px: float = 0.0) -> int:
    count = 0
    expanded = [
        bbox.expanded(
            1.0 + margin_px / max(bbox.width, 1.0),
            1.0 + margin_px / max(bbox.height, 1.0),
        )
        for bbox in bboxes
    ]
    for idx, bbox in enumerate(expanded):
        for other in expanded[idx + 1 :]:
            if bbox.overlaps(other):
                count += 1
    return count


def _tick_label_bboxes(axis, renderer) -> list[transforms.Bbox]:
    return [
        tick.label1.get_window_extent(renderer=renderer)
        for tick in axis.get_major_ticks()
        if tick.label1.get_visible() and tick.label1.get_text().strip()
    ]


def _axis_actual_tick_width(axis, *, fallback: float) -> float:
    widths = [
        float(line.get_markeredgewidth())
        for line in axis.get_ticklines()
        if line.get_visible() and float(line.get_markeredgewidth()) > 0.0
    ]
    if widths:
        return max(widths)
    return fallback


def _text_outside_count(
    text_bboxes: Sequence[tuple[plt.Text, transforms.Bbox]],
    *,
    clip_bbox_provider,
) -> int:
    count = 0
    for text, bbox in text_bboxes:
        clip_bbox = clip_bbox_provider(text)
        if clip_bbox is None:
            continue
        if (
            bbox.x0 < clip_bbox.x0
            or bbox.x1 > clip_bbox.x1
            or bbox.y0 < clip_bbox.y0
            or bbox.y1 > clip_bbox.y1
        ):
            count += 1
    return count


def analyze_rendered_figure(
    fig: plt.Figure,
    *,
    template: str,
    options: RenderOptions,
    palette_preset: str,
    autofixes_applied: Iterable[str] = (),
) -> QAReport:
    if template in _CURVE_QA_TEMPLATES:
        return _analyze_curve_figure(
            fig,
            template=template,
            options=options,
            autofixes_applied=autofixes_applied,
        )
    if template in {"heatmap", "annotated_heatmap"}:
        return _analyze_heatmap_figure(
            fig,
            options=options,
            palette_preset=palette_preset,
            autofixes_applied=autofixes_applied,
        )
    if template in _STATS_QA_TEMPLATES:
        return _analyze_stats_figure(
            fig,
            template=template,
            autofixes_applied=autofixes_applied,
        )
    if template in {"stacked_curve", "segmented_stacked_curve"}:
        return _analyze_stacked_figure(
            fig,
            template=template,
            autofixes_applied=autofixes_applied,
        )
    return _finalize_report([], autofixes_applied=autofixes_applied)


def _analyze_curve_figure(
    fig: plt.Figure,
    *,
    template: str,
    options: RenderOptions,
    autofixes_applied: Iterable[str],
) -> QAReport:
    renderer = _draw_renderer(fig)
    ax = fig.axes[0]
    axes_bbox = ax.get_window_extent(renderer=renderer)
    curve_profile = qa_profile("curve")
    issues: list[QAIssue] = []

    legend = ax.get_legend()
    line_labels = [line.get_label() for line in ax.lines if not str(line.get_label()).startswith("_")]
    series_count = len(line_labels)
    text_bboxes = _text_bboxes(ax.texts, renderer)
    label_collision_margin_px = float(curve_profile.get("label_collision_margin_px", 3.0))

    if legend is not None:
        legend_bbox = legend.get_window_extent(renderer=renderer)
        legend_ratio = _bbox_area(legend_bbox) / max(_bbox_area(axes_bbox), 1.0)
        warn_ratio = float(curve_profile.get("legend_area_ratio_warn", 0.055))
        fail_ratio = float(curve_profile.get("legend_area_ratio_fail", 0.07))
        if legend_ratio >= warn_ratio:
            issues.append(
                QAIssue(
                    id="legend_footprint",
                    severity="critical" if legend_ratio >= fail_ratio else "warning",
                    metric_value=round(legend_ratio, 4),
                    target=warn_ratio,
                    message="Legend footprint is too large for the current axis frame.",
                )
            )

    if series_count > 1 and legend is None and len(text_bboxes) < series_count:
        issues.append(
            QAIssue(
                id="series_identification",
                severity="critical",
                metric_value=len(text_bboxes),
                target=series_count,
                message="Series labels are incomplete after legend removal.",
            )
        )

    label_overlap_count = _overlap_count(
        [bbox for _, bbox in text_bboxes],
        margin_px=label_collision_margin_px,
    )
    if label_overlap_count:
        issues.append(
            QAIssue(
                id="label_collision",
                severity="critical" if label_overlap_count > 1 else "warning",
                metric_value=float(label_overlap_count),
                target=0.0,
                message="Direct labels are colliding inside the plot area.",
            )
        )

    out_of_bounds = _text_outside_count(
        text_bboxes,
        clip_bbox_provider=(
            lambda text: text.axes.get_window_extent(renderer=renderer) if text.axes else None
        ),
    )
    if out_of_bounds:
        issues.append(
            QAIssue(
                id="label_out_of_bounds",
                severity="critical",
                metric_value=float(out_of_bounds),
                target=0.0,
                message="At least one direct label extends outside the plotting axes.",
            )
        )

    if ax.lines:
        line_width = float(np.mean([line.get_linewidth() for line in ax.lines]))
        tick_width = max(
            _axis_actual_tick_width(ax.xaxis, fallback=float(plt.rcParams["xtick.major.width"])),
            _axis_actual_tick_width(ax.yaxis, fallback=float(plt.rcParams["ytick.major.width"])),
            1e-6,
        )
        hierarchy = max(line_width - tick_width, 0.0) / max(line_width, 1e-6)
        target = float(curve_profile.get("stroke_hierarchy_target", 0.3))
        if hierarchy < target and _is_small_panel(options, "curve"):
            issues.append(
                QAIssue(
                    id="stroke_hierarchy",
                    severity="warning",
                    metric_value=round(hierarchy, 3),
                    target=target,
                    message="Line and tick hierarchy is too close for a compact panel.",
                )
            )

    return _finalize_report(issues, autofixes_applied=autofixes_applied)


def _analyze_heatmap_figure(
    fig: plt.Figure,
    *,
    options: RenderOptions,
    palette_preset: str,
    autofixes_applied: Iterable[str],
) -> QAReport:
    renderer = _draw_renderer(fig)
    ax = fig.axes[0]
    axes_bbox = ax.get_window_extent(renderer=renderer)
    heatmap_profile = qa_profile("heatmap")
    issues: list[QAIssue] = []

    if len(fig.axes) > 1:
        cbar_ax = fig.axes[-1]
        cbar_bbox = cbar_ax.get_tightbbox(renderer=renderer)
        width_ratio = cbar_bbox.width / max(axes_bbox.width, 1.0)
        height_ratio = cbar_bbox.height / max(fig.bbox.height, 1.0)
        if width_ratio < 0.48 or width_ratio > 0.68:
            issues.append(
                QAIssue(
                    id="colorbar_length",
                    severity="warning",
                    metric_value=round(width_ratio, 3),
                    target="0.48-0.68",
                    message="Colorbar length has drifted away from the editorial target strip width.",
                )
            )
        if height_ratio > 0.075:
            issues.append(
                QAIssue(
                    id="colorbar_thickness",
                    severity="warning",
                    metric_value=round(height_ratio, 3),
                    target=0.075,
                    message="Colorbar strip is visually too thick for a small heatmap panel.",
                )
            )
        if fig.texts:
            label_bbox = fig.texts[0].get_window_extent(renderer=renderer)
            gap_px = float(label_bbox.y0 - cbar_bbox.y1)
            min_gap = float(heatmap_profile.get("min_label_gap_px", 6.0))
            if gap_px < min_gap:
                issues.append(
                    QAIssue(
                        id="colorbar_label_gap",
                        severity="warning",
                        metric_value=round(gap_px, 3),
                        target=min_gap,
                        message="Colorbar header and strip are too tightly stacked.",
                    )
                )

    x_tick_overlap = _overlap_count(_tick_label_bboxes(ax.xaxis, renderer), margin_px=1.0)
    y_tick_overlap = _overlap_count(_tick_label_bboxes(ax.yaxis, renderer), margin_px=1.0)
    if x_tick_overlap or y_tick_overlap:
        issues.append(
            QAIssue(
                id="axis_label_crowding",
                severity="warning",
                metric_value=float(x_tick_overlap + y_tick_overlap),
                target=0.0,
                message="Row or column labels are crowding the heatmap frame.",
            )
        )

    safe_palettes = {str(item) for item in heatmap_profile.get("safe_sequential_palettes", ())}
    if safe_palettes and palette_preset not in safe_palettes:
        issues.append(
            QAIssue(
                id="palette_uniformity",
                severity="warning",
                metric_value=palette_preset,
                target="perceptually_uniform",
                message="Selected heatmap palette is not in the approved perceptual-uniform list.",
            )
        )

    return _finalize_report(issues, autofixes_applied=autofixes_applied)


def _bar_step_ratio(ax: plt.Axes) -> tuple[float | None, float | None]:
    patches = [patch for patch in ax.patches if patch.get_width() > 0]
    if len(patches) < 2:
        return None, None
    centers = np.array([patch.get_x() + patch.get_width() / 2.0 for patch in patches], dtype=float)
    widths = np.array([patch.get_width() for patch in patches], dtype=float)
    sorted_centers = np.sort(centers)
    steps = np.diff(sorted_centers)
    if steps.size == 0:
        return None, None
    return float(np.mean(widths)), float(np.median(steps))


def _average_cap_ratio(ax: plt.Axes) -> float | None:
    cap_widths: list[float] = []
    for line in ax.lines:
        x = np.asarray(line.get_xdata(), dtype=float)
        y = np.asarray(line.get_ydata(), dtype=float)
        if x.size == 2 and y.size == 2 and np.isclose(y[0], y[1]):
            cap_widths.append(float(abs(x[1] - x[0])))
    mean_bar_width, _ = _bar_step_ratio(ax)
    if not cap_widths or mean_bar_width is None or mean_bar_width <= 0:
        return None
    return float(np.mean(cap_widths) / mean_bar_width)


def _analyze_stats_figure(
    fig: plt.Figure,
    *,
    template: str,
    autofixes_applied: Iterable[str],
) -> QAReport:
    renderer = _draw_renderer(fig)
    ax = fig.axes[0]
    stats_profile = qa_profile("stats")
    issues: list[QAIssue] = []

    x_tick_overlap = _overlap_count(_tick_label_bboxes(ax.xaxis, renderer), margin_px=1.0)
    if x_tick_overlap:
        issues.append(
            QAIssue(
                id="category_crowding",
                severity="warning",
                metric_value=float(x_tick_overlap),
                target=0.0,
                message="Category labels are too crowded for a clean editorial stat plot.",
            )
        )

    visible_y_tick_count = sum(
        1
        for tick in ax.yaxis.get_major_ticks()
        if tick.label1.get_visible() and tick.label1.get_text().strip()
    )
    if visible_y_tick_count > 7:
        issues.append(
            QAIssue(
                id="y_tick_load",
                severity="warning",
                metric_value=float(visible_y_tick_count),
                target=7.0,
                message="Too many y-axis labels are visible for a compact stat plot.",
            )
        )

    if template == "bar":
        mean_width, step = _bar_step_ratio(ax)
        if mean_width is not None and step is not None and step > 0:
            ratio = mean_width / step
            warn_ratio = float(stats_profile.get("bar_width_ratio_warn", 0.34))
            fail_ratio = float(stats_profile.get("bar_width_ratio_fail", 0.42))
            if ratio > warn_ratio:
                issues.append(
                    QAIssue(
                        id="bar_spacing",
                        severity="critical" if ratio > fail_ratio else "warning",
                        metric_value=round(ratio, 3),
                        target=warn_ratio,
                        message="Bars are too wide relative to group spacing.",
                    )
                )
        cap_ratio = _average_cap_ratio(ax)
        target_cap_ratio = float(stats_profile.get("error_cap_ratio_target", 0.22))
        if cap_ratio is not None and abs(cap_ratio - target_cap_ratio) > 0.1:
            issues.append(
                QAIssue(
                    id="error_cap_ratio",
                    severity="warning",
                    metric_value=round(cap_ratio, 3),
                    target=target_cap_ratio,
                    message="Error-bar caps are not proportioned to the bar width.",
                )
            )
        raw_collections = [collection for collection in ax.collections if np.asarray(collection.get_offsets()).size]
        if not raw_collections:
            issues.append(
                QAIssue(
                    id="raw_point_overlay",
                    severity="warning",
                    metric_value=0.0,
                    target=1.0,
                    message="Bar plot is missing the editorial raw-point overlay.",
                )
            )

    return _finalize_report(issues, autofixes_applied=autofixes_applied)


def _analyze_stacked_figure(
    fig: plt.Figure,
    *,
    template: str,
    autofixes_applied: Iterable[str],
) -> QAReport:
    renderer = _draw_renderer(fig)
    issues: list[QAIssue] = []
    stacked_profile = qa_profile("stacked")

    label_bboxes: list[transforms.Bbox] = []
    for axis in fig.axes:
        text_bboxes = _text_bboxes(axis.texts, renderer)
        label_bboxes.extend([bbox for _, bbox in text_bboxes])
        outside = _text_outside_count(
            text_bboxes,
            clip_bbox_provider=(
                lambda text, axis=axis: axis.get_window_extent(renderer=renderer)
            ),
        )
        if outside:
            issues.append(
                QAIssue(
                    id="stacked_label_bounds",
                    severity="critical",
                    metric_value=float(outside),
                    target=0.0,
                    message="Stacked labels should remain inside their target axes.",
                )
            )

    overlap_count = _overlap_count(label_bboxes, margin_px=1.0)
    if overlap_count:
        issues.append(
            QAIssue(
                id="stacked_label_collision",
                severity="warning",
                metric_value=float(overlap_count),
                target=0.0,
                message="Stacked labels are starting to collide.",
            )
        )

    label_density_limit = float(stacked_profile.get("label_density_warn_per_axis", 5.0))
    if len(label_bboxes) > label_density_limit * max(len(fig.axes), 1):
        issues.append(
            QAIssue(
                id="stacked_label_density",
                severity="warning",
                metric_value=float(len(label_bboxes)),
                target=label_density_limit * max(len(fig.axes), 1),
                message="Stacked annotation density is climbing above the preferred editorial load.",
            )
        )

    if template == "segmented_stacked_curve" and fig.axes:
        height_mm = fig.get_size_inches()[1] * 25.4
        highest_axis = max(axis.get_position().y1 for axis in fig.axes)
        reserved_mm = (1.0 - highest_axis) * height_mm
        reserve_tolerance = float(stacked_profile.get("reserve_tolerance_mm", 1.0))
        if abs(reserved_mm - WIDE_NMR_STRUCTURE_RESERVED_MM) > reserve_tolerance:
            issues.append(
                QAIssue(
                    id="wide_nmr_reserve",
                    severity="warning",
                    metric_value=round(reserved_mm, 3),
                    target=WIDE_NMR_STRUCTURE_RESERVED_MM,
                    message="Wide NMR structure reserve space drifted away from the editorial target.",
                )
            )

    return _finalize_report(issues, autofixes_applied=autofixes_applied)
