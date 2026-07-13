from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import transforms
from src.plot_contract import load_plot_contract, qa_profile, validation_rule
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
    layout_summary: Mapping[str, Any] | None = None,
) -> QAReport:
    penalty = sum(_issue_penalty(issue.severity) for issue in issues)
    score = max(0.0, min(100.0, 100.0 - penalty))
    summary = dict(layout_summary or {})
    summary.setdefault("issue_ids", tuple(issue.id for issue in issues))
    summary.setdefault("needs_ai_intervention", any(issue.severity == "critical" for issue in issues))
    return QAReport(
        score=round(score, 1),
        grade=_grade_for_score(score),
        issues=tuple(issues),
        autofixes_applied=tuple(dict.fromkeys(str(item) for item in autofixes_applied if item)),
        layout_summary=summary,
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


def _outside_bbox_px(inner: transforms.Bbox, outer: transforms.Bbox) -> float:
    return max(
        outer.x0 - inner.x0,
        inner.x1 - outer.x1,
        outer.y0 - inner.y0,
        inner.y1 - outer.y1,
        0.0,
    )


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


def _visible_tick_values(axis) -> tuple[float, ...]:
    values: list[float] = []
    for tick in axis.get_major_ticks():
        label = tick.label1
        if label.get_visible() and str(label.get_text()).strip():
            value = float(tick.get_loc())
            if np.isfinite(value):
                values.append(value)
    return tuple(values)


def _line_width_values(ax: plt.Axes) -> tuple[float, ...]:
    values: list[float] = [
        float(line.get_linewidth())
        for line in ax.lines
        if line.get_visible() and float(line.get_linewidth()) > 0.0
    ]
    for collection in ax.collections:
        if not collection.get_visible():
            continue
        with np.errstate(all="ignore"):
            widths = np.asarray(collection.get_linewidths(), dtype=float)
        values.extend(float(value) for value in widths if np.isfinite(value) and value > 0.0)
    return tuple(values)


def _stroke_summary(ax: plt.Axes) -> dict[str, Any]:
    line_widths = _line_width_values(ax)
    tick_width = max(
        _axis_actual_tick_width(ax.xaxis, fallback=float(plt.rcParams["xtick.major.width"])),
        _axis_actual_tick_width(ax.yaxis, fallback=float(plt.rcParams["ytick.major.width"])),
        1e-6,
    )
    if not line_widths:
        return {
            "line_count": 0,
            "line_width_min_pt": None,
            "line_width_mean_pt": None,
            "line_width_max_pt": None,
            "tick_width_pt": round(float(tick_width), 3),
            "line_to_tick_ratio": None,
        }
    return {
        "line_count": len(line_widths),
        "line_width_min_pt": round(float(np.min(line_widths)), 3),
        "line_width_mean_pt": round(float(np.mean(line_widths)), 3),
        "line_width_max_pt": round(float(np.max(line_widths)), 3),
        "tick_width_pt": round(float(tick_width), 3),
        "line_to_tick_ratio": round(float(np.mean(line_widths) / max(tick_width, 1e-6)), 3),
    }


def _display_data_points(ax: plt.Axes) -> np.ndarray:
    point_blocks: list[np.ndarray] = []
    for line in ax.lines:
        if not line.get_visible():
            continue
        x_values = np.asarray(line.get_xdata(), dtype=float)
        y_values = np.asarray(line.get_ydata(), dtype=float)
        valid = np.isfinite(x_values) & np.isfinite(y_values)
        if np.any(valid):
            point_blocks.append(ax.transData.transform(np.column_stack([x_values[valid], y_values[valid]])))
    for collection in ax.collections:
        if not collection.get_visible():
            continue
        try:
            offsets = np.asarray(collection.get_offsets(), dtype=float)
        except (AttributeError, TypeError, ValueError):
            continue
        if offsets.ndim == 2 and offsets.shape[1] >= 2:
            valid = np.isfinite(offsets[:, 0]) & np.isfinite(offsets[:, 1])
            if np.any(valid):
                point_blocks.append(ax.transData.transform(offsets[valid, :2]))
    if not point_blocks:
        return np.empty((0, 2), dtype=float)
    return np.vstack(point_blocks)


def _data_occupancy_summary(ax: plt.Axes, renderer) -> dict[str, Any]:
    axes_bbox = ax.get_window_extent(renderer=renderer)
    points = _display_data_points(ax)
    if points.size == 0:
        return {
            "has_data": False,
            "vertical_occupancy": None,
            "horizontal_occupancy": None,
            "top_blank_fraction": None,
            "bottom_blank_fraction": None,
            "left_blank_fraction": None,
            "right_blank_fraction": None,
            "data_bbox_px": None,
        }
    inside = (
        (points[:, 0] >= axes_bbox.x0)
        & (points[:, 0] <= axes_bbox.x1)
        & (points[:, 1] >= axes_bbox.y0)
        & (points[:, 1] <= axes_bbox.y1)
    )
    clipped = points[inside]
    if clipped.size == 0:
        return {
            "has_data": False,
            "vertical_occupancy": 0.0,
            "horizontal_occupancy": 0.0,
            "top_blank_fraction": 1.0,
            "bottom_blank_fraction": 1.0,
            "left_blank_fraction": 1.0,
            "right_blank_fraction": 1.0,
            "data_bbox_px": None,
        }
    x0 = float(np.min(clipped[:, 0]))
    x1 = float(np.max(clipped[:, 0]))
    y0 = float(np.min(clipped[:, 1]))
    y1 = float(np.max(clipped[:, 1]))
    width = max(float(axes_bbox.width), 1.0)
    height = max(float(axes_bbox.height), 1.0)
    return {
        "has_data": True,
        "vertical_occupancy": round(float((y1 - y0) / height), 4),
        "horizontal_occupancy": round(float((x1 - x0) / width), 4),
        "top_blank_fraction": round(float((axes_bbox.y1 - y1) / height), 4),
        "bottom_blank_fraction": round(float((y0 - axes_bbox.y0) / height), 4),
        "left_blank_fraction": round(float((x0 - axes_bbox.x0) / width), 4),
        "right_blank_fraction": round(float((axes_bbox.x1 - x1) / width), 4),
        "data_bbox_px": [
            round(x0, 3),
            round(y0, 3),
            round(x1, 3),
            round(y1, 3),
        ],
    }


def _axis_layout_summary(fig: plt.Figure, ax: plt.Axes, renderer) -> dict[str, Any]:
    legend = ax.get_legend()
    axes_bbox = ax.get_window_extent(renderer=renderer)
    figure_bbox = fig.bbox
    legend_summary: dict[str, Any] = {"present": legend is not None}
    if legend is not None:
        legend_bbox = legend.get_window_extent(renderer=renderer)
        legend_area_ratio = _bbox_area(legend_bbox) / max(_bbox_area(axes_bbox), 1.0)
        legend_summary.update(
            {
                "bbox_px": [
                    round(float(legend_bbox.x0), 3),
                    round(float(legend_bbox.y0), 3),
                    round(float(legend_bbox.x1), 3),
                    round(float(legend_bbox.y1), 3),
                ],
                "labels": tuple(text.get_text() for text in legend.get_texts()),
                "area_ratio": round(float(legend_area_ratio), 4),
                "outside_figure": bool(_outside_bbox_px(legend_bbox, figure_bbox) > 1.0),
                "outside_figure_px": round(float(_outside_bbox_px(legend_bbox, figure_bbox)), 3),
            }
        )
    return {
        "x_label": ax.get_xlabel(),
        "y_label": ax.get_ylabel(),
        "x_bounds": tuple(round(float(value), 9) for value in ax.get_xlim()),
        "y_bounds": tuple(round(float(value), 9) for value in ax.get_ylim()),
        "x_scale": ax.get_xscale(),
        "y_scale": ax.get_yscale(),
        "x_inverted": bool(ax.xaxis_inverted()),
        "y_inverted": bool(ax.yaxis_inverted()),
        "x_ticks": tuple(round(float(value), 9) for value in _visible_tick_values(ax.xaxis)),
        "y_ticks": tuple(round(float(value), 9) for value in _visible_tick_values(ax.yaxis)),
        "x_tick_count": len(_visible_tick_values(ax.xaxis)),
        "y_tick_count": len(_visible_tick_values(ax.yaxis)),
        "axes_area_ratio": round(float(_bbox_area(axes_bbox) / max(_bbox_area(figure_bbox), 1.0)), 4),
        "legend": legend_summary,
        "stroke": _stroke_summary(ax),
        "data_occupancy": _data_occupancy_summary(ax, renderer),
    }


def _base_layout_summary(
    fig: plt.Figure,
    *,
    template: str,
    options: RenderOptions,
    renderer,
) -> dict[str, Any]:
    axes = [_axis_layout_summary(fig, axis, renderer) for axis in fig.axes]
    summary: dict[str, Any] = {
        "template": template,
        "figure_size_mm": (
            round(float(fig.get_size_inches()[0] * 25.4), 3),
            round(float(fig.get_size_inches()[1] * 25.4), 3),
        ),
        "requested_size_mm": (round(float(options.width_mm), 3), round(float(options.height_mm), 3)),
        "axes": tuple(axes),
        "export_review_mode": "structured_qa_only",
    }
    stack_layout = getattr(fig, "_sciplot_stack_layout", None)
    if isinstance(stack_layout, Mapping):
        summary["stack_spacing"] = dict(stack_layout)
    layout_debug = getattr(fig, "_sciplot_layout_debug", None)
    if layout_debug:
        summary["layout_decisions"] = tuple(str(item) for item in layout_debug)
    return summary


def _line_points_inside_bbox(ax: plt.Axes, bbox: transforms.Bbox) -> int:
    count = 0
    for line in ax.lines:
        x_values = np.asarray(line.get_xdata(), dtype=float)
        y_values = np.asarray(line.get_ydata(), dtype=float)
        valid = np.isfinite(x_values) & np.isfinite(y_values)
        if not np.any(valid):
            continue
        points = ax.transData.transform(np.column_stack([x_values[valid], y_values[valid]]))
        inside = (
            (points[:, 0] >= bbox.x0)
            & (points[:, 0] <= bbox.x1)
            & (points[:, 1] >= bbox.y0)
            & (points[:, 1] <= bbox.y1)
        )
        count += int(np.count_nonzero(inside))
    return count


def _legend_overlap_metrics(ax: plt.Axes, renderer) -> dict[str, float | int]:
    legend = ax.get_legend()
    if legend is None:
        return {"line_points": 0, "text_bboxes": 0, "tick_bboxes": 0}
    legend_bbox = legend.get_window_extent(renderer=renderer)
    text_bboxes = [
        bbox
        for _, bbox in _text_bboxes(
            [ax.xaxis.label, ax.yaxis.label, *ax.texts],
            renderer,
        )
    ]
    tick_bboxes = [*_tick_label_bboxes(ax.xaxis, renderer), *_tick_label_bboxes(ax.yaxis, renderer)]
    return {
        "line_points": _line_points_inside_bbox(ax, legend_bbox),
        "text_bboxes": sum(1 for bbox in text_bboxes if legend_bbox.overlaps(bbox)),
        "tick_bboxes": sum(1 for bbox in tick_bboxes if legend_bbox.overlaps(bbox)),
    }


def _legend_profile_value(profile_name: str, key: str, default: float) -> float:
    profile = qa_profile(profile_name)
    curve_profile = qa_profile("curve")
    return float(profile.get(key, curve_profile.get(key, default)))


def _append_legend_geometry_issues(
    fig: plt.Figure,
    ax: plt.Axes,
    renderer,
    issues: list[QAIssue],
    *,
    profile_name: str,
) -> None:
    legend = ax.get_legend()
    if legend is None:
        return
    legend_bbox = legend.get_window_extent(renderer=renderer)
    axes_bbox = ax.get_window_extent(renderer=renderer)
    figure_bbox = fig.bbox
    legend_ratio = _bbox_area(legend_bbox) / max(_bbox_area(axes_bbox), 1.0)
    warn_ratio = _legend_profile_value(profile_name, "legend_area_ratio_warn", 0.055)
    fail_ratio = _legend_profile_value(profile_name, "legend_area_ratio_fail", 0.07)
    overlap_metrics = _legend_overlap_metrics(ax, renderer)
    line_tolerance = int(_legend_profile_value(profile_name, "legend_line_point_overlap_tolerance", 1.0))
    line_points = int(overlap_metrics["line_points"])
    has_content_overlap = (
        line_points > line_tolerance
        or int(overlap_metrics["text_bboxes"]) > 0
        or int(overlap_metrics["tick_bboxes"]) > 0
    )
    if legend_bbox.overlaps(axes_bbox) and has_content_overlap and legend_ratio >= warn_ratio:
        issues.append(
            QAIssue(
                id="legend_footprint",
                severity="critical" if legend_ratio >= fail_ratio else "warning",
                metric_value=round(legend_ratio, 4),
                target=warn_ratio,
                message="Legend footprint is too large for the current axis frame.",
            )
        )

    outside_px = _outside_bbox_px(legend_bbox, figure_bbox)
    tolerance_px = _legend_profile_value(profile_name, "legend_outside_tolerance_px", 1.0)
    if outside_px > tolerance_px:
        issues.append(
            QAIssue(
                id="legend_outside_bounds",
                severity="critical",
                metric_value=round(outside_px, 3),
                target=tolerance_px,
                message="Legend extends outside the rendered figure canvas.",
            )
        )

    axes_ratio = _bbox_area(axes_bbox) / max(_bbox_area(figure_bbox), 1.0)
    axes_warn = _legend_profile_value(profile_name, "axes_area_ratio_warn", 0.35)
    axes_fail = _legend_profile_value(profile_name, "axes_area_ratio_fail", 0.28)
    if axes_ratio < axes_warn:
        issues.append(
            QAIssue(
                id="legend_axes_too_small",
                severity="critical" if axes_ratio < axes_fail else "warning",
                metric_value=round(axes_ratio, 4),
                target=axes_warn,
                message="Legend layout leaves too little usable axis area for the curves.",
            )
        )


def _axis_has_wavenumber_label(ax: plt.Axes) -> bool:
    label = f"{ax.get_xlabel()}".casefold()
    return "wavenumber" in label or "cm" in label and ("-1" in label or "−1" in label or "^{-1}" in label)


def _append_tick_gate_issues(ax: plt.Axes, renderer, issues: list[QAIssue]) -> None:
    x_overlap = _overlap_count(_tick_label_bboxes(ax.xaxis, renderer), margin_px=1.0)
    y_overlap = _overlap_count(_tick_label_bboxes(ax.yaxis, renderer), margin_px=1.0)
    if x_overlap or y_overlap:
        issues.append(
            QAIssue(
                id="tick_label_overlap",
                severity="critical" if x_overlap + y_overlap > 2 else "warning",
                metric_value=float(x_overlap + y_overlap),
                target=0.0,
                message="Major tick labels overlap; use a sparser tick policy or edge-label mode.",
            )
        )

    if ax.get_xscale() == "log" and any(value <= 0.0 for value in ax.get_xticks() if np.isfinite(value)):
        issues.append(
            QAIssue(
                id="log_axis_nonpositive_tick",
                severity="critical",
                metric_value="x",
                target="positive_ticks",
                message="Log x-axis contains a non-positive major tick.",
            )
        )
    if ax.get_yscale() == "log" and any(value <= 0.0 for value in ax.get_yticks() if np.isfinite(value)):
        issues.append(
            QAIssue(
                id="log_axis_nonpositive_tick",
                severity="critical",
                metric_value="y",
                target="positive_ticks",
                message="Log y-axis contains a non-positive major tick.",
            )
        )


def _append_ftir_wavenumber_gate(ax: plt.Axes, issues: list[QAIssue]) -> None:
    if not _axis_has_wavenumber_label(ax):
        return
    x0, x1 = ax.get_xlim()
    bounds_ok = np.isclose(max(x0, x1), 4000.0, atol=1e-6) and np.isclose(min(x0, x1), 400.0, atol=1e-6)
    ticks = _visible_tick_values(ax.xaxis)
    endpoints_ok = any(np.isclose(value, 4000.0, atol=1e-6) for value in ticks) and any(
        np.isclose(value, 400.0, atol=1e-6) for value in ticks
    )
    if not (bounds_ok and endpoints_ok and ax.xaxis_inverted()):
        metric_value = (
            f"bounds={tuple(round(float(v), 3) for v in (x0, x1))}; "
            f"ticks={tuple(round(float(v), 3) for v in ticks)}"
        )
        issues.append(
            QAIssue(
                id="ftir_wavenumber_bounds_missing",
                severity="critical",
                metric_value=metric_value,
                target="4000->400 with endpoint ticks",
                message="FTIR/wavenumber axes must display 4000 to 400 cm^-1 with both endpoint ticks visible.",
            )
        )


def _append_legend_gate_issues(ax: plt.Axes, renderer, issues: list[QAIssue]) -> None:
    metrics = _legend_overlap_metrics(ax, renderer)
    line_tolerance = int(qa_profile("curve").get("legend_line_point_overlap_tolerance", 1))
    line_points = int(metrics["line_points"])
    total = (
        max(0, line_points - line_tolerance)
        + int(metrics["text_bboxes"])
        + int(metrics["tick_bboxes"])
    )
    if total:
        issues.append(
            QAIssue(
                id="legend_overlap",
                severity="critical",
                metric_value=float(total),
                target=0.0,
                message="Legend overlaps curve data, tick labels, axis labels, or inline labels.",
            )
        )


def _append_stroke_gate_issues(ax: plt.Axes, issues: list[QAIssue], *, profile_name: str) -> None:
    profile = qa_profile(profile_name)
    curve_profile = qa_profile("curve")
    stroke = _stroke_summary(ax)
    min_width = stroke.get("line_width_min_pt")
    max_width = stroke.get("line_width_max_pt")
    ratio = stroke.get("line_to_tick_ratio")
    if min_width is None or max_width is None:
        return

    min_allowed = float(profile.get("stroke_line_width_min_pt", curve_profile.get("stroke_line_width_min_pt", 1.0)))
    max_allowed = float(profile.get("stroke_line_width_max_pt", curve_profile.get("stroke_line_width_max_pt", 1.8)))
    if float(min_width) < min_allowed or float(max_width) > max_allowed:
        issues.append(
            QAIssue(
                id="stroke_weight_out_of_band",
                severity="warning",
                metric_value=f"min={min_width}; max={max_width}",
                target=f"{min_allowed}-{max_allowed}",
                message="Curve stroke weight is outside the publication-style contract.",
            )
        )

    if ratio is None:
        return
    min_ratio = float(profile.get("stroke_line_tick_ratio_min", curve_profile.get("stroke_line_tick_ratio_min", 0.95)))
    max_ratio = float(profile.get("stroke_line_tick_ratio_max", curve_profile.get("stroke_line_tick_ratio_max", 2.2)))
    if float(ratio) < min_ratio or float(ratio) > max_ratio:
        issues.append(
            QAIssue(
                id="line_tick_hierarchy",
                severity="warning",
                metric_value=round(float(ratio), 3),
                target=f"{min_ratio}-{max_ratio}",
                message="Curve lines and tick strokes do not have a readable visual hierarchy.",
            )
        )


def _append_stacked_blank_gate(ax: plt.Axes, renderer, issues: list[QAIssue], *, profile_name: str) -> None:
    profile = qa_profile(profile_name)
    occupancy = _data_occupancy_summary(ax, renderer)
    if not occupancy.get("has_data"):
        return
    top_blank = occupancy.get("top_blank_fraction")
    vertical = occupancy.get("vertical_occupancy")
    if top_blank is not None:
        warn_top = float(profile.get("top_blank_fraction_warn", 0.22))
        if float(top_blank) > warn_top:
            issues.append(
                QAIssue(
                    id="stacked_top_blank_excess",
                    severity="warning",
                    metric_value=round(float(top_blank), 4),
                    target=warn_top,
                    message="Stacked spectra leave too much unused space above the highest curve.",
                )
            )
    if vertical is not None:
        warn_vertical = float(profile.get("vertical_occupancy_warn", 0.55))
        if float(vertical) < warn_vertical:
            issues.append(
                QAIssue(
                    id="data_vertical_occupancy_low",
                    severity="warning",
                    metric_value=round(float(vertical), 4),
                    target=warn_vertical,
                    message="Curve data use too little of the vertical plotting area.",
                )
            )


def _append_stacked_spacing_gate(
    fig: plt.Figure,
    ax: plt.Axes,
    renderer,
    issues: list[QAIssue],
) -> None:
    stack_layout = getattr(fig, "_sciplot_stack_layout", None)
    if not isinstance(stack_layout, Mapping):
        return
    peak = float(stack_layout.get("peak_height") or 0.0)
    gap = float(stack_layout.get("gap") or 0.0)
    min_gap = float(stack_layout.get("min_gap") or 0.0)
    axes_bbox = ax.get_window_extent(renderer=renderer)
    peak_px = axes_bbox.height * peak / max(abs(float(np.diff(ax.get_ylim())[0])), np.finfo(float).eps)

    if stack_layout.get("spacing_mode") == "manual" and peak > 0 and gap < min_gap:
        issues.append(
            QAIssue(
                id="stack_curve_overlap",
                severity="critical",
                metric_value=round(gap / peak, 3),
                target=0.25,
                message="Manual stacked-curve spacing is tighter than the minimum readable gap.",
            )
        )
    if stack_layout.get("spacing_mode") == "manual" and peak > 0 and gap > 2.5 * peak:
        issues.append(
            QAIssue(
                id="stack_spacing_too_loose",
                severity="warning",
                metric_value=round(gap / peak, 3),
                target="<=2.5",
                message="Manual stacked-curve spacing leaves unusually large gaps.",
            )
        )
    if peak_px < 8.0:
        issues.append(
            QAIssue(
                id="stack_peak_too_small",
                severity="warning",
                metric_value=round(float(peak_px), 3),
                target=8.0,
                message=(
                    "Stacked-curve peaks are too short in pixel space; "
                    "increase physical height or split the figure."
                ),
            )
        )


def _stacked_text_clip_bbox(fig: plt.Figure, axis: plt.Axes, text: plt.Text, renderer):
    if not text.get_clip_on():
        return fig.bbox
    return axis.get_window_extent(renderer=renderer)


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
            options=options,
            autofixes_applied=autofixes_applied,
        )
    if template in {"stacked_curve", "segmented_stacked_curve"}:
        return _analyze_stacked_figure(
            fig,
            template=template,
            options=options,
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
    layout_summary = _base_layout_summary(fig, template=template, options=options, renderer=renderer)
    curve_profile = qa_profile("curve")
    issues: list[QAIssue] = []

    legend = ax.get_legend()
    line_labels = [line.get_label() for line in ax.lines if not str(line.get_label()).startswith("_")]
    series_count = len(line_labels)
    text_bboxes = _text_bboxes(ax.texts, renderer)
    label_collision_margin_px = float(curve_profile.get("label_collision_margin_px", 3.0))

    if legend is not None:
        _append_legend_geometry_issues(fig, ax, renderer, issues, profile_name="curve")
        _append_legend_gate_issues(ax, renderer, issues)

    _append_tick_gate_issues(ax, renderer, issues)
    _append_ftir_wavenumber_gate(ax, issues)

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

    _append_stroke_gate_issues(ax, issues, profile_name="curve")

    return _finalize_report(issues, autofixes_applied=autofixes_applied, layout_summary=layout_summary)


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
    layout_summary = _base_layout_summary(fig, template="heatmap", options=options, renderer=renderer)
    heatmap_profile = qa_profile("heatmap")
    issues: list[QAIssue] = []

    if len(fig.axes) > 1:
        cbar_ax = fig.axes[-1]
        cbar_frame_bbox = cbar_ax.get_window_extent(renderer=renderer)
        cbar_bbox = cbar_ax.get_tightbbox(renderer=renderer)
        contract = load_plot_contract()
        frame = contract.global_frame
        figure_width_mm = fig.get_size_inches()[0] * 25.4
        figure_height_mm = fig.get_size_inches()[1] * 25.4
        standard_frame_bbox = transforms.Bbox.from_extents(
            frame.left_margin_mm / figure_width_mm * fig.bbox.width,
            frame.bottom_margin_mm / figure_height_mm * fig.bbox.height,
            (1.0 - frame.right_margin_mm / figure_width_mm) * fig.bbox.width,
            (1.0 - frame.top_margin_mm / figure_height_mm) * fig.bbox.height,
        )
        outer_frame_bbox = transforms.Bbox.union([axes_bbox, cbar_frame_bbox])
        frame_tolerance_mm = float(validation_rule("heatmap_main_frame").tolerance_mm or 0.05)
        tolerance_x = frame_tolerance_mm / figure_width_mm * fig.bbox.width
        tolerance_y = frame_tolerance_mm / figure_height_mm * fig.bbox.height
        edge_errors = {
            "left": abs(outer_frame_bbox.x0 - standard_frame_bbox.x0),
            "right": abs(outer_frame_bbox.x1 - standard_frame_bbox.x1),
            "bottom": abs(outer_frame_bbox.y0 - standard_frame_bbox.y0),
            "top": abs(outer_frame_bbox.y1 - standard_frame_bbox.y1),
        }
        frame_aligned = (
            edge_errors["left"] <= tolerance_x
            and edge_errors["right"] <= tolerance_x
            and edge_errors["bottom"] <= tolerance_y
            and edge_errors["top"] <= tolerance_y
        )
        layout_summary["frame_alignment"] = {
            "mode": "standard_graph_envelope",
            "status": "aligned" if frame_aligned else "misaligned",
            "outside_legend_allowed": False,
            "edge_error_px": {key: round(value, 3) for key, value in edge_errors.items()},
            "tolerance_mm": frame_tolerance_mm,
        }
        if not frame_aligned:
            issues.append(
                QAIssue(
                    id="heatmap_outer_frame_misaligned",
                    severity="critical",
                    metric_value=round(max(edge_errors.values()), 3),
                    target=f"within {frame_tolerance_mm:g} mm",
                    message="The heatmap and colorbar union no longer matches the fixed publication frame.",
                )
            )

        figure_text_bboxes = [
            text.get_window_extent(renderer=renderer) for text in fig.texts if text.get_visible()
        ]
        colorbar_x_tick_bboxes = _tick_label_bboxes(cbar_ax.xaxis, renderer)
        colorbar_y_tick_bboxes = _tick_label_bboxes(cbar_ax.yaxis, renderer)
        auxiliary_text_bboxes = [*figure_text_bboxes, *colorbar_x_tick_bboxes, *colorbar_y_tick_bboxes]
        text_tolerance_mm = float(validation_rule("heatmap_colorbar_inside_canvas").tolerance_mm or 0.2)
        text_tolerance_x = text_tolerance_mm / figure_width_mm * fig.bbox.width
        text_tolerance_y = text_tolerance_mm / figure_height_mm * fig.bbox.height
        auxiliary_text_inside = all(
            bbox.x0 >= fig.bbox.x0 - text_tolerance_x
            and bbox.x1 <= fig.bbox.x1 + text_tolerance_x
            and bbox.y0 >= fig.bbox.y0 - text_tolerance_y
            and bbox.y1 <= fig.bbox.y1 + text_tolerance_y
            for bbox in auxiliary_text_bboxes
        )
        label_left_error = (
            abs(figure_text_bboxes[0].x0 - standard_frame_bbox.x0) if figure_text_bboxes else 0.0
        )
        right_tick_anchor_error = (
            abs((colorbar_x_tick_bboxes[-1].x0 + colorbar_x_tick_bboxes[-1].x1) / 2.0 - cbar_frame_bbox.x1)
            if colorbar_x_tick_bboxes
            else 0.0
        )
        auxiliary_text_anchored = label_left_error <= text_tolerance_x and right_tick_anchor_error <= text_tolerance_x
        auxiliary_text_aligned = auxiliary_text_inside and auxiliary_text_anchored
        layout_summary["auxiliary_text_alignment"] = {
            "envelope": "standard_text_safe_area",
            "status": "inside" if auxiliary_text_aligned else "outside",
            "tolerance_mm": text_tolerance_mm,
            "label_left_anchor_error_px": round(label_left_error, 3),
            "right_tick_anchor_error_px": round(right_tick_anchor_error, 3),
        }
        if not auxiliary_text_aligned:
            issues.append(
                QAIssue(
                    id="heatmap_auxiliary_text_outside_standard_frame",
                    severity="critical",
                    metric_value="outside",
                    target="standard_text_safe_area",
                    message="Colorbar text left the standard safe area or lost its aligned outer anchors.",
                )
            )

        width_ratio = cbar_frame_bbox.width / max(axes_bbox.width, 1.0)
        height_ratio = cbar_frame_bbox.height / max(fig.bbox.height, 1.0)
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
            min_gap = float(heatmap_profile.get("min_label_gap_px", 6.0))
            if str(heatmap_profile.get("frame_envelope_mode") or "") == "standard_graph":
                gap_px = float(cbar_frame_bbox.x0 - label_bbox.x1)
            else:
                gap_px = float(label_bbox.y0 - cbar_bbox.y1)
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

    return _finalize_report(issues, autofixes_applied=autofixes_applied, layout_summary=layout_summary)


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
    options: RenderOptions,
    autofixes_applied: Iterable[str],
) -> QAReport:
    renderer = _draw_renderer(fig)
    ax = fig.axes[0]
    layout_summary = _base_layout_summary(fig, template=template, options=options, renderer=renderer)
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

    return _finalize_report(issues, autofixes_applied=autofixes_applied, layout_summary=layout_summary)


