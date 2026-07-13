from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import transforms
from src.layout_policy import (
    LayoutCandidate,
    LayoutScore,
    choose_layout_candidate,
    empty_layout_decision,
    flag_margin_fallback,
    record_layout_decision,
)
from src.plotting_families.heatmap_family import plot_heatmap
from src.plotting_primitives import _format_axis_label
from src.rendering.cache import load_heatmap_table_for_options
from src.rendering.models import RenderedPlot, RenderOptions
from src.rendering.render_support import _heatmap_editorial_layout, _rendered_plot_with_qa


@dataclass(frozen=True)
class HeatmapCellLabelPlacement:
    x: float
    y: float
    text: str
    color: str
    fontsize: float

def _probe_heatmap_cell_text_bbox(
    ax: plt.Axes,
    *,
    renderer: object,
    x: float,
    y: float,
    text: str,
    fontsize: float,
) -> transforms.Bbox:
    probe = ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        alpha=0.0,
        clip_on=True,
        zorder=4.2,
    )
    bbox = probe.get_window_extent(renderer=renderer)
    probe.remove()
    return bbox

def _heatmap_cell_display_bbox(ax: plt.Axes, *, x_idx: int, y_idx: int) -> transforms.Bbox:
    p0 = ax.transData.transform((float(x_idx), float(y_idx)))
    p1 = ax.transData.transform((float(x_idx + 1), float(y_idx + 1)))
    left = min(float(p0[0]), float(p1[0]))
    right = max(float(p0[0]), float(p1[0]))
    bottom = min(float(p0[1]), float(p1[1]))
    top = max(float(p0[1]), float(p1[1]))
    return transforms.Bbox.from_extents(left, bottom, right, top)

def _overflow_against_cell(text_bbox: transforms.Bbox, cell_bbox: transforms.Bbox) -> float:
    overflow = 0.0
    overflow += max(0.0, cell_bbox.x0 - text_bbox.x0)
    overflow += max(0.0, text_bbox.x1 - cell_bbox.x1)
    overflow += max(0.0, cell_bbox.y0 - text_bbox.y0)
    overflow += max(0.0, text_bbox.y1 - cell_bbox.y1)
    norm = max(cell_bbox.width + cell_bbox.height, 1.0)
    return overflow / norm

def _format_heatmap_cell_value(value: float, *, fmt: str) -> str:
    return f"{value:{fmt}}"

