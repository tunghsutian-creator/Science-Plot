from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from src import plot_style
from src.plotting_families.stats_family import plot_bar, plot_box, plot_point_error, plot_violin
from src.plotting_primitives import _apply_numeric_axis_tick_preferences, _format_axis_label
from src.rendering.cache import load_replicate_table_for_options
from src.rendering.common import (
    manual_axis_overrides,
    predict_bar_box_slug,
    summarize_replicate_distribution,
    validate_manual_axis_overrides,
)
from src.rendering.models import RenderedPlot, RenderOptions
from src.rendering.render_support import _rendered_plot_with_qa, _stats_profile
from src.rendering.series_order import reorder_replicate_groups, unknown_series_order_labels


def _ordered_groups(input_path: Path, sheet: str | int, options: RenderOptions):
    groups = reorder_replicate_groups(
        load_replicate_table_for_options(input_path, sheet, options),
        options.series_order,
    )
    unknown_groups = unknown_series_order_labels([group.group for group in groups], options.series_order)
    if unknown_groups:
        raise ValueError("series_order contains unknown group labels: " + ", ".join(unknown_groups))
    return groups


def _manual_y_override(options: RenderOptions) -> tuple[float | None, float | None] | None:
    _, y_override = manual_axis_overrides(options)
    return y_override


def _stats_raw_point_overlay_enabled(
    *,
    template: str,
    density_safe: bool,
) -> bool:
    if template in {"point_error", "lollipop_error"}:
        return density_safe
    if template == "box_strip":
        return True
    return False


