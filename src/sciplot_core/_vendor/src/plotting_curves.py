from __future__ import annotations

from collections.abc import Sequence

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import to_rgba
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator

from src import plot_style
from src.data_loader import CurveSeries
from src.layout_policy import LayoutCandidate, LayoutScore, choose_layout_candidate, record_layout_decision
from src.layout_scoring import score_points_against_bbox
from src.plotting_curve_support import (
    CURVE_TEMPLATES,
    INSIDE_LEGEND_INSET_FRACTION,
    MARKER_STYLE_CYCLE,
    _baseline_correct_series,
    _compute_stacked_axis_limits,
    _infer_markevery,
    _legend_kwargs,
    _place_series_edge_labels,
    _prepare_stacked_layout,
    _stack_retry_scales,
    _validate_curve_series_input,
    absolute_legend_inset_fractions,
    legend_layout_candidates,
)
from src.plotting_primitives import (
    MAX_VISIBLE_Y_MAJOR_TICKS,
    AxisLimits,
    AxisMode,
    LegendMode,
    _apply_major_ticks_with_override,
    _apply_numeric_axis_tick_preferences,
    _format_axis_label,
    _merge_limits,
    _resolved_panel_geometry,
    compute_axis_limits,
)


def _legend_candidates(
    inset_fraction: float | tuple[float, float] = INSIDE_LEGEND_INSET_FRACTION,
) -> list[tuple[str, tuple[float, float], str]]:
    compatibility: list[tuple[str, tuple[float, float], str]] = []
    for candidate in legend_layout_candidates(
        preserve_stress_label=False,
        compact=False,
        inset_fraction=inset_fraction,
    ):
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        anchor = candidate.anchor if candidate.anchor is not None else (1.0, 1.0)
        compatibility.append(
            (
                str(payload.get("loc", "upper right")),
                anchor,
                str(payload.get("alignment", "right")),
            )
        )
    return compatibility


def _place_legend_candidate(
    ax: plt.Axes,
    candidate: LayoutCandidate | tuple[str, tuple[float, float], str],
) -> Legend:
    if isinstance(candidate, tuple):
        loc, anchor, align = candidate
    else:
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        loc = str(payload.get("loc", "upper right"))
        align = str(payload.get("alignment", "right"))
        anchor = candidate.anchor if candidate.anchor is not None else (1.0, 1.0)
    legend = ax.legend(
        loc=loc,
        bbox_to_anchor=anchor,
        bbox_transform=ax.transAxes,
        borderaxespad=0.0,
        alignment=align,
    )
    return legend


def _score_legend_bbox(ax: plt.Axes, legend: Legend, series_list: Sequence[CurveSeries]) -> float:
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bbox = legend.get_window_extent(renderer=renderer)
    score = 0.0

    for series in series_list:
        x = series.data["x"].to_numpy(dtype=float)
        y = series.data["y"].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        x = x[valid]
        y = y[valid]
        if len(x) == 0:
            continue

        points = ax.transData.transform(np.column_stack([x, y]))
        metrics = score_points_against_bbox(
            points,
            bbox,
            inside_weight=10.0,
            near_radius=12.0,
            near_weight=1.0,
            normalize_near=True,
        )
        score += metrics.total

    return score


def _legend_kwargs_from_candidate(
    ax: plt.Axes,
    candidate: LayoutCandidate,
) -> dict[str, object]:
    payload = candidate.payload if isinstance(candidate.payload, dict) else {}
    loc = str(payload.get("loc", "upper right"))
    align = str(payload.get("alignment", "right"))
    anchor = candidate.anchor if candidate.anchor is not None else (1.0, 1.0)
    return {
        "loc": loc,
        "bbox_to_anchor": anchor,
        "bbox_transform": ax.transAxes,
        "borderaxespad": 0.0,
        "alignment": align,
    }


def choose_legend_corner_with_policy(
    ax: plt.Axes,
    series_list: Sequence[CurveSeries],
    inset_fraction: float | tuple[float, float] = INSIDE_LEGEND_INSET_FRACTION,
    *,
    preserve_stress_label: bool = False,
) -> tuple[dict[str, object], float, object]:
    candidates = legend_layout_candidates(
        preserve_stress_label=preserve_stress_label,
        compact=False,
        inset_fraction=inset_fraction,
    )

    def _score(candidate: LayoutCandidate) -> LayoutScore:
        payload = candidate.payload if isinstance(candidate.payload, dict) else {}
        legend = _place_legend_candidate(ax, candidate)
        try:
            overlap = _score_legend_bbox(ax, legend, series_list)
            bias = float(payload.get("bias", 0.0))
            score = overlap + bias
            return LayoutScore(
                score=score,
                blocked=False,
                reason=f"curve_overlap={overlap:.4f}; bias={bias:.3f}",
            )
        finally:
            legend.remove()

    decision = choose_layout_candidate(
        object_kind="legend",
        candidates=candidates,
        score_hook=_score,
    )
    chosen = decision.chosen_candidate or candidates[0]
    score = float(decision.chosen_score) if decision.chosen_score is not None else float("inf")
    return _legend_kwargs_from_candidate(ax, chosen), score, decision


