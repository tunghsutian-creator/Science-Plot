from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from src.plotting_families.curve_family import plot_curves
from src.plotting_primitives import _format_axis_label
from src.rendering.cache import (
    load_curve_table_for_options,
    load_heatmap_table_for_options,
    read_raw_table_for_options,
)
from src.rendering.common import validate_manual_axis_overrides, validate_series_scales
from src.rendering.datagraph_inputs import series_looks_polar, table_figure_size_error, theta_values_for_plot
from src.rendering.models import RenderedPlot, RenderOptions
from src.rendering.render_support import _rendered_plot_with_qa
from src.rendering.series_order import filter_curve_series, reorder_curve_series, unknown_series_order_labels

from src import plot_style


def _display_cell(value: object) -> str:
    return "" if pd.isna(value) else str(value)


def _apply_axis_scales_and_labels(ax: plt.Axes, *, options: RenderOptions) -> None:
    ax.set_xscale(options.xscale)
    ax.set_yscale(options.yscale)
    if options.x_min is not None or options.x_max is not None:
        left, right = ax.get_xlim()
        ax.set_xlim(
            options.x_min if options.x_min is not None else left,
            options.x_max if options.x_max is not None else right,
        )
    if options.y_min is not None or options.y_max is not None:
        bottom, top = ax.get_ylim()
        ax.set_ylim(
            options.y_min if options.y_min is not None else bottom,
            options.y_max if options.y_max is not None else top,
        )
    if options.reverse_x:
        ax.invert_xaxis()


def _panel_figure(*, options: RenderOptions) -> tuple[plt.Figure, plt.Axes]:
    return plot_style.create_panel_figure(width_mm=options.width_mm, height_mm=options.height_mm)


def _polar_figure(*, options: RenderOptions) -> tuple[plt.Figure, plt.Axes]:
    spacing = plot_style.current_spacing()
    width_mm = options.width_mm
    height_mm = options.height_mm
    fig, ax = plt.subplots(
        figsize=(plot_style.mm_to_inch(width_mm), plot_style.mm_to_inch(height_mm)),
        subplot_kw={"projection": "polar"},
        constrained_layout=False,
    )
    fig.subplots_adjust(
        left=spacing.left_margin_mm / width_mm,
        right=1 - spacing.right_margin_mm / width_mm,
        bottom=spacing.bottom_margin_mm / height_mm,
        top=1 - spacing.top_margin_mm / height_mm,
    )
    return fig, ax


def _filter_and_order_curve_series(series_list, options: RenderOptions):
    unknown_include = unknown_series_order_labels(
        [series.sample for series in series_list],
        options.series_include,
    )
    if unknown_include:
        raise ValueError("series_include contains unknown series labels: " + ", ".join(unknown_include))
    selected = filter_curve_series(series_list, options.series_include)
    if not selected and options.series_include:
        raise ValueError("series_include did not match any series.")
    unknown_order = unknown_series_order_labels(
        [series.sample for series in selected],
        options.series_order,
    )
    if unknown_order:
        raise ValueError("series_order contains unknown series labels: " + ", ".join(unknown_order))
    return reorder_curve_series(selected, options.series_order)


def _load_filter_and_order_curve_series(input_path: Path, sheet: str | int, options: RenderOptions):
    return _filter_and_order_curve_series(load_curve_table_for_options(input_path, sheet, options), options)