def _render_bar(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    groups = _ordered_groups(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="bar")
    stats_profile = _stats_profile(groups)
    show_raw_points = _stats_raw_point_overlay_enabled(template="bar", density_safe=stats_profile.show_raw_points)
    fig, _ = plot_bar(
        groups,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        bar_width=stats_profile.bar_width,
        spacing_scale=stats_profile.spacing_scale,
        capsize=stats_profile.capsize,
        show_raw_points=show_raw_points,
        raw_point_size=stats_profile.raw_point_size,
        raw_point_alpha=stats_profile.raw_point_alpha,
        y_tick_density=options.y_tick_density,
        y_tick_edge_labels=options.y_tick_edge_labels,
        ylim=_manual_y_override(options),
    )
    if fig.axes:
        first = groups[0]
        fig.axes[0].set_ylabel(
            _format_axis_label(
                first.value_label,
                first.value_unit,
                override_label=options.y_label_override,
            )
        )
    return [
        _rendered_plot_with_qa(
            filename=f"{predict_bar_box_slug(groups)}_bar.pdf",
            figure=fig,
            template="bar",
            options=options,
            autofixes_applied=("stats_spacing_profile", "bar_capsize_profile"),
        )
    ]


def _render_box(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    groups = _ordered_groups(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="box")
    stats_profile = _stats_profile(groups)
    fig, _ = plot_box(
        groups,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        box_width=stats_profile.box_width,
        spacing_scale=stats_profile.spacing_scale,
        show_raw_points=False,
        show_fliers=False,
        y_tick_density=options.y_tick_density,
        y_tick_edge_labels=options.y_tick_edge_labels,
        ylim=_manual_y_override(options),
    )
    if fig.axes:
        first = groups[0]
        fig.axes[0].set_ylabel(
            _format_axis_label(
                first.value_label,
                first.value_unit,
                override_label=options.y_label_override,
            )
        )
    return [
        _rendered_plot_with_qa(
            filename=f"{predict_bar_box_slug(groups)}_box.pdf",
            figure=fig,
            template="box",
            options=options,
            autofixes_applied=("stats_spacing_profile",),
        )
    ]

def _render_violin(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    groups = _ordered_groups(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="violin")
    stats_profile = _stats_profile(groups)
    fig, _ = plot_violin(
        groups,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        violin_width=stats_profile.violin_width,
        spacing_scale=stats_profile.spacing_scale,
        y_tick_density=options.y_tick_density,
        y_tick_edge_labels=options.y_tick_edge_labels,
        ylim=_manual_y_override(options),
    )
    if fig.axes:
        first = groups[0]
        fig.axes[0].set_ylabel(
            _format_axis_label(
                first.value_label,
                first.value_unit,
                override_label=options.y_label_override,
            )
        )
    return [
        _rendered_plot_with_qa(
            filename=f"{predict_bar_box_slug(groups)}_violin.pdf",
            figure=fig,
            template="violin",
            options=options,
            autofixes_applied=("stats_spacing_profile",),
        )
    ]


def _render_point_error(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    groups = _ordered_groups(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="point_error")
    if not groups:
        raise ValueError("No valid groups were found in the replicate table.")
    stats_profile = _stats_profile(groups)
    fig, _ = plot_point_error(
        groups,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        point_spacing_width=max(0.22, stats_profile.bar_width * 0.85),
        spacing_scale=max(1.0, stats_profile.spacing_scale),
        capsize=stats_profile.capsize,
        marker_size_pt=max(4.2, plot_style.current_stroke().marker_size_pt * 0.9),
        show_raw_points=_stats_raw_point_overlay_enabled(
            template="point_error",
            density_safe=stats_profile.show_raw_points,
        ),
        raw_point_size=stats_profile.raw_point_size,
        raw_point_alpha=stats_profile.raw_point_alpha,
        y_tick_density=options.y_tick_density,
        y_tick_edge_labels=options.y_tick_edge_labels,
        ylim=_manual_y_override(options),
    )
    if fig.axes:
        first = groups[0]
        fig.axes[0].set_ylabel(
            _format_axis_label(
                first.value_label,
                first.value_unit,
                override_label=options.y_label_override,
            )
        )
    return [
        _rendered_plot_with_qa(
            filename=f"{predict_bar_box_slug(groups)}_point_error.pdf",
            figure=fig,
            template="point_error",
            options=options,
            autofixes_applied=(
                "stats_spacing_profile",
                "point_error_capsize_profile",
                "point_error_profile",
            )
            + (("point_error_raw_points_overlay",) if stats_profile.show_raw_points else ()),
        )
    ]

def _render_lollipop_error(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    groups = _ordered_groups(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="lollipop_error")
    if not groups:
        raise ValueError("No valid groups were found in the replicate table.")
    stats_profile = _stats_profile(groups)
    fig, ax = plot_point_error(
        groups,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        axis_mode="auto_positive",
        point_spacing_width=max(0.22, stats_profile.bar_width * 0.82),
        spacing_scale=max(1.0, stats_profile.spacing_scale),
        capsize=stats_profile.capsize,
        marker_size_pt=max(4.4, plot_style.current_stroke().marker_size_pt * 0.94),
        show_raw_points=_stats_raw_point_overlay_enabled(
            template="lollipop_error",
            density_safe=stats_profile.show_raw_points,
        ),
        raw_point_size=stats_profile.raw_point_size,
        raw_point_alpha=stats_profile.raw_point_alpha,
        y_tick_density=options.y_tick_density,
        y_tick_edge_labels=options.y_tick_edge_labels,
        ylim=_manual_y_override(options),
    )
    palette = plot_style.get_categorical_palette(n_colors=len(groups))
    means = np.array([float(group.data.mean()) for group in groups], dtype=float)
    positions = np.asarray(ax.get_xticks(), dtype=float)
    if positions.size != len(groups):
        positions = np.arange(len(groups), dtype=float)
    baseline = 0.0 if np.nanmin(means) >= 0.0 else float(ax.get_ylim()[0])
    if baseline < float(ax.get_ylim()[0]):
        ax.set_ylim(bottom=baseline)
    for pos, mean, color in zip(positions, means, palette, strict=True):
        ax.vlines(
            pos,
            baseline,
            mean,
            color=color,
            linewidth=max(0.95, plot_style.current_stroke().line_width_pt * 0.85),
            alpha=min(0.94, plot_style.current_stroke().line_alpha + 0.08),
            zorder=3.0,
        )
    first = groups[0]
    ax.set_ylabel(
        _format_axis_label(
            first.value_label,
            first.value_unit,
            override_label=options.y_label_override,
        )
    )
    return [
        _rendered_plot_with_qa(
            filename=f"{predict_bar_box_slug(groups)}_lollipop_error.pdf",
            figure=fig,
            template="lollipop_error",
            options=options,
            autofixes_applied=(
                "stats_spacing_profile",
                "point_error_capsize_profile",
                "lollipop_stem_overlay",
                "lollipop_error_profile",
            )
            + (("point_error_raw_points_overlay",) if stats_profile.show_raw_points else ()),
        )
    ]


def _emphasize_strip_point_overlay(
    ax: plt.Axes,
    *,
    min_size: float,
    min_alpha: float,
) -> None:
    for collection in ax.collections:
        sizes = np.asarray(collection.get_sizes(), dtype=float)
        if sizes.size:
            collection.set_sizes(np.maximum(sizes, min_size))
        collection.set_alpha(max(float(collection.get_alpha() or 0.0), min_alpha))
        collection.set_edgecolor("none")
        collection.set_linewidth(0.0)

def _overlay_violin_box_summary(
    ax: plt.Axes,
    *,
    groups,
    positions: np.ndarray,
    box_width: float,
) -> None:
    values = [group.data.to_numpy(dtype=float) for group in groups]
    box = ax.boxplot(
        values,
        positions=positions,
        widths=box_width,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "black", "linewidth": max(1.0, plot_style.current_stroke().line_width_pt)},
        whiskerprops={"linewidth": 0.95, "color": "black"},
        capprops={"linewidth": 0.95, "color": "black"},
        boxprops={"linewidth": 0.95, "color": "black"},
    )
    for patch in box["boxes"]:
        patch.set_facecolor("none")
        patch.set_alpha(1.0)
        patch.set_edgecolor("black")

def _render_box_strip(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    groups = _ordered_groups(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="box_strip")
    if not groups:
        raise ValueError("No valid groups were found in the replicate table.")
    stats_profile = _stats_profile(groups)
    fig, ax = plot_box(
        groups,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        box_width=stats_profile.box_width,
        spacing_scale=stats_profile.spacing_scale,
        show_raw_points=True,
        raw_point_size=stats_profile.raw_point_size,
        raw_point_alpha=stats_profile.raw_point_alpha,
        show_fliers=False,
        y_tick_density=options.y_tick_density,
        y_tick_edge_labels=options.y_tick_edge_labels,
        ylim=_manual_y_override(options),
    )
    _emphasize_strip_point_overlay(
        ax,
        min_size=max(stats_profile.raw_point_size, 11.0),
        min_alpha=max(stats_profile.raw_point_alpha, 0.82),
    )
    return [
        _rendered_plot_with_qa(
            filename=f"{predict_bar_box_slug(groups)}_box_strip.pdf",
            figure=fig,
            template="box_strip",
            options=options,
            autofixes_applied=(
                "stats_spacing_profile",
                "strip_point_overlay_emphasis",
                "box_strip_profile",
            ),
        )
    ]

def _render_violin_box(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    groups = _ordered_groups(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="violin_box")
    if not groups:
        raise ValueError("No valid groups were found in the replicate table.")
    stats_profile = _stats_profile(groups)
    fig, ax = plot_violin(
        groups,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        violin_width=stats_profile.violin_width,
        spacing_scale=stats_profile.spacing_scale,
        y_tick_density=options.y_tick_density,
        y_tick_edge_labels=options.y_tick_edge_labels,
        ylim=_manual_y_override(options),
    )
    positions = np.asarray(ax.get_xticks(), dtype=float)
    if positions.size == len(groups):
        _overlay_violin_box_summary(
            ax,
            groups=groups,
            positions=positions,
            box_width=max(0.16, stats_profile.violin_width * 0.42),
        )
    return [
        _rendered_plot_with_qa(
            filename=f"{predict_bar_box_slug(groups)}_violin_box.pdf",
            figure=fig,
            template="violin_box",
            options=options,
            autofixes_applied=(
                "stats_spacing_profile",
                "violin_box_overlay",
                "violin_box_profile",
            ),
        )
    ]

def _gaussian_density(values: np.ndarray, x_grid: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return np.zeros_like(x_grid)
    std = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    iqr = float(np.subtract(*np.percentile(values, [75, 25]))) if values.size > 1 else 0.0
    robust_scale = min(std, iqr / 1.34) if std > 0 and iqr > 0 else max(std, iqr / 1.34, 0.0)
    if robust_scale <= 0:
        robust_scale = max(abs(float(values.mean())), 1.0) * 0.08
    bandwidth = max(1e-6, 1.06 * robust_scale * (values.size ** (-1.0 / 5.0)))
    z = (x_grid[:, None] - values[None, :]) / bandwidth
    kernel = np.exp(-0.5 * z * z) / np.sqrt(2.0 * np.pi)
    return kernel.mean(axis=1) / bandwidth


def _finite_group_values(groups) -> list[np.ndarray]:
    all_values: list[np.ndarray] = []
    for group in groups:
        values = group.data.to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if values.size:
            all_values.append(values)
    if not all_values:
        raise ValueError("No valid groups were found in the replicate table.")
    return all_values


def _density_x_grid(values: np.ndarray) -> np.ndarray:
    x_min = float(values.min())
    x_max = float(values.max())
    if np.isclose(x_min, x_max):
        span = max(abs(x_min), 1.0) * 0.08
        return np.linspace(x_min - span, x_max + span, 160)
    return np.linspace(x_min, x_max, 160)


def _render_histogram_density(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    groups = _ordered_groups(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="histogram_density")
    if not groups:
        raise ValueError("No valid groups were found in the replicate table.")

    summary = summarize_replicate_distribution(groups)
    fig, ax = plot_style.create_panel_figure(width_mm=options.width_mm, height_mm=options.height_mm)
    palette = plot_style.get_categorical_palette(options.palette_preset, n_colors=len(groups))
    all_values = _finite_group_values(groups)
    density_max = 0.0

    pooled = np.concatenate(all_values)
    if summary.pooled_unique_count <= max(6, int(round(summary.total_points * 0.35))):
        bin_count = int(max(4, min(18, summary.pooled_unique_count + 1)))
        discrete_binning = True
    else:
        bin_count = int(min(24, max(8, round(np.sqrt(max(pooled.size, 1))))))
        discrete_binning = False

    for color, group, values in zip(palette, groups, all_values, strict=True):
        ax.hist(
            values,
            bins=bin_count,
            density=True,
            alpha=min(plot_style.current_stroke().fill_alpha, 0.28),
            color=color,
            edgecolor=color,
            linewidth=0.8,
            label=group.group,
        )
        x_grid = _density_x_grid(values)
        density = _gaussian_density(values, x_grid)
        density_max = max(density_max, float(np.max(density)) if density.size else 0.0)
        ax.plot(
            x_grid,
            density,
            color=color,
            linewidth=max(1.0, plot_style.current_stroke().line_width_pt),
            alpha=min(0.96, plot_style.current_stroke().line_alpha + 0.15),
            zorder=3.4,
        )

    first = groups[0]
    ax.set_xlabel(
        _format_axis_label(
            first.value_label,
            first.value_unit,
            override_label=options.x_label_override,
        )
    )
    ax.set_ylabel("Density")
    if len(groups) > 1:
        ax.legend(loc="best", frameon=False)
    if density_max > 0:
        ax.set_ylim(bottom=0.0, top=density_max * 1.16)
    else:
        ax.set_ylim(bottom=0.0)

    x_override, y_override = manual_axis_overrides(options)
    if x_override is not None:
        x_low, x_high = ax.get_xlim()
        ax.set_xlim(
            x_override[0] if x_override[0] is not None else x_low,
            x_override[1] if x_override[1] is not None else x_high,
        )
    if y_override is not None:
        y_low, y_high = ax.get_ylim()
        ax.set_ylim(
            y_override[0] if y_override[0] is not None else y_low,
            y_override[1] if y_override[1] is not None else y_high,
        )
    _apply_numeric_axis_tick_preferences(
        ax.xaxis,
        scale="linear",
        tick_density=options.x_tick_density,
        tick_edge_labels=options.x_tick_edge_labels,
    )
    _apply_numeric_axis_tick_preferences(
        ax.yaxis,
        scale="linear",
        tick_density=options.y_tick_density,
        tick_edge_labels=options.y_tick_edge_labels,
        max_major_ticks=7,
    )

    autofixes = ["histogram_density_overlay"]
    if discrete_binning:
        autofixes.append("histogram_discrete_binning")

    return [
        _rendered_plot_with_qa(
            filename=f"{predict_bar_box_slug(groups)}_histogram_density.pdf",
            figure=fig,
            template="histogram_density",
            options=options,
            autofixes_applied=tuple(autofixes),
        )
    ]


def _render_density_area(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    groups = _ordered_groups(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="density_area")
    if not groups:
        raise ValueError("No valid groups were found in the replicate table.")

    fig, ax = plot_style.create_panel_figure(width_mm=options.width_mm, height_mm=options.height_mm)
    palette = plot_style.get_categorical_palette(options.palette_preset, n_colors=len(groups))
    all_values = _finite_group_values(groups)
    density_max = 0.0

    for color, group, values in zip(palette, groups, all_values, strict=True):
        x_grid = _density_x_grid(values)
        density = _gaussian_density(values, x_grid)
        density_max = max(density_max, float(np.max(density)) if density.size else 0.0)
        ax.fill_between(
            x_grid,
            density,
            0.0,
            color=color,
            alpha=min(plot_style.current_stroke().fill_alpha, 0.28),
            linewidth=0.0,
            zorder=2.8,
        )
        ax.plot(
            x_grid,
            density,
            color=color,
            linewidth=max(1.0, plot_style.current_stroke().line_width_pt),
            alpha=min(0.96, plot_style.current_stroke().line_alpha + 0.15),
            label=group.group,
            zorder=3.4,
        )

    first = groups[0]
    ax.set_xlabel(
        _format_axis_label(
            first.value_label,
            first.value_unit,
            override_label=options.x_label_override,
        )
    )
    ax.set_ylabel("Density")
    if len(groups) > 1:
        ax.legend(loc="best", frameon=False)
    if density_max > 0:
        ax.set_ylim(bottom=0.0, top=density_max * 1.16)
    else:
        ax.set_ylim(bottom=0.0)

    x_override, y_override = manual_axis_overrides(options)
    if x_override is not None:
        x_low, x_high = ax.get_xlim()
        ax.set_xlim(
            x_override[0] if x_override[0] is not None else x_low,
            x_override[1] if x_override[1] is not None else x_high,
        )
    if y_override is not None:
        y_low, y_high = ax.get_ylim()
        ax.set_ylim(
            y_override[0] if y_override[0] is not None else y_low,
            y_override[1] if y_override[1] is not None else y_high,
        )
    _apply_numeric_axis_tick_preferences(
        ax.xaxis,
        scale="linear",
        tick_density=options.x_tick_density,
        tick_edge_labels=options.x_tick_edge_labels,
    )
    _apply_numeric_axis_tick_preferences(
        ax.yaxis,
        scale="linear",
        tick_density=options.y_tick_density,
        tick_edge_labels=options.y_tick_edge_labels,
        max_major_ticks=7,
    )

    return [
        _rendered_plot_with_qa(
            filename=f"{predict_bar_box_slug(groups)}_density_area.pdf",
            figure=fig,
            template="density_area",
            options=options,
            autofixes_applied=("density_area_overlay",),
        )
    ]