def choose_legend_corner(
    ax: plt.Axes,
    series_list: Sequence[CurveSeries],
    inset_fraction: float | tuple[float, float] = INSIDE_LEGEND_INSET_FRACTION,
    *,
    preserve_stress_label: bool = False,
) -> tuple[dict[str, object], float]:
    kwargs, score, _decision = choose_legend_corner_with_policy(
        ax,
        series_list,
        inset_fraction=inset_fraction,
        preserve_stress_label=preserve_stress_label,
    )
    return kwargs, score


def plot_curves(
    series_list: Sequence[CurveSeries],
    *,
    legend_mode: LegendMode = "inside_best",
    axis_mode: AxisMode = "auto",
    xscale: str = "linear",
    yscale: str = "linear",
    width_mm: float | None = None,
    height_mm: float | None = None,
    left_margin_mm: float | None = None,
    right_margin_mm: float | None = None,
    bottom_margin_mm: float | None = None,
    top_margin_mm: float | None = None,
    xlim: tuple[float | None, float | None] | None = None,
    ylim: tuple[float | None, float | None] | None = None,
    headroom_factor: float | None = None,
    y_padding_top: float = 0.18,
    y_padding_bottom: float = 0.06,
    show_markers: bool = True,
    marker_style_cycle: Sequence[str] | None = None,
    marker_size: float | None = None,
    marker_every: int | None = None,
    visible_xticks: Sequence[float] | None = None,
    x_tick_density: str | None = None,
    y_tick_density: str | None = None,
    x_tick_edge_labels: str | None = None,
    y_tick_edge_labels: str | None = None,
    x_padding_fraction: float | None = None,
    reverse_x: bool = False,
    stack_mode: str = "none",
    stack_floor_fraction: float = 0.22,
    stack_gap_fraction: float = 0.22,
    series_label_mode: str = "legend",
    series_label_side: str = "auto",
    label_track_inset_fraction: float = 0.06,
    label_offset_pt: float = 5.0,
    baseline_mode: str = "none",
    show_y_ticks: bool = True,
    legend_expand_axes: str = "xy",
    legend_inset_fraction: float | None = None,
    preserve_stress_label: bool = False,
    line_drawstyle: str = "default",
    fill_to_axis: bool = False,
) -> tuple[plt.Figure, plt.Axes]:
    _validate_curve_series_input(series_list)
    stroke = plot_style.current_stroke()
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
    legend_inset = absolute_legend_inset_fractions(
        width_mm=resolved_width_mm,
        height_mm=resolved_height_mm,
        left_margin_mm=resolved_left_margin_mm,
        right_margin_mm=resolved_right_margin_mm,
        bottom_margin_mm=resolved_bottom_margin_mm,
        top_margin_mm=resolved_top_margin_mm,
        default=legend_inset_fraction,
    )
    palette = plot_style.get_categorical_palette(n_colors=len(series_list))
    markers = marker_style_cycle or MARKER_STYLE_CYCLE
    resolved_marker_size = stroke.marker_size_pt if marker_size is None else marker_size
    normalized_series = _baseline_correct_series(series_list, baseline_mode=baseline_mode)
    stacked_mode_enabled = stack_mode != "none" and len(series_list) > 1
    plotted_series = list(normalized_series)
    limits: AxisLimits
    label_success = True
    retry_scales = _stack_retry_scales() if stacked_mode_enabled and series_label_mode == "edge" else (1.0,)

    for step_scale in retry_scales:
        ax.cla()
        plotted_lines: list[tuple[CurveSeries, tuple[float, float, float], Line2D]] = []
        stacked_layout = (
            _prepare_stacked_layout(
                normalized_series,
                stack_floor_fraction=stack_floor_fraction,
                stack_gap_fraction=stack_gap_fraction,
                step_scale=step_scale,
            )
            if stacked_mode_enabled
            else None
        )
        plotted_series = stacked_layout.series_list if stacked_layout is not None else list(normalized_series)

        for idx, (color, series) in enumerate(zip(palette, plotted_series, strict=True)):
            markevery = marker_every if marker_every is not None else _infer_markevery(len(series.data))
            line_color = to_rgba(color, stroke.line_alpha)
            (line,) = ax.plot(
                series.data["x"],
                series.data["y"],
                label=series.sample,
                color=line_color,
                linewidth=stroke.line_width_pt,
                drawstyle=line_drawstyle,
                marker=markers[idx % len(markers)] if show_markers else None,
                markersize=resolved_marker_size,
                markerfacecolor=color,
                markeredgecolor=color,
                markeredgewidth=0.5,
                markevery=markevery,
            )
            plotted_lines.append((series, color, line))

        if stacked_layout is not None:
            limits = _compute_stacked_axis_limits(
                stacked_layout,
                xscale=xscale,
                y_padding_top=y_padding_top,
                x_padding=0.02 if x_padding_fraction is None else x_padding_fraction,
            )
        else:
            limits = compute_axis_limits(
                [series.data["y"].to_numpy() for series in plotted_series],
                kind="line",
                axis_mode=axis_mode,
                legend_mode=legend_mode,
                x_values=[series.data["x"].to_numpy() for series in plotted_series],
                xscale=xscale,
                yscale=yscale,
                x_padding=0.02 if x_padding_fraction is None else x_padding_fraction,
                headroom_factor=headroom_factor,
                y_padding_top=y_padding_top,
                y_padding_bottom=y_padding_bottom,
            )
        ax.set_xlim(*_merge_limits(limits.xlim, xlim))
        ax.set_ylim(*_merge_limits(limits.ylim, ylim))
        ax.set_xscale(xscale)
        ax.set_yscale(yscale)
        if reverse_x:
            ax.invert_xaxis()

        if fill_to_axis:
            y_floor = ax.get_ylim()[0]
            baseline = y_floor
            if yscale != "log" and all((series.data["y"] >= 0).all() for series, _color, _line in plotted_lines):
                baseline = 0.0
            elif yscale != "log" and y_floor <= 0.0 <= ax.get_ylim()[1]:
                baseline = 0.0
            fill_alpha = min(stroke.max_fill_alpha, stroke.fill_alpha)
            for idx, (series, color, line) in enumerate(plotted_lines):
                x_values = series.data["x"].to_numpy(dtype=float)
                y_values = series.data["y"].to_numpy(dtype=float)
                valid = np.isfinite(x_values) & np.isfinite(y_values)
                if np.count_nonzero(valid) < 2:
                    continue
                series_baseline = baseline
                if stacked_layout is not None:
                    series_baseline = stacked_layout.floor + idx * stacked_layout.step
                ax.fill_between(
                    x_values[valid],
                    y_values[valid],
                    series_baseline,
                    color=to_rgba(color, fill_alpha),
                    linewidth=0.0,
                    zorder=line.get_zorder() - 0.2,
                )

        first = series_list[0]
        ax.set_xlabel(_format_axis_label(first.x_label, first.x_unit))
        ax.set_ylabel(
            _format_axis_label(
                first.y_label,
                first.y_unit,
                preserve_stress_label=preserve_stress_label,
            )
        )
        if not show_y_ticks:
            ax.tick_params(axis="y", left=False, labelleft=False, which="both")
            ax.spines["left"].set_visible(True)
        if series_label_mode == "edge" and len(plotted_series) > 1:
            label_success = _place_series_edge_labels(
                ax,
                plotted_series,
                palette,
                reverse_x=reverse_x,
                side=series_label_side,
                inset_fraction=label_track_inset_fraction,
                label_offset_pt=label_offset_pt,
                search_band_fraction=0.24 if stacked_mode_enabled else 0.08,
                fontsize=6.2 if stacked_mode_enabled else 6.0,
            )
        else:
            label_success = True
        if label_success:
            break

    if series_label_mode != "edge" and legend_mode == "inside_best":
        legend_kwargs, _overlap_score, legend_corner_decision = choose_legend_corner_with_policy(
            ax,
            plotted_series,
            inset_fraction=legend_inset,
            preserve_stress_label=preserve_stress_label,
        )
        record_layout_decision(
            fig,
            legend_corner_decision,
            context={"path": "plot_curves", "phase": "legend_corner_initial"},
        )
        ax.legend(**legend_kwargs)
    elif series_label_mode != "edge" and legend_mode != "none":
        legend_kwargs = _legend_kwargs(legend_mode, inset_fraction=legend_inset)
        if "bbox_to_anchor" in legend_kwargs:
            legend_kwargs["bbox_transform"] = ax.transAxes
        ax.legend(**legend_kwargs)

    if visible_xticks is not None:
        ax.xaxis.set_major_locator(FixedLocator(np.asarray(visible_xticks, dtype=float)))
    else:
        _apply_major_ticks_with_override(
            ax.xaxis,
            policy_ticks=limits.x_tick_policy.major_ticks if limits.x_tick_policy is not None else None,
            override=xlim,
            scale=xscale,
        )
    _apply_numeric_axis_tick_preferences(
        ax.xaxis,
        scale=xscale,
        tick_density=x_tick_density,
        tick_edge_labels=x_tick_edge_labels,
    )
    if show_y_ticks:
        _apply_major_ticks_with_override(
            ax.yaxis,
            policy_ticks=limits.y_tick_policy.major_ticks if limits.y_tick_policy is not None else None,
            override=ylim,
            scale=yscale,
            max_major_ticks=MAX_VISIBLE_Y_MAJOR_TICKS,
        )
        _apply_numeric_axis_tick_preferences(
            ax.yaxis,
            scale=yscale,
            tick_density=y_tick_density,
            tick_edge_labels=y_tick_edge_labels,
            max_major_ticks=MAX_VISIBLE_Y_MAJOR_TICKS,
        )
    return fig, ax


