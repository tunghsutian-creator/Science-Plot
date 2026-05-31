from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import transforms

from src import plot_style
from src.data_loader import HeatmapTable
from src.layout_policy import (
    LayoutCandidate,
    LayoutScore,
    choose_layout_candidate,
    flag_margin_fallback,
    record_layout_decision,
)
from src.plotting_primitives import (
    _HEATMAP_LAYOUT,
    _compute_heatmap_cax_geometry,
    _format_axis_label,
    _resolved_panel_geometry,
)


def _colorbar_header_candidates(
    *,
    cax_rect: list[float],
    y: float,
    gap_pt: float,
) -> list[LayoutCandidate]:
    x_left = float(cax_rect[0])
    x_center = float(cax_rect[0] + cax_rect[2] / 2.0)
    x_right = float(cax_rect[0] + cax_rect[2])
    return [
        LayoutCandidate(
            candidate_id="header_left",
            anchor=(x_left, y),
            standoff_pt=gap_pt,
            payload={"x": x_left, "y": y, "ha": "left", "bias": 0.0},
            notes="left-aligned colorbar header",
        ),
        LayoutCandidate(
            candidate_id="header_center",
            anchor=(x_center, y),
            standoff_pt=gap_pt,
            payload={"x": x_center, "y": y, "ha": "center", "bias": 0.18},
            notes="center-aligned colorbar header",
        ),
        LayoutCandidate(
            candidate_id="header_right",
            anchor=(x_right, y),
            standoff_pt=gap_pt,
            payload={"x": x_right, "y": y, "ha": "right", "bias": 0.28},
            notes="right-aligned colorbar header",
        ),
    ]


def _choose_colorbar_header_candidate(
    *,
    fig: plt.Figure,
    ax: plt.Axes,
    cax_rect: list[float],
    label_text: str,
    gap_fraction: float,
    label_gap_pt: float,
    fontsize: float,
) -> tuple[LayoutCandidate, object]:
    y = min(0.985, cax_rect[1] + cax_rect[3] + gap_fraction)
    candidates = _colorbar_header_candidates(cax_rect=cax_rect, y=float(y), gap_pt=label_gap_pt)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    figure_bbox = fig.bbox
    axes_bbox = ax.get_window_extent(renderer=renderer)
    cbar_bbox = transforms.Bbox.from_bounds(
        cax_rect[0] * figure_bbox.width,
        cax_rect[1] * figure_bbox.height,
        cax_rect[2] * figure_bbox.width,
        cax_rect[3] * figure_bbox.height,
    )
    desired_gap_px = gap_fraction * figure_bbox.height

    def _score(candidate: LayoutCandidate) -> LayoutScore:
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        x = float(payload.get("x", cax_rect[0]))
        y_anchor = float(payload.get("y", y))
        ha = str(payload.get("ha", "left"))
        bias = float(payload.get("bias", 0.0))
        probe = fig.text(
            x,
            y_anchor,
            label_text,
            ha=ha,
            va="center",
            fontsize=fontsize,
            alpha=0.0,
            transform=fig.transFigure,
        )
        try:
            bbox = probe.get_window_extent(renderer=renderer)
        finally:
            probe.remove()

        if (
            bbox.x0 < 1.0
            or bbox.x1 > figure_bbox.width - 1.0
            or bbox.y0 < 1.0
            or bbox.y1 > figure_bbox.height - 1.0
        ):
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="header_out_of_figure")
        if bbox.y0 <= cbar_bbox.y1 + 0.5:
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="header_overlaps_colorbar")

        gap_px = float(bbox.y0 - cbar_bbox.y1)
        gap_penalty = abs(gap_px - desired_gap_px) * 0.45
        axes_penalty = 280.0 if bbox.overlaps(axes_bbox) else 0.0
        score = gap_penalty + axes_penalty + bias
        return LayoutScore(
            score=score,
            blocked=False,
            reason=(
                f"gap_px={gap_px:.3f}; gap_penalty={gap_penalty:.3f}; "
                f"axes_penalty={axes_penalty:.1f}; bias={bias:.3f}"
            ),
        )

    def _fallback(
        available: list[LayoutCandidate],
        _evaluations,
        _best,
    ) -> tuple[LayoutCandidate, float, str] | None:
        if not available:
            return None
        fallback_candidate = available[0]
        payload = fallback_candidate.payload if isinstance(fallback_candidate.payload, dict) else {}
        fallback_y = min(float(payload.get("y", y)), 0.985)
        return (
            LayoutCandidate(
                candidate_id=fallback_candidate.candidate_id,
                anchor=(float(payload.get("x", cax_rect[0])), fallback_y),
                standoff_pt=fallback_candidate.standoff_pt,
                payload={**payload, "y": fallback_y},
                notes=fallback_candidate.notes,
            ),
            1_000_000.0,
            "clamped header to figure top margin",
        )

    decision = choose_layout_candidate(
        object_kind="colorbar_header",
        candidates=candidates,
        score_hook=_score,
        fallback_hook=_fallback,
    )
    chosen = decision.chosen_candidate or candidates[0]
    if np.isclose(y, 0.985):
        decision = flag_margin_fallback(
            decision,
            action="clamp_to_figure_top",
            reason="colorbar header anchor touched figure-top margin",
        )
    return chosen, decision


