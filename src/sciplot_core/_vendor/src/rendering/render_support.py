from __future__ import annotations

from dataclasses import dataclass

import matplotlib.pyplot as plt

from src.plot_contract import qa_profile
from src.rendering.models import QAReport, RenderedPlot, RenderOptions
from src.rendering.qa import analyze_rendered_figure


@dataclass(frozen=True)
class StatsRenderProfile:
    bar_width: float
    box_width: float
    violin_width: float
    spacing_scale: float
    show_raw_points: bool
    raw_point_size: float
    raw_point_alpha: float
    capsize: float

@dataclass(frozen=True)
class HeatmapEditorialLayout:
    colorbar_x_offset_fraction: float
    colorbar_width_fraction: float
    colorbar_y_offset_fraction: float
    colorbar_height_fraction: float
    colorbar_tick_count: int
    label_gap_pt: float

def _rendered_plot_with_qa(
    *,
    filename: str,
    figure: plt.Figure,
    template: str,
    options: RenderOptions,
    autofixes_applied: tuple[str, ...] = (),
) -> RenderedPlot:
    report = analyze_rendered_figure(
        figure,
        template=template,
        options=options,
        palette_preset=options.palette_preset,
        autofixes_applied=autofixes_applied,
    )
    if (
        _needs_stroke_autorepair(report)
        and not _has_manual_line_width(options)
        and _apply_stroke_autorepair(figure, template=template)
    ):
        autofixes_applied = (*autofixes_applied, "stroke_weight_autorepaired")
        report = analyze_rendered_figure(
            figure,
            template=template,
            options=options,
            palette_preset=options.palette_preset,
            autofixes_applied=autofixes_applied,
        )
    return RenderedPlot(
        filename=filename,
        figure=figure,
        qa_report=report,
    )


def _needs_stroke_autorepair(report: QAReport) -> bool:
    return any(issue.id in {"stroke_weight_out_of_band", "line_tick_hierarchy"} for issue in report.issues)


def _has_manual_line_width(options: RenderOptions) -> bool:
    if not options.series_styles:
        return False
    return any(item.get("line_width") is not None for item in options.series_styles)


def _tick_width(ax: plt.Axes) -> float:
    widths = [
        float(line.get_markeredgewidth())
        for axis in (ax.xaxis, ax.yaxis)
        for line in axis.get_ticklines()
        if line.get_visible() and float(line.get_markeredgewidth()) > 0.0
    ]
    return max(widths, default=float(plt.rcParams["xtick.major.width"]),)


def _apply_stroke_autorepair(fig: plt.Figure, *, template: str) -> bool:
    profile_name = "stacked" if template in {"stacked_curve", "segmented_stacked_curve"} else "curve"
    profile = qa_profile(profile_name)
    curve_profile = qa_profile("curve")
    min_width = float(profile.get("stroke_line_width_min_pt", curve_profile.get("stroke_line_width_min_pt", 1.0)))
    max_width = float(profile.get("stroke_line_width_max_pt", curve_profile.get("stroke_line_width_max_pt", 1.8)))
    min_ratio = float(profile.get("stroke_line_tick_ratio_min", curve_profile.get("stroke_line_tick_ratio_min", 0.95)))
    changed = False
    for ax in fig.axes:
        target = min(max(min_width, _tick_width(ax) * min_ratio), max_width)
        for line in ax.lines:
            if not line.get_visible():
                continue
            width = float(line.get_linewidth())
            if 0.0 < width < target:
                line.set_linewidth(target)
                changed = True
        for collection in ax.collections:
            if not collection.get_visible() or not hasattr(collection, "get_linewidths"):
                continue
            widths = [float(value) for value in collection.get_linewidths()]
            if widths and any(0.0 < width < target for width in widths):
                collection.set_linewidths([target if 0.0 < width < target else width for width in widths])
                changed = True
    return changed

def _stats_profile(groups) -> StatsRenderProfile:
    profile = qa_profile("stats")
    group_count = max(len(groups), 1)
    replicate_count = max((len(group.data) for group in groups), default=0)
    min_bar_width = float(profile.get("min_bar_width", 0.28))
    max_bar_width = float(profile.get("max_bar_width", 0.42))
    min_spacing = float(profile.get("min_spacing_scale", 1.0))
    max_spacing = float(profile.get("max_spacing_scale", 1.18))
    density = min(max((group_count - 2) / 4.0, 0.0), 1.0)
    bar_width = max_bar_width - (max_bar_width - min_bar_width) * density
    spacing_scale = min_spacing + (max_spacing - min_spacing) * min(max((group_count - 1) / 5.0, 0.0), 1.0)
    show_raw_points = (
        group_count <= int(profile.get("raw_point_max_groups", 6))
        and replicate_count <= int(profile.get("raw_point_max_replicates", 10))
    )
    return StatsRenderProfile(
        bar_width=bar_width,
        box_width=max(min(bar_width, 0.4), min_bar_width),
        violin_width=min(bar_width + 0.05, 0.48),
        spacing_scale=spacing_scale,
        show_raw_points=show_raw_points,
        raw_point_size=float(profile.get("raw_point_size", 11.0)),
        raw_point_alpha=float(profile.get("raw_point_alpha", 0.75)),
        capsize=max(2.0, min(4.0, 2.0 + bar_width * 4.5)),
    )

def _heatmap_editorial_layout() -> HeatmapEditorialLayout:
    profile = qa_profile("heatmap")
    return HeatmapEditorialLayout(
        colorbar_x_offset_fraction=float(profile.get("colorbar_x_offset_fraction", 0.29)),
        colorbar_width_fraction=float(profile.get("colorbar_width_fraction", 0.56)),
        colorbar_y_offset_fraction=float(profile.get("colorbar_y_offset_fraction", 0.2)),
        colorbar_height_fraction=float(profile.get("colorbar_height_fraction", 0.1)),
        colorbar_tick_count=int(profile.get("colorbar_tick_count", 4)),
        label_gap_pt=float(profile.get("label_gap_pt", 6.0)),
    )