def plot_scatter(
    series_list: Sequence[CurveSeries],
    *,
    legend_mode: LegendMode = "inside_best",
    axis_mode: AxisMode = "auto",
    xscale: str = "linear",
    yscale: str = "linear",
    width_mm: float | None = None,
    height_mm: float | None = None,
    left_margin_mm: float | None = None,
    right_margin_mm: float | None = None,
    bottom_margin_mm: float | None = None,
    top_margin_mm: float | None = None,
    xlim: tuple[float | None, float | None] | None = None,
    ylim: tuple[float | None, float | None] | None = None,
    headroom_factor: float | None = None,
    y_padding_top: float = 0.12,
    y_padding_bottom: float = 0.06,
    marker_size: float = 14.0,
    visible_xticks: Sequence[float] | None = None,
    x_tick_density: str | None = None,
    y_tick_density: str | None = None,
    x_tick_edge_labels: str | None = None,
    y_tick_edge_labels: str | None = None,
    x_padding_fraction: float | None = None,
    reverse_x: bool = False,
    legend_expand_axes: str = "xy",
    legend_inset_fraction: float | None = None,
    preserve_stress_label: bool = False,
) -> tuple[plt.Figure, plt.Axes]:
    _validate_curve_series_input(series_list)
    stroke = plot_style.current_stroke()
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
    legend_inset = absolute_legend_inset_fractions(
        width_mm=resolved_width_mm,
        height_mm=resolved_height_mm,
        left_margin_mm=resolved_left_margin_mm,
        right_margin_mm=resolved_right_margin_mm,
        bottom_margin_mm=resolved_bottom_margin_mm,
        top_margin_mm=resolved_top_margin_mm,
        default=legend_inset_fraction,
    )
    palette = plot_style.get_categorical_palette(n_colors=len(series_list))

    for color, series in zip(palette, series_list, strict=True):
        ax.scatter(
            series.data["x"],
            series.data["y"],
            label=series.sample,
            color=color,
            s=marker_size,
            alpha=stroke.marker_alpha,
            linewidths=0.0,
            zorder=2.5,
        )

    limits = compute_axis_limits(
        [series.data["y"].to_numpy() for series in series_list],
        kind="line",
        axis_mode=axis_mode,
        legend_mode=legend_mode,
        x_values=[series.data["x"].to_numpy() for series in series_list],
        xscale=xscale,
        yscale=yscale,
        x_padding=0.02 if x_padding_fraction is None else x_padding_fraction,
        headroom_factor=headroom_factor,
        y_padding_top=y_padding_top,
        y_padding_bottom=y_padding_bottom,
    )
    ax.set_xlim(*_merge_limits(limits.xlim, xlim))
    ax.set_ylim(*_merge_limits(limits.ylim, ylim))
    ax.set_xscale(xscale)
    ax.set_yscale(yscale)
    if reverse_x:
        ax.invert_xaxis()

    first = series_list[0]
    ax.set_xlabel(_format_axis_label(first.x_label, first.x_unit))
    ax.set_ylabel(
        _format_axis_label(
            first.y_label,
            first.y_unit,
            preserve_stress_label=preserve_stress_label,
        )
    )

    if legend_mode == "inside_best":
        legend_kwargs, _overlap_score, legend_corner_decision = choose_legend_corner_with_policy(
            ax,
            series_list,
            inset_fraction=legend_inset,
            preserve_stress_label=preserve_stress_label,
        )
        record_layout_decision(
            fig,
            legend_corner_decision,
            context={"path": "plot_scatter", "phase": "legend_corner_initial"},
        )
        ax.legend(**legend_kwargs)
    elif legend_mode != "none":
        legend_kwargs = _legend_kwargs(legend_mode, inset_fraction=legend_inset)
        if "bbox_to_anchor" in legend_kwargs:
            legend_kwargs["bbox_transform"] = ax.transAxes
        ax.legend(**legend_kwargs)

    if visible_xticks is not None:
        ax.xaxis.set_major_locator(FixedLocator(np.asarray(visible_xticks, dtype=float)))
    else:
        _apply_major_ticks_with_override(
            ax.xaxis,
            policy_ticks=limits.x_tick_policy.major_ticks if limits.x_tick_policy is not None else None,
            override=xlim,
            scale=xscale,
        )
    _apply_numeric_axis_tick_preferences(
        ax.xaxis,
        scale=xscale,
        tick_density=x_tick_density,
        tick_edge_labels=x_tick_edge_labels,
    )
    _apply_major_ticks_with_override(
        ax.yaxis,
        policy_ticks=limits.y_tick_policy.major_ticks if limits.y_tick_policy is not None else None,
        override=ylim,
        scale=yscale,
        max_major_ticks=MAX_VISIBLE_Y_MAJOR_TICKS,
    )
    _apply_numeric_axis_tick_preferences(
        ax.yaxis,
        scale=yscale,
        tick_density=y_tick_density,
        tick_edge_labels=y_tick_edge_labels,
        max_major_ticks=MAX_VISIBLE_Y_MAJOR_TICKS,
    )
    return fig, ax