def _analyze_stacked_figure(
    fig: plt.Figure,
    *,
    template: str,
    options: RenderOptions,
    autofixes_applied: Iterable[str],
) -> QAReport:
    renderer = _draw_renderer(fig)
    issues: list[QAIssue] = []
    layout_summary = _base_layout_summary(fig, template=template, options=options, renderer=renderer)
    stacked_profile = qa_profile("stacked")

    label_bboxes: list[transforms.Bbox] = []
    for axis in fig.axes:
        _append_legend_geometry_issues(fig, axis, renderer, issues, profile_name="stacked")
        _append_tick_gate_issues(axis, renderer, issues)
        _append_ftir_wavenumber_gate(axis, issues)
        _append_legend_gate_issues(axis, renderer, issues)
        _append_stacked_spacing_gate(fig, axis, renderer, issues)
        _append_stroke_gate_issues(axis, issues, profile_name="stacked")
        _append_stacked_blank_gate(axis, renderer, issues, profile_name="stacked")
        text_bboxes = _text_bboxes(axis.texts, renderer)
        label_bboxes.extend([bbox for _, bbox in text_bboxes])
        outside = _text_outside_count(
            text_bboxes,
            clip_bbox_provider=(
                lambda text, axis=axis: _stacked_text_clip_bbox(fig, axis, text, renderer)
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

    return _finalize_report(issues, autofixes_applied=autofixes_applied, layout_summary=layout_summary)