def _choose_annotated_heatmap_label_plan(
    *,
    fig: plt.Figure,
    ax: plt.Axes,
    values: np.ndarray,
    mid: float,
) -> tuple[list[HeatmapCellLabelPlacement], str]:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    finite_cells = [
        (y_idx, x_idx, float(values[y_idx, x_idx]))
        for y_idx in range(values.shape[0])
        for x_idx in range(values.shape[1])
        if np.isfinite(values[y_idx, x_idx])
    ]
    if not finite_cells:
        record_layout_decision(
            fig,
            empty_layout_decision("annotation_textbox", reason="no_finite_heatmap_cells"),
            context={
                "path": "annotated_heatmap_cell_labels",
                "phase": "candidate_selection",
                "annotation_kind": "heatmap_cell_labels",
                "matrix_shape": [int(values.shape[0]), int(values.shape[1])],
                "finite_cells": 0,
            },
        )
        return [], "labels_none"

    candidates = [
        LayoutCandidate(
            candidate_id="labels_full",
            payload={"fmt": ".3g", "fontsize": 5.2, "checkerboard": False, "bias": 0.0},
            notes="full precision per-cell labels",
        ),
        LayoutCandidate(
            candidate_id="labels_compact",
            payload={"fmt": ".2g", "fontsize": 4.8, "checkerboard": False, "bias": 0.8},
            notes="compact precision per-cell labels",
        ),
        LayoutCandidate(
            candidate_id="labels_small",
            payload={"fmt": ".2g", "fontsize": 4.4, "checkerboard": False, "bias": 1.2},
            notes="small-font per-cell labels",
        ),
        LayoutCandidate(
            candidate_id="labels_checkerboard",
            payload={"fmt": ".2g", "fontsize": 4.8, "checkerboard": True, "bias": 2.8},
            notes="checkerboard fallback for dense matrices",
        ),
    ]
    plan_cache: dict[str, list[HeatmapCellLabelPlacement]] = {}

    def _score(candidate: LayoutCandidate) -> LayoutScore:
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        fmt = str(payload.get("fmt", ".3g"))
        fontsize = float(payload.get("fontsize", 5.2))
        checkerboard = bool(payload.get("checkerboard", False))
        bias = float(payload.get("bias", 0.0))

        placements: list[HeatmapCellLabelPlacement] = []
        placed_bboxes: list[transforms.Bbox] = []
        overflow_total = 0.0
        overlap_count = 0
        hidden_count = 0

        for y_idx, x_idx, value in finite_cells:
            if checkerboard and ((x_idx + y_idx) % 2 == 1):
                hidden_count += 1
                continue
            text_value = _format_heatmap_cell_value(value, fmt=fmt)
            text_bbox = _probe_heatmap_cell_text_bbox(
                ax,
                renderer=renderer,
                x=float(x_idx + 0.5),
                y=float(y_idx + 0.5),
                text=text_value,
                fontsize=fontsize,
            )
            cell_bbox = _heatmap_cell_display_bbox(ax, x_idx=x_idx, y_idx=y_idx)
            overflow_total += _overflow_against_cell(text_bbox, cell_bbox)
            expanded = text_bbox.expanded(1.03, 1.10)
            if any(expanded.overlaps(other) for other in placed_bboxes):
                overlap_count += 1
            placed_bboxes.append(expanded)
            placements.append(
                HeatmapCellLabelPlacement(
                    x=float(x_idx + 0.5),
                    y=float(y_idx + 0.5),
                    text=text_value,
                    color="white" if value >= mid else "black",
                    fontsize=fontsize,
                )
            )

        if not placements:
            return LayoutScore(score=1_000_000_000.0, blocked=True, reason="no_visible_labels")

        shown = len(placements)
        total = len(finite_cells)
        overlap_ratio = overlap_count / shown
        overflow_ratio = overflow_total / shown
        hidden_ratio = hidden_count / total
        score = overlap_ratio * 260.0 + overflow_ratio * 62.0 + hidden_ratio * 28.0 + bias
        reason = (
            f"shown={shown}/{total}; overlap_ratio={overlap_ratio:.3f}; "
            f"overflow_ratio={overflow_ratio:.3f}; hidden_ratio={hidden_ratio:.3f}; bias={bias:.3f}"
        )
        plan_cache[candidate.candidate_id] = placements
        return LayoutScore(score=float(score), reason=reason)

    decision = choose_layout_candidate(
        object_kind="annotation_textbox",
        candidates=candidates,
        score_hook=_score,
    )
    if decision.chosen_candidate is None:
        record_layout_decision(
            fig,
            empty_layout_decision("annotation_textbox", reason="no_viable_heatmap_label_strategy"),
            context={
                "path": "annotated_heatmap_cell_labels",
                "phase": "candidate_selection",
                "annotation_kind": "heatmap_cell_labels",
                "matrix_shape": [int(values.shape[0]), int(values.shape[1])],
                "finite_cells": int(len(finite_cells)),
            },
        )
        return [], "labels_none"
    strategy_id = decision.chosen_candidate.candidate_id
    if strategy_id != "labels_full":
        decision = flag_margin_fallback(
            decision,
            action=f"heatmap_label_strategy:{strategy_id}",
            reason="default full-label strategy was not optimal for this matrix density",
        )
    record_layout_decision(
        fig,
        decision,
        context={
            "path": "annotated_heatmap_cell_labels",
            "phase": "candidate_selection",
            "annotation_kind": "heatmap_cell_labels",
            "matrix_shape": [int(values.shape[0]), int(values.shape[1])],
            "finite_cells": int(len(finite_cells)),
        },
    )
    return plan_cache.get(strategy_id, []), strategy_id