def plot_curve_template(
    template_name: str,
    series_list: Sequence[CurveSeries],
    **overrides: object,
) -> tuple[plt.Figure, plt.Axes]:
    try:
        template = CURVE_TEMPLATES[template_name]
    except KeyError as exc:
        raise ValueError(f"Unknown curve template: {template_name}") from exc

    params: dict[str, object] = {
        "xscale": template.xscale,
        "yscale": template.yscale,
        "width_mm": template.width_mm,
        "height_mm": template.height_mm,
        "left_margin_mm": template.left_margin_mm,
        "right_margin_mm": template.right_margin_mm,
        "bottom_margin_mm": template.bottom_margin_mm,
        "top_margin_mm": template.top_margin_mm,
        "legend_mode": template.legend_mode,
        "axis_mode": template.axis_mode,
        "y_padding_top": template.y_padding_top,
        "y_padding_bottom": template.y_padding_bottom,
        "reverse_x": template.reverse_x,
        "show_markers": template.show_markers,
        "stack_mode": template.stack_mode,
        "stack_floor_fraction": template.stack_floor_fraction,
        "stack_gap_fraction": template.stack_gap_fraction,
        "series_label_mode": template.series_label_mode,
        "series_label_side": template.series_label_side,
        "label_track_inset_fraction": template.label_track_inset_fraction,
        "label_offset_pt": template.label_offset_pt,
        "baseline_mode": template.baseline_mode,
        "show_y_ticks": template.show_y_ticks,
        "preserve_stress_label": template_name == "tensile_curve",
    }
    params.update(overrides)
    return plot_curves(series_list, **params)  # type: ignore[arg-type]


def plot_frequency_sweep(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("frequency_sweep", series_list, **overrides)


def plot_temperature_sweep(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("temperature_sweep", series_list, **overrides)


def plot_stress_relaxation(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("stress_relaxation", series_list, **overrides)


def plot_tensile_curve(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("tensile_curve", series_list, **overrides)


def plot_ftir(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("ftir", series_list, **overrides)


def plot_nmr(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("nmr", series_list, **overrides)


def plot_xrd(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("xrd", series_list, **overrides)


def plot_dsc(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("dsc", series_list, **overrides)


def plot_tga(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("tga", series_list, **overrides)


def plot_dma(series_list: Sequence[CurveSeries], **overrides: object) -> tuple[plt.Figure, plt.Axes]:
    return plot_curve_template("dma", series_list, **overrides)