def _render_function_curve(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_series_scales(series_list, xscale=options.xscale, yscale=options.yscale)
    validate_manual_axis_overrides(options, template="function_curve")
    fig, ax = plot_curves(
        series_list,
        show_markers=False,
        axis_mode="auto",
        xscale=options.xscale,
        yscale=options.yscale,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        reverse_x=options.reverse_x,
        legend_mode="inside_best",
        xlim=(options.x_min, options.x_max) if options.x_min is not None or options.x_max is not None else None,
        ylim=(options.y_min, options.y_max) if options.y_min is not None or options.y_max is not None else None,
        x_tick_density=options.x_tick_density,
        y_tick_density=options.y_tick_density,
        x_tick_edge_labels=options.x_tick_edge_labels,
        y_tick_edge_labels=options.y_tick_edge_labels,
    )
    ax.set_xlabel(
        _format_axis_label(
            series_list[0].x_label,
            series_list[0].x_unit,
            override_label=options.x_label_override,
        )
    )
    ax.set_ylabel(
        _format_axis_label(
            series_list[0].y_label,
            series_list[0].y_unit,
            override_label=options.y_label_override,
        )
    )
    return [
        _rendered_plot_with_qa(
            filename=f"{input_path.stem}_function_curve.pdf",
            figure=fig,
            template="function_curve",
            options=options,
        )
    ]


def _render_contour_field(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    table = load_heatmap_table_for_options(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="contour_field")
    fig, ax = _panel_figure(options=options)
    data = table.data.dropna(subset=["x", "y", "z"])
    if data.empty:
        raise ValueError("Contour field requires finite X/Y/Z values.")
    x_values = data["x"].to_numpy(dtype=float)
    y_values = data["y"].to_numpy(dtype=float)
    z_values = data["z"].to_numpy(dtype=float)
    finite = np.isfinite(x_values) & np.isfinite(y_values) & np.isfinite(z_values)
    if finite.sum() < 3:
        raise ValueError("Contour field requires at least three finite X/Y/Z points.")
    contour = ax.tricontourf(
        x_values[finite],
        y_values[finite],
        z_values[finite],
        levels=12,
        cmap=plot_style.get_sequential_cmap(options.palette_preset),
    )
    ax.tricontour(
        x_values[finite],
        y_values[finite],
        z_values[finite],
        levels=12,
        colors="black",
        linewidths=0.25,
        alpha=0.55,
    )
    if options.show_colorbar:
        colorbar = fig.colorbar(contour, ax=ax, fraction=0.05, pad=0.03)
        colorbar.set_label(_format_axis_label(table.z_label, table.z_unit))
    ax.set_xlabel(_format_axis_label(table.x_label, table.x_unit, override_label=options.x_label_override))
    ax.set_ylabel(_format_axis_label(table.y_label, table.y_unit, override_label=options.y_label_override))
    _apply_axis_scales_and_labels(ax, options=options)
    return [
        _rendered_plot_with_qa(
            filename=f"{input_path.stem}_contour_field.pdf",
            figure=fig,
            template="contour_field",
            options=options,
            autofixes_applied=("contour_field_levels",),
        )
    ]


def _render_polar_curve(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="polar_curve")
    if not series_looks_polar(series_list):
        raise ValueError("Polar curve requires theta/radius columns with radian or degree theta units.")
    fig, ax = _polar_figure(options=options)
    colors = plot_style.get_categorical_palette(options.palette_preset, n_colors=len(series_list))
    for index, series in enumerate(series_list):
        data = series.data.dropna(subset=["x", "y"])
        if data.empty:
            continue
        ax.plot(
            theta_values_for_plot(data["x"], unit=series.x_unit),
            data["y"].to_numpy(dtype=float),
            label=series.sample,
            color=colors[index],
        )
    if not ax.lines:
        raise ValueError("Polar curve requires at least one finite theta/r series.")
    ax.set_xlabel(
        _format_axis_label(
            series_list[0].x_label,
            series_list[0].x_unit,
            override_label=options.x_label_override,
        )
    )
    ax.set_ylabel(
        _format_axis_label(
            series_list[0].y_label,
            series_list[0].y_unit,
            override_label=options.y_label_override,
        )
    )
    if len(series_list) > 1:
        ax.legend(loc="upper right", bbox_to_anchor=(1.12, 1.12))
    return [
        _rendered_plot_with_qa(
            filename=f"{input_path.stem}_polar_curve.pdf",
            figure=fig,
            template="polar_curve",
            options=options,
            autofixes_applied=("polar_projection",),
        )
    ]


def _render_table_figure(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    raw = read_raw_table_for_options(input_path, sheet, options).dropna(how="all").dropna(axis=1, how="all")
    if raw.empty:
        raise ValueError("Table figure requires at least one visible row and column.")
    if size_error := table_figure_size_error(raw):
        raise ValueError(size_error)
    preview = raw.iloc[:12, :8].copy()
    display = preview.map(_display_cell) if hasattr(preview, "map") else preview.applymap(_display_cell)
    fig, ax = _panel_figure(options=options)
    ax.axis("off")
    table = ax.table(
        cellText=display.iloc[1:].values if display.shape[0] > 1 else display.values,
        colLabels=display.iloc[0].tolist() if display.shape[0] > 1 else None,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(6.0)
    table.scale(1.0, 1.15)
    for (row, _), cell in table.get_celld().items():
        cell.set_linewidth(0.25)
        if row == 0 and display.shape[0] > 1:
            cell.set_text_props(weight="bold")
            cell.set_facecolor("#f2f2f2")
    return [
        _rendered_plot_with_qa(
            filename=f"{input_path.stem}_table_figure.pdf",
            figure=fig,
            template="table_figure",
            options=options,
            autofixes_applied=("table_figure_compact",),
        )
    ]


__all__ = [
    "_render_contour_field",
    "_render_function_curve",
    "_render_polar_curve",
    "_render_table_figure",
]