def plot_heatmap(
    table: HeatmapTable,
    *,
    width_mm: float | None = None,
    height_mm: float | None = None,
    left_margin_mm: float | None = None,
    right_margin_mm: float | None = None,
    bottom_margin_mm: float | None = None,
    top_margin_mm: float | None = None,
    show_colorbar: bool = True,
    palette_preset: str | None = None,
    colorbar_layout: dict[str, float] | None = None,
    colorbar_tick_count: int = 3,
    colorbar_label_gap_pt: float = 4.0,
) -> tuple[plt.Figure, plt.Axes]:
    (
        resolved_width_mm,
        resolved_height_mm,
        resolved_left_margin_mm,
        resolved_right_margin_mm,
        resolved_bottom_margin_mm,
        resolved_top_margin_mm,
    ) = _resolved_panel_geometry(
        width_mm=width_mm,
        height_mm=height_mm,
        left_margin_mm=left_margin_mm,
        right_margin_mm=right_margin_mm,
        bottom_margin_mm=bottom_margin_mm,
        top_margin_mm=top_margin_mm,
    )
    fig, ax = plot_style.create_panel_figure(
        width_mm=resolved_width_mm,
        height_mm=resolved_height_mm,
        left_margin_mm=resolved_left_margin_mm,
        right_margin_mm=resolved_right_margin_mm,
        bottom_margin_mm=resolved_bottom_margin_mm,
        top_margin_mm=resolved_top_margin_mm,
    )

    x_is_numeric = pd.api.types.is_numeric_dtype(table.data["x"])
    y_is_numeric = pd.api.types.is_numeric_dtype(table.data["y"])

    if x_is_numeric:
        x_order = sorted(pd.unique(table.data["x"]).tolist())
    else:
        x_order = pd.unique(table.data["x"]).tolist()
    if y_is_numeric:
        y_order = sorted(pd.unique(table.data["y"]).tolist())
    else:
        y_order = pd.unique(table.data["y"]).tolist()

    matrix = table.data.pivot(index="y", columns="x", values="z").reindex(
        index=y_order,
        columns=x_order,
    )

    cax = None
    colorbar_label = None
    if show_colorbar:
        position = ax.get_position()
        heatmap_rect, cax_rect = _compute_heatmap_cax_geometry(position, layout_overrides=colorbar_layout)
        ax.set_position(heatmap_rect)
        cax = fig.add_axes(cax_rect)
        gap_fraction = (colorbar_label_gap_pt / 72.0) / max(fig.get_size_inches()[1], 1e-6)
        colorbar_header, colorbar_decision = _choose_colorbar_header_candidate(
            fig=fig,
            ax=ax,
            cax_rect=cax_rect,
            label_text=_format_axis_label(table.z_label, table.z_unit),
            gap_fraction=gap_fraction,
            label_gap_pt=float(colorbar_label_gap_pt),
            fontsize=float(_HEATMAP_LAYOUT["label_font_size_pt"]),
        )
        record_layout_decision(
            fig,
            colorbar_decision,
            context={"path": "heatmap_colorbar_header", "phase": "candidate_selection"},
        )
        header_payload = colorbar_header.payload if isinstance(colorbar_header.payload, dict) else {}
        colorbar_label = fig.text(
            float(header_payload.get("x", cax_rect[0])),
            float(header_payload.get("y", min(0.985, cax_rect[1] + cax_rect[3] + gap_fraction))),
            _format_axis_label(table.z_label, table.z_unit),
            ha=str(header_payload.get("ha", "left")),
            va="center",
            fontsize=float(_HEATMAP_LAYOUT["label_font_size_pt"]),
        )

    heatmap = sns.heatmap(
        matrix,
        ax=ax,
        cmap=plot_style.get_sequential_cmap(palette_preset),
        cbar=False,
        linewidths=0.0,
    )
    ax.set_xlabel(_format_axis_label(table.x_label, table.x_unit))
    ax.set_ylabel(_format_axis_label(table.y_label, table.y_unit))
    ax.tick_params(axis="x", rotation=0)
    ax.tick_params(axis="y", rotation=0)

    for tick in ax.get_xticklabels():
        tick.set_fontsize(6)
    for tick in ax.get_yticklabels():
        tick.set_fontsize(6)

    if show_colorbar and heatmap.collections and cax is not None:
        z_min = float(np.nanmin(matrix.to_numpy(dtype=float)))
        z_max = float(np.nanmax(matrix.to_numpy(dtype=float)))
        colorbar = fig.colorbar(heatmap.collections[0], cax=cax, orientation="horizontal")
        tick_count = max(2, int(colorbar_tick_count))
        colorbar.set_ticks(np.linspace(z_min, z_max, tick_count))
        colorbar.ax.tick_params(
            labelsize=float(_HEATMAP_LAYOUT["tick_font_size_pt"]),
            pad=0.2,
            length=float(_HEATMAP_LAYOUT["tick_length_pt"]),
        )
        colorbar.outline.set_linewidth(0.8)
        if colorbar_label is not None:
            colorbar_label.set_fontsize(float(_HEATMAP_LAYOUT["label_font_size_pt"]))
    return fig, ax