def _render_heatmap(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    table = load_heatmap_table_for_options(input_path, sheet, options)
    layout = _heatmap_editorial_layout()
    fig, _ = plot_heatmap(
        table,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        show_colorbar=options.show_colorbar,
        palette_preset=options.palette_preset,
        colorbar_layout={
            "frame_envelope_mode": layout.frame_envelope_mode,
            "colorbar_x_offset_fraction": layout.colorbar_x_offset_fraction,
            "colorbar_width_fraction": layout.colorbar_width_fraction,
            "colorbar_height_fraction": layout.colorbar_height_fraction,
            "colorbar_main_gap_fraction": layout.colorbar_main_gap_fraction,
        },
        colorbar_tick_count=layout.colorbar_tick_count,
        colorbar_label_gap_pt=layout.label_gap_pt,
    )
    if fig.axes:
        ax = fig.axes[0]
        ax.set_xlabel(
            _format_axis_label(
                table.x_label,
                table.x_unit,
                override_label=options.x_label_override,
            )
        )
        ax.set_ylabel(
            _format_axis_label(
                table.y_label,
                table.y_unit,
                override_label=options.y_label_override,
            )
        )
    autofixes = ("heatmap_colorbar_tuned",) if options.show_colorbar else ()
    return [
        _rendered_plot_with_qa(
            filename=f"{input_path.stem}_heatmap.pdf",
            figure=fig,
            template="heatmap",
            options=options,
            autofixes_applied=autofixes,
        )
    ]

def _render_annotated_heatmap(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    table = load_heatmap_table_for_options(input_path, sheet, options)
    layout = _heatmap_editorial_layout()
    fig, ax = plot_heatmap(
        table,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        show_colorbar=options.show_colorbar,
        palette_preset=options.palette_preset,
        colorbar_layout={
            "frame_envelope_mode": layout.frame_envelope_mode,
            "colorbar_x_offset_fraction": layout.colorbar_x_offset_fraction,
            "colorbar_width_fraction": layout.colorbar_width_fraction,
            "colorbar_height_fraction": layout.colorbar_height_fraction,
            "colorbar_main_gap_fraction": layout.colorbar_main_gap_fraction,
        },
        colorbar_tick_count=layout.colorbar_tick_count,
        colorbar_label_gap_pt=layout.label_gap_pt,
    )
    matrix = table.data.pivot(index="y", columns="x", values="z")
    values = matrix.to_numpy(dtype=float)
    if values.size:
        finite = values[np.isfinite(values)]
        mid = float(np.median(finite)) if finite.size else 0.0
    else:
        mid = 0.0
    placements, strategy_id = _choose_annotated_heatmap_label_plan(
        fig=fig,
        ax=ax,
        values=values,
        mid=mid,
    )
    for placement in placements:
        ax.text(
            placement.x,
            placement.y,
            placement.text,
            ha="center",
            va="center",
            fontsize=placement.fontsize,
            color=placement.color,
            zorder=4.2,
            clip_on=True,
        )
    ax.set_xlabel(
        _format_axis_label(
            table.x_label,
            table.x_unit,
            override_label=options.x_label_override,
        )
    )
    ax.set_ylabel(
        _format_axis_label(
            table.y_label,
            table.y_unit,
            override_label=options.y_label_override,
        )
    )
    autofixes = ["annotated_heatmap_labels"]
    if strategy_id != "labels_full":
        autofixes.append("annotated_heatmap_label_layout_policy")
        autofixes.append(f"annotated_heatmap_label_strategy_{strategy_id}")
    if options.show_colorbar:
        autofixes.append("heatmap_colorbar_tuned")
    return [
        _rendered_plot_with_qa(
            filename=f"{input_path.stem}_annotated_heatmap.pdf",
            figure=fig,
            template="annotated_heatmap",
            options=options,
            autofixes_applied=tuple(autofixes),
        )
    ]
