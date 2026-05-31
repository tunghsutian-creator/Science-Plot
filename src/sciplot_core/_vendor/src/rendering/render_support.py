from __future__ import annotations

from dataclasses import dataclass

import matplotlib.pyplot as plt

from src.plot_contract import qa_profile
from src.rendering.models import RenderedPlot, RenderOptions
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
    return RenderedPlot(
        filename=filename,
        figure=figure,
        qa_report=analyze_rendered_figure(
            figure,
            template=template,
            options=options,
            palette_preset=options.palette_preset,
            autofixes_applied=autofixes_applied,
        ),
    )

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
