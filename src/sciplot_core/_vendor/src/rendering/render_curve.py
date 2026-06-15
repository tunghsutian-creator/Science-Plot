from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from src.plotting_curve_support import compute_shared_curve_x_layout
from src.plotting_families.curve_family import plot_curves, plot_scatter
from src.plotting_families.spectral_family import plot_wide_nmr
from src.plotting_primitives import (
    MAX_VISIBLE_Y_MAJOR_TICKS,
    _apply_major_ticks_with_override,
    _apply_numeric_axis_tick_preferences,
    _format_axis_label,
    compute_axis_limits,
)
from src.rendering.advanced_plot_axes import mark_extra_axis, mark_primary_axis
from src.rendering.cache import load_curve_table_for_options
from src.rendering.common import (
    aligned_replicate_band,
    load_rheology_bundle_series,
    load_segmented_config,
    looks_like_tensile_curve,
    manual_axis_overrides,
    merge_axis_override_bounds,
    rheology_output_filenames,
    validate_manual_axis_overrides,
    validate_series_scales,
)
from src.rendering.dataset_models import build_normalized_dataset
from src.rendering.extra_axes import (
    extra_axis_binding_mode,
    extra_axis_label,
    extra_axis_series_ids,
    normalize_series_selection_ids,
)
from src.rendering.fit_analysis import fit_linear_series_list, fit_options_from_payload, fit_series_list
from src.rendering.models import RenderedPlot, RenderOptions, TemplateName
from src.rendering.qa import apply_curve_autofix
from src.rendering.render_curve_support import (
    _apply_compact_inside_legend,
    _compact_curve_fix,
    _curve_candidate_key,
    _curve_dense_fix,
    _ensure_direct_labels,
    _float_plot_kw,
    _merge_curve_fixes,
    _post_curve_fix,
    _prefer_compact_legend,
    _prefer_direct_labels,
)
from src.rendering.render_support import _rendered_plot_with_qa
from src.rendering.series_offsets import series_offset_by_id
from src.rendering.series_order import filter_curve_series, reorder_curve_series, unknown_series_order_labels
from src.rendering.series_styles import matplotlib_marker_symbol, series_style_by_id

from src import plot_style


@dataclass(frozen=True)
class SecondaryYAxisBinding:
    position: str
    series_ids: tuple[str, ...]
    axis_label: str


def _series_ids_for_series_list(series_list) -> tuple[str, ...]:
    return normalize_series_selection_ids(series.sample for series in series_list)


def _resolve_secondary_y_axis_binding(
    *,
    template: str,
    series_list,
    options: RenderOptions,
    preserve_stress_label: bool,
) -> SecondaryYAxisBinding | None:
    if template not in {"curve", "point_line", "scatter"}:
        return None
    payload = cast(Mapping[str, Any] | None, options.extra_y_axis)
    if payload is None or not bool(payload.get("enabled", False)):
        return None
    if extra_axis_binding_mode(payload) != "series_assignment":
        return None

    available_ids = _series_ids_for_series_list(series_list)
    requested_ids = set(extra_axis_series_ids(payload))
    assigned_ids = tuple(series_id for series_id in available_ids if series_id in requested_ids)
    if not assigned_ids or len(assigned_ids) >= len(available_ids):
        return None

    secondary_label = extra_axis_label(payload)
    if secondary_label:
        return SecondaryYAxisBinding(
            position=str(payload.get("position", "right")),
            series_ids=assigned_ids,
            axis_label=secondary_label,
        )

    first_secondary = series_list[available_ids.index(assigned_ids[0])]
    return SecondaryYAxisBinding(
        position=str(payload.get("position", "right")),
        series_ids=assigned_ids,
        axis_label=_format_axis_label(
            first_secondary.y_label,
            first_secondary.y_unit,
            preserve_stress_label=preserve_stress_label,
        ),
    )


def _apply_curve_axis_labels(ax, first, options: RenderOptions, *, preserve_stress_label: bool) -> None:
    ax.set_xlabel(
        _format_axis_label(
            first.x_label,
            first.x_unit,
            override_label=options.x_label_override,
        )
    )
    ax.set_ylabel(
        _format_axis_label(
            first.y_label,
            first.y_unit,
            preserve_stress_label=preserve_stress_label,
            override_label=options.y_label_override,
        )
    )


def _curve_artist_color(artist, *, scatter: bool) -> object:
    if scatter:
        colors = artist.get_facecolors()
        if len(colors):
            return tuple(colors[0])
    return artist.get_color()


def _styleable_series_artists(ax: Axes, *, scatter: bool) -> list[Any]:
    if scatter:
        return [collection for collection in ax.collections if np.asarray(collection.get_offsets()).size]
    return list(ax.lines)


def _rebuild_visible_legend(ax: Axes) -> None:
    legend = ax.get_legend()
    if legend is None:
        return
    loc = getattr(legend, "_loc", "best")
    handles, labels = ax.get_legend_handles_labels()
    visible_items = [
        (handle, label)
        for handle, label in zip(handles, labels, strict=False)
        if label and not label.startswith("_") and getattr(handle, "get_visible", lambda: True)()
    ]
    legend.remove()
    if visible_items:
        visible_handles, visible_labels = zip(*visible_items, strict=True)
        ax.legend(list(visible_handles), list(visible_labels), loc=loc)


def _apply_series_style_overrides(
    ax: Axes,
    *,
    series_list,
    options: RenderOptions,
    scatter: bool,
) -> tuple[str, ...]:
    styles = series_style_by_id(options.series_styles)
    if not styles:
        return ()
    series_ids = _series_ids_for_series_list(series_list)
    artists = _styleable_series_artists(ax, scatter=scatter)
    applied = False

    for series_id, artist in zip(series_ids, artists, strict=False):
        style = styles.get(series_id)
        if style is None:
            continue
        artist.set_visible(bool(style.get("enabled", True)))
        color = style.get("color")
        if color:
            if scatter:
                artist.set_facecolor(color)
                artist.set_edgecolor(color)
            else:
                artist.set_color(color)
                artist.set_markerfacecolor(color)
                artist.set_markeredgecolor(color)
        line_width = style.get("line_width")
        if line_width is not None:
            if scatter:
                artist.set_linewidths([float(line_width)])
            else:
                artist.set_linewidth(float(line_width))
        marker = matplotlib_marker_symbol(style.get("marker"))
        if marker is not None and not scatter and hasattr(artist, "set_marker"):
            artist.set_marker(marker)
        applied = True

    if applied:
        _rebuild_visible_legend(ax)
        return ("series_style_overrides",)
    return ()


def _apply_series_offsets(
    ax: Axes,
    *,
    series_list,
    options: RenderOptions,
    scatter: bool,
) -> tuple[str, ...]:
    offsets = series_offset_by_id(options.series_offsets)
    if not offsets:
        return ()
    series_ids = _series_ids_for_series_list(series_list)
    artists = _styleable_series_artists(ax, scatter=scatter)
    applied = False

    for series_id, artist in zip(series_ids, artists, strict=False):
        offset = offsets.get(series_id)
        if offset is None or not bool(offset.get("enabled", True)):
            continue
        try:
            x_offset = float(offset.get("x_offset", 0.0))
            y_offset = float(offset.get("y_offset", 0.0))
        except (TypeError, ValueError):
            continue
        if not np.isfinite(x_offset) or not np.isfinite(y_offset) or (x_offset == 0.0 and y_offset == 0.0):
            continue
        if scatter:
            points = np.asarray(artist.get_offsets(), dtype=float)
            if points.size == 0:
                continue
            shifted = np.array(points, copy=True)
            shifted[:, 0] = shifted[:, 0] + x_offset
            shifted[:, 1] = shifted[:, 1] + y_offset
            artist.set_offsets(shifted)
        else:
            x_data = np.asarray(artist.get_xdata(), dtype=float)
            y_data = np.asarray(artist.get_ydata(), dtype=float)
            artist.set_xdata(x_data + x_offset)
            artist.set_ydata(y_data + y_offset)
        applied = True

    if applied:
        ax.relim()
        ax.autoscale_view()
        _rebuild_visible_legend(ax)
        return ("series_offsets",)
    return ()


def _configure_secondary_y_axis(primary_ax: Axes, secondary_ax: Axes, *, position: str) -> None:
    if position == "left":
        primary_ax.yaxis.set_label_position("right")
        primary_ax.yaxis.tick_right()
        primary_ax.spines["right"].set_visible(True)
        primary_ax.spines["left"].set_visible(False)

        secondary_ax.yaxis.set_label_position("left")
        secondary_ax.yaxis.tick_left()
        secondary_ax.spines["left"].set_position(("axes", 0.0))
        secondary_ax.spines["left"].set_visible(True)
        secondary_ax.spines["right"].set_visible(False)
        return

    primary_ax.yaxis.set_label_position("left")
    primary_ax.yaxis.tick_left()
    primary_ax.spines["left"].set_visible(True)
    primary_ax.spines["right"].set_visible(False)

    secondary_ax.yaxis.set_label_position("right")
    secondary_ax.yaxis.tick_right()
    secondary_ax.spines["right"].set_visible(True)
    secondary_ax.spines["left"].set_visible(False)


def _apply_secondary_y_axis_limits(
    ax: Axes,
    *,
    series_list,
    options: RenderOptions,
    axis_mode: str,
    scatter: bool,
    y_padding_top: float,
    y_padding_bottom: float,
) -> None:
    limits = compute_axis_limits(
        [series.data["y"].to_numpy() for series in series_list],
        kind="line",
        axis_mode=axis_mode,
        legend_mode="none",
        x_values=[series.data["x"].to_numpy() for series in series_list],
        xscale=options.xscale,
        yscale=options.yscale,
        y_padding_top=y_padding_top,
        y_padding_bottom=y_padding_bottom,
    )
    ax.set_yscale(options.yscale)
    ax.set_ylim(*limits.ylim)
    _apply_major_ticks_with_override(
        ax.yaxis,
        policy_ticks=limits.y_tick_policy.major_ticks if limits.y_tick_policy is not None else None,
        override=None,
        scale=options.yscale,
        max_major_ticks=MAX_VISIBLE_Y_MAJOR_TICKS,
    )
    _apply_numeric_axis_tick_preferences(
        ax.yaxis,
        scale=options.yscale,
        tick_density=options.y_tick_density,
        tick_edge_labels=options.y_tick_edge_labels,
        max_major_ticks=MAX_VISIBLE_Y_MAJOR_TICKS,
    )


def _rebind_secondary_y_axis_series(
    rendered: RenderedPlot,
    *,
    template: str,
    series_list,
    options: RenderOptions,
    scatter: bool,
    base_kwargs: dict[str, object],
    secondary_binding: SecondaryYAxisBinding,
) -> tuple[RenderedPlot, Mapping[str, Axes], Mapping[str, object]]:
    primary_ax = rendered.figure.axes[0]
    mark_primary_axis(primary_ax)
    series_ids = _series_ids_for_series_list(series_list)
    assigned_ids = set(secondary_binding.series_ids)
    artist_sequence = (
        [collection for collection in primary_ax.collections if np.asarray(collection.get_offsets()).size]
        if scatter
        else list(primary_ax.lines)
    )
    if len(artist_sequence) < len(series_list):
        return rendered, {}, {}

    secondary_ax = primary_ax.twinx()
    mark_extra_axis(secondary_ax, axis_name="y")
    secondary_ax.set_zorder(primary_ax.get_zorder() + 0.1)
    secondary_ax.patch.set_alpha(0.0)
    secondary_ax.set_xscale(primary_ax.get_xscale())
    secondary_ax.set_xlim(primary_ax.get_xlim())
    if primary_ax.xaxis_inverted():
        secondary_ax.invert_xaxis()

    axis_mode = str(base_kwargs.get("axis_mode", "auto"))
    y_padding_top = _float_plot_kw(base_kwargs, "y_padding_top", 0.12 if scatter else 0.18)
    y_padding_bottom = _float_plot_kw(base_kwargs, "y_padding_bottom", 0.06)
    preserve_stress_label = bool(base_kwargs.get("preserve_stress_label", False))

    series_axes: dict[str, Axes] = {}
    series_colors: dict[str, object] = {}
    primary_handles: list[object] = []
    secondary_handles: list[object] = []
    primary_series = []
    secondary_series = []

    for series_id, series, artist in zip(series_ids, series_list, artist_sequence, strict=False):
        color = _curve_artist_color(artist, scatter=scatter)
        if series_id in assigned_ids:
            if scatter:
                offsets = np.asarray(artist.get_offsets())
                sizes = artist.get_sizes()
                secondary_artist = secondary_ax.scatter(
                    offsets[:, 0],
                    offsets[:, 1],
                    label=artist.get_label(),
                    color=color,
                    s=float(sizes[0]) if len(sizes) else 14.0,
                    alpha=artist.get_alpha(),
                    linewidths=artist.get_linewidths(),
                    zorder=artist.get_zorder(),
                )
            else:
                secondary_artist = secondary_ax.plot(
                    artist.get_xdata(),
                    artist.get_ydata(),
                    label=artist.get_label(),
                    color=color,
                    linewidth=artist.get_linewidth(),
                    linestyle=artist.get_linestyle(),
                    alpha=artist.get_alpha(),
                    drawstyle=artist.get_drawstyle(),
                    marker=artist.get_marker(),
                    markersize=artist.get_markersize(),
                    markerfacecolor=artist.get_markerfacecolor(),
                    markeredgecolor=artist.get_markeredgecolor(),
                    markeredgewidth=artist.get_markeredgewidth(),
                    markevery=artist.get_markevery(),
                    zorder=artist.get_zorder(),
                )[0]
            secondary_handles.append(secondary_artist)
            secondary_series.append(series)
            series_axes[series_id] = secondary_ax
            series_colors[series_id] = color
            artist.remove()
        else:
            primary_handles.append(artist)
            primary_series.append(series)
            series_axes[series_id] = primary_ax
            series_colors[series_id] = color

    legend = primary_ax.get_legend()
    if legend is not None:
        legend.remove()

    if not primary_series or not secondary_series:
        secondary_ax.remove()
        return rendered, {}, {}

    _configure_secondary_y_axis(primary_ax, secondary_ax, position=secondary_binding.position)
    _apply_curve_axis_labels(
        primary_ax,
        primary_series[0],
        options,
        preserve_stress_label=preserve_stress_label,
    )
    _apply_secondary_y_axis_limits(
        primary_ax,
        series_list=primary_series,
        options=options,
        axis_mode=axis_mode,
        scatter=scatter,
        y_padding_top=y_padding_top,
        y_padding_bottom=y_padding_bottom,
    )
    _apply_secondary_y_axis_limits(
        secondary_ax,
        series_list=secondary_series,
        options=options,
        axis_mode=axis_mode,
        scatter=scatter,
        y_padding_top=y_padding_top,
        y_padding_bottom=y_padding_bottom,
    )
    secondary_ax.set_ylabel(secondary_binding.axis_label)

    combined_handles: list[Any] = []
    combined_labels = []
    primary_map: dict[str, Any] = {
        series_id: handle
        for series_id, handle in zip(
            [series_id for series_id in series_ids if series_id not in assigned_ids],
            primary_handles,
            strict=True,
        )
    }
    secondary_map: dict[str, Any] = {
        series_id: handle
        for series_id, handle in zip(secondary_binding.series_ids, secondary_handles, strict=True)
    }
    for series_id in series_ids:
        handle = secondary_map.get(series_id) if series_id in assigned_ids else primary_map.get(series_id)
        if handle is None:
            continue
        combined_handles.append(handle)
        combined_labels.append(handle.get_label())
    if combined_handles:
        primary_ax.legend(combined_handles, combined_labels, loc="upper right")

    return (
        _rendered_plot_with_qa(
            filename=rendered.filename,
            figure=rendered.figure,
            template=template,
            options=options,
            autofixes_applied=(
                tuple(rendered.qa_report.autofixes_applied) if rendered.qa_report is not None else ()
            )
            + ("extra_axis_series_assignment",),
        ),
        series_axes,
        series_colors,
    )


def _fit_overlay_axis_bindings(
    rendered: RenderedPlot,
    *,
    series_list,
    scatter: bool,
    secondary_binding: SecondaryYAxisBinding | None,
) -> tuple[Mapping[str, Axes], Mapping[str, object]]:
    if secondary_binding is None or len(rendered.figure.axes) < 2:
        return {}, {}

    series_ids = _series_ids_for_series_list(series_list)
    assigned_ids = set(secondary_binding.series_ids)
    primary_ax = rendered.figure.axes[0]
    secondary_ax = rendered.figure.axes[1]
    primary_artists = (
        [collection for collection in primary_ax.collections if np.asarray(collection.get_offsets()).size]
        if scatter
        else list(primary_ax.lines)
    )
    secondary_artists = (
        [collection for collection in secondary_ax.collections if np.asarray(collection.get_offsets()).size]
        if scatter
        else list(secondary_ax.lines)
    )

    series_axes: dict[str, Axes] = {}
    series_colors: dict[str, object] = {}
    primary_iter = iter(primary_artists)
    secondary_iter = iter(secondary_artists)
    for series_id in series_ids:
        if series_id in assigned_ids:
            artist = next(secondary_iter, None)
            if artist is None:
                continue
            series_axes[series_id] = secondary_ax
            series_colors[series_id] = _curve_artist_color(artist, scatter=scatter)
            continue
        artist = next(primary_iter, None)
        if artist is None:
            continue
        series_axes[series_id] = primary_ax
        series_colors[series_id] = _curve_artist_color(artist, scatter=scatter)
    return series_axes, series_colors


def _render_curve_candidate(
    *,
    filename: str,
    template: str,
    series_list,
    options: RenderOptions,
    show_markers: bool,
    scatter: bool,
    direct_label_side: str | None,
    legend_variant: str,
    base_kwargs: dict[str, object],
) -> tuple[RenderedPlot, str]:
    combined_fix = _merge_curve_fixes(
        _curve_dense_fix(series_list, show_markers=show_markers, scatter=scatter),
        _compact_curve_fix(options),
    )
    compact_legend = legend_variant == "compact"
    strategy = (
        "compact_legend"
        if compact_legend
        else "legend"
        if direct_label_side is None
        else f"direct_{direct_label_side}"
    )
    autofixes = list(combined_fix.autofixes_applied)
    if direct_label_side is not None:
        autofixes.append("direct_series_labels")
    if compact_legend:
        autofixes.append("compact_inside_legend")
    forced_legend_mode = _legend_mode_for_position(
        cast(str | None, base_kwargs.get("legend_position", options.legend_position))
    )
    resolved_xscale = str(base_kwargs.get("xscale", options.xscale))
    resolved_yscale = str(base_kwargs.get("yscale", options.yscale))
    resolved_x_tick_density = cast(str | None, base_kwargs.get("x_tick_density", options.x_tick_density))
    resolved_y_tick_density = cast(str | None, base_kwargs.get("y_tick_density", options.y_tick_density))

    if scatter:
        fig, ax = plot_scatter(
            series_list,
            axis_mode=str(base_kwargs.get("axis_mode", "auto")),
            xscale=resolved_xscale,
            yscale=resolved_yscale,
            width_mm=options.width_mm,
            height_mm=options.height_mm,
            reverse_x=options.reverse_x,
            legend_mode=(
                "none"
                if direct_label_side is not None or compact_legend
                else forced_legend_mode
            ),
            legend_expand_axes=str(base_kwargs.get("legend_expand_axes", "xy")),
            marker_size=14.0
            * (combined_fix.collection_size_scale if combined_fix.collection_size_scale != 1.0 else 1.0),
            visible_xticks=base_kwargs.get("visible_xticks"),
            x_tick_density=resolved_x_tick_density,
            y_tick_density=resolved_y_tick_density,
            x_tick_edge_labels=options.x_tick_edge_labels,
            y_tick_edge_labels=options.y_tick_edge_labels,
            x_padding_fraction=options.x_padding_fraction,
            xlim=base_kwargs.get("xlim"),
            ylim=base_kwargs.get("ylim"),
            preserve_stress_label=bool(base_kwargs.get("preserve_stress_label", False)),
            y_padding_top=(
                _float_plot_kw(base_kwargs, "y_padding_top", 0.12) + 0.04
                if compact_legend
                else _float_plot_kw(base_kwargs, "y_padding_top", 0.12)
            ),
            y_padding_bottom=_float_plot_kw(base_kwargs, "y_padding_bottom", 0.06),
        )
        if direct_label_side is not None and len(series_list) > 1:
            _ensure_direct_labels(
                ax,
                series_list,
                options=options,
                reverse_x=options.reverse_x,
                side=direct_label_side,
            )
        elif compact_legend:
            _apply_compact_inside_legend(
                ax,
                series_count=len(series_list),
                preserve_stress_label=bool(base_kwargs.get("preserve_stress_label", False)),
            )
        applied = apply_curve_autofix(ax, _post_curve_fix(combined_fix, include_line_scale=False))
        applied += _apply_series_style_overrides(
            ax,
            series_list=series_list,
            options=options,
            scatter=scatter,
        )
        applied += _apply_series_offsets(
            ax,
            series_list=series_list,
            options=options,
            scatter=scatter,
        )
    else:
        marker_size = None
        if show_markers:
            marker_size = plot_style.current_stroke().marker_size_pt * combined_fix.marker_size_scale
        fig, ax = plot_curves(
            series_list,
            show_markers=show_markers,
            axis_mode=str(base_kwargs.get("axis_mode", "auto")),
            xscale=resolved_xscale,
            yscale=resolved_yscale,
            width_mm=options.width_mm,
            height_mm=options.height_mm,
            reverse_x=options.reverse_x,
            marker_every=combined_fix.marker_every if show_markers else None,
            marker_size=marker_size,
            legend_mode=(
                "none"
                if direct_label_side is not None or compact_legend
                else forced_legend_mode
            ),
            legend_expand_axes=str(base_kwargs.get("legend_expand_axes", "xy")),
            preserve_stress_label=bool(base_kwargs.get("preserve_stress_label", False)),
            series_label_mode=(
                "edge"
                if direct_label_side is not None
                else str(base_kwargs.get("series_label_mode", "legend"))
            ),
            series_label_side=direct_label_side or str(base_kwargs.get("series_label_side", "auto")),
            visible_xticks=base_kwargs.get("visible_xticks"),
            x_tick_density=resolved_x_tick_density,
            y_tick_density=resolved_y_tick_density,
            x_tick_edge_labels=options.x_tick_edge_labels,
            y_tick_edge_labels=options.y_tick_edge_labels,
            x_padding_fraction=options.x_padding_fraction,
            xlim=base_kwargs.get("xlim"),
            ylim=base_kwargs.get("ylim"),
            line_drawstyle=str(base_kwargs.get("line_drawstyle", "default")),
            fill_to_axis=bool(base_kwargs.get("fill_to_axis", False)),
            y_padding_top=(
                _float_plot_kw(base_kwargs, "y_padding_top", 0.18) + 0.04
                if compact_legend
                else _float_plot_kw(base_kwargs, "y_padding_top", 0.18)
            ),
            y_padding_bottom=_float_plot_kw(base_kwargs, "y_padding_bottom", 0.06),
        )
        if direct_label_side is not None and len(series_list) > 1:
            _ensure_direct_labels(
                ax,
                series_list,
                options=options,
                reverse_x=options.reverse_x,
                side=direct_label_side,
            )
        elif compact_legend:
            _apply_compact_inside_legend(
                ax,
                series_count=len(series_list),
                preserve_stress_label=bool(base_kwargs.get("preserve_stress_label", False)),
            )
        applied = apply_curve_autofix(ax, _post_curve_fix(combined_fix, include_line_scale=show_markers))
        applied += _apply_series_style_overrides(
            ax,
            series_list=series_list,
            options=options,
            scatter=scatter,
        )
        applied += _apply_series_offsets(
            ax,
            series_list=series_list,
            options=options,
            scatter=scatter,
        )

    rendered = _rendered_plot_with_qa(
        filename=filename,
        figure=fig,
        template=template,
        options=options,
        autofixes_applied=tuple(dict.fromkeys([*autofixes, *applied])),
    )
    if rendered.figure.axes:
        _apply_curve_axis_labels(
            rendered.figure.axes[0],
            series_list[0],
            options,
            preserve_stress_label=bool(base_kwargs.get("preserve_stress_label", False)),
        )
    return rendered, strategy


def _with_manual_axis_overrides(
    base_kwargs: dict[str, object],
    options: RenderOptions,
) -> dict[str, object]:
    resolved = dict(base_kwargs)
    x_override, y_override = manual_axis_overrides(options)
    if x_override is not None:
        resolved["xlim"] = merge_axis_override_bounds(
            cast(tuple[float | None, float | None] | None, resolved.get("xlim")),
            x_override,
        )
        if "visible_xticks" in resolved:
            resolved["visible_xticks"] = None
    if y_override is not None:
        resolved["ylim"] = merge_axis_override_bounds(
            cast(tuple[float | None, float | None] | None, resolved.get("ylim")),
            y_override,
        )
    return resolved


def _legend_mode_for_position(position: str | None) -> str:
    cleaned = (position or "auto").strip().lower()
    if cleaned in {"upper_left", "upper_right", "lower_left", "lower_right"}:
        return f"inside_{cleaned}"
    return "inside_best"


def _ensure_known_series_order(series_list, series_order) -> None:
    unknown = unknown_series_order_labels([series.sample for series in series_list], series_order)
    if unknown:
        raise ValueError("series_order contains unknown series labels: " + ", ".join(unknown))


def _ensure_known_series_include(series_list, series_include) -> None:
    unknown = unknown_series_order_labels([series.sample for series in series_list], series_include)
    if unknown:
        raise ValueError("series_include contains unknown series labels: " + ", ".join(unknown))


def _filter_and_order_curve_series(series_list, options: RenderOptions):
    _ensure_known_series_include(series_list, options.series_include)
    selected = filter_curve_series(series_list, options.series_include)
    if not selected and options.series_include:
        raise ValueError("series_include did not match any series.")
    _ensure_known_series_order(selected, options.series_order)
    return reorder_curve_series(selected, options.series_order)


def _right_edge_curve_height(series, *, reverse_x: bool) -> float:
    x_values = np.asarray(series.data["x"].to_numpy(dtype=float), dtype=float)
    y_values = np.asarray(series.data["y"].to_numpy(dtype=float), dtype=float)
    finite = np.isfinite(x_values) & np.isfinite(y_values)
    if not bool(finite.any()):
        return float("nan")

    finite_x = x_values[finite]
    finite_y = y_values[finite]
    edge_x = np.min(finite_x) if reverse_x else np.max(finite_x)
    edge_indices = np.flatnonzero(finite_x == edge_x)
    if edge_indices.size:
        return float(finite_y[int(edge_indices[-1])])
    index = int(np.argmin(finite_x) if reverse_x else np.argmax(finite_x))
    return float(finite_y[index])


def _sort_curve_series_by_right_edge_height(series_list, *, reverse_x: bool):
    def sort_key(series) -> tuple[float, str]:
        height = _right_edge_curve_height(series, reverse_x=reverse_x)
        return (-height if np.isfinite(height) else float("inf"), series.sample.casefold())

    return sorted(series_list, key=sort_key)


def _series_y_bounds(series_list) -> tuple[float, float] | None:
    values = [
        series.data["y"].to_numpy(dtype=float)
        for series in series_list
        if "y" in series.data
    ]
    if not values:
        return None
    combined = np.concatenate(values)
    combined = combined[np.isfinite(combined)]
    if combined.size == 0:
        return None
    return float(np.min(combined)), float(np.max(combined))


def _decade_ylim_for_series(series_list) -> tuple[float, float] | None:
    bounds = _series_y_bounds(series_list)
    if bounds is None:
        return None
    low, high = bounds
    if low <= 0 or high <= 0:
        return None
    lower = 10.0 ** np.floor(np.log10(low))
    upper = 10.0 ** np.ceil(np.log10(high))
    if np.isclose(lower, upper):
        upper *= 10.0
    return float(lower), float(upper)


def _frequency_metric_axis_overrides(metric_name: str, series_list) -> dict[str, object]:
    if metric_name in {"storage_modulus", "loss_modulus", "complex_modulus"}:
        overrides: dict[str, object] = {
            "yscale": "log",
            "y_tick_density": "auto",
        }
        ylim = _decade_ylim_for_series(series_list)
        if ylim is not None:
            overrides["ylim"] = ylim
        return overrides
    if metric_name == "loss_factor":
        return {
            "yscale": "linear",
            "y_tick_density": "auto",
            "ylim": (1.0, 4.0),
            "legend_position": "upper_right",
        }
    return {}


def _load_filter_and_order_curve_series(input_path: Path, sheet: str | int, options: RenderOptions):
    return _filter_and_order_curve_series(load_curve_table_for_options(input_path, sheet, options), options)


def _fit_overlay_color(ax, *, series_index: int, scatter: bool) -> str:
    if scatter:
        scatter_collections = [collection for collection in ax.collections if np.asarray(collection.get_offsets()).size]
        if series_index < len(scatter_collections):
            collection = scatter_collections[series_index]
            colors = collection.get_facecolors()
            if len(colors):
                return cast(str, tuple(colors[0]))
    if series_index < len(ax.lines):
        return cast(str, ax.lines[series_index].get_color())
    return "black"


def _apply_curve_fit_overlay(
    rendered: RenderedPlot,
    *,
    template: str,
    series_list,
    options: RenderOptions,
    scatter: bool,
    series_axes: Mapping[str, Axes] | None = None,
    series_colors: Mapping[str, object] | None = None,
) -> RenderedPlot:
    fit_options = fit_options_from_payload(options.fit_options)
    if not fit_options.enabled:
        return rendered
    results = fit_series_list(
        series_list,
        model_id=fit_options.model_id,
        custom_function=fit_options.custom_function,
    )
    primary_ax = rendered.figure.axes[0]
    stroke = plot_style.current_stroke()
    equation_ax = primary_ax
    for series_index, result in enumerate(results.series_results):
        target_ax = series_axes.get(result.series_id, primary_ax) if series_axes is not None else primary_ax
        color = (
            series_colors.get(result.series_id)
            if series_colors is not None and result.series_id in series_colors
            else _fit_overlay_color(primary_ax, series_index=series_index, scatter=scatter)
        )
        target_ax.plot(
            result.x_line,
            result.y_line,
            color=color,
            linewidth=max(0.8, stroke.line_width_pt * 0.95),
            alpha=min(0.88, stroke.line_alpha),
            linestyle="--",
            label="_nolegend_",
            zorder=3.2,
        )
        equation_ax = target_ax
    if len(results.series_results) == 1:
        equation = results.series_results[0].equation_display
        equation_ax.text(
            0.03,
            0.97,
            equation,
            transform=equation_ax.transAxes,
            ha="left",
            va="top",
            fontsize=plot_style.current_typography().legend_font_size_pt,
            bbox={"facecolor": "white", "alpha": 0.72, "linewidth": 0.0, "boxstyle": "round,pad=0.2"},
            zorder=4.0,
        )
    return _rendered_plot_with_qa(
        filename=rendered.filename,
        figure=rendered.figure,
        template=template,
        options=options,
        autofixes_applied=(
            tuple(rendered.qa_report.autofixes_applied) if rendered.qa_report is not None else ()
        )
        + (f"{fit_options.model_id}_fit_overlay",),
    )


def _render_curve_like_plot(
    *,
    filename: str,
    template: str,
    series_list,
    options: RenderOptions,
    show_markers: bool,
    scatter: bool = False,
    base_kwargs: dict[str, object] | None = None,
) -> RenderedPlot:
    resolved_kwargs = _with_manual_axis_overrides(dict(base_kwargs or {}), options)
    preserve_stress_label = bool(resolved_kwargs.get("preserve_stress_label", False))
    secondary_binding = _resolve_secondary_y_axis_binding(
        template=template,
        series_list=series_list,
        options=options,
        preserve_stress_label=preserve_stress_label,
    )
    supports_direct_labels = secondary_binding is None and not (preserve_stress_label and len(series_list) >= 4)
    forced_legend = options.legend_position != "auto"
    candidates = [
        _render_curve_candidate(
            filename=filename,
            template=template,
            series_list=series_list,
            options=options,
            show_markers=show_markers,
            scatter=scatter,
            direct_label_side=None,
            legend_variant="standard",
            base_kwargs=resolved_kwargs,
        )
    ]
    if not forced_legend and secondary_binding is None and _prefer_compact_legend(options, len(series_list)):
        candidates.append(
            _render_curve_candidate(
                filename=filename,
                template=template,
                series_list=series_list,
                options=options,
                show_markers=show_markers,
                scatter=scatter,
                direct_label_side=None,
                legend_variant="compact",
                base_kwargs=resolved_kwargs,
            )
        )
    inline_labels_requested = options.series_label_mode == "inline"
    if (
        not forced_legend
        and inline_labels_requested
        and supports_direct_labels
        and _prefer_direct_labels(options, len(series_list))
        and len(series_list) > 1
    ):
        for side in ("left", "right"):
            candidates.append(
                _render_curve_candidate(
                    filename=filename,
                    template=template,
                    series_list=series_list,
                    options=options,
                    show_markers=show_markers,
                    scatter=scatter,
                    direct_label_side=side,
                    legend_variant="standard",
                    base_kwargs=resolved_kwargs,
                )
            )

    best_rendered, best_strategy = max(candidates, key=_curve_candidate_key)
    for rendered, strategy in candidates:
        if rendered is best_rendered and strategy == best_strategy:
            continue
        plt.close(rendered.figure)
    if secondary_binding is not None:
        rebound, _, _ = _rebind_secondary_y_axis_series(
            best_rendered,
            template=template,
            series_list=series_list,
            options=options,
            scatter=scatter,
            base_kwargs=resolved_kwargs,
            secondary_binding=secondary_binding,
        )
        return rebound
    return best_rendered

def _render_rheology_bundle(
    bundle: str,
    template: TemplateName,
    input_path: Path,
    sheet: str | int,
    options: RenderOptions,
    *,
    show_markers: bool,
    extra_curve_kwargs: dict[str, object] | None = None,
) -> list[RenderedPlot]:
    metric_series = load_rheology_bundle_series(bundle, input_path, sheet)
    validate_manual_axis_overrides(options, template=template)
    metric_series = {
        metric_name: _filter_and_order_curve_series(series_list, options)
        for metric_name, series_list in metric_series.items()
    }
    if bundle == "frequency_sweep" and not options.series_order:
        metric_series = {
            metric_name: _sort_curve_series_by_right_edge_height(series_list, reverse_x=options.reverse_x)
            for metric_name, series_list in metric_series.items()
        }
    output_filenames = rheology_output_filenames(bundle, template)
    shared_x_layout = None
    if bundle in {"frequency_sweep", "temperature_sweep"}:
        all_x_values = [
            series.data["x"].to_numpy(dtype=float)
            for metric_name in output_filenames
            for series in metric_series.get(metric_name, [])
        ]
        shared_x_layout = compute_shared_curve_x_layout(all_x_values, xscale=options.xscale)

    outputs: list[RenderedPlot] = []
    for metric_name, filename in output_filenames.items():
        series_list = metric_series.get(metric_name, [])
        if not series_list:
            raise ValueError(f"Missing data for {bundle} metric: {metric_name}")

        plot_kwargs: dict[str, object] = {
            "show_markers": show_markers,
            "xscale": options.xscale,
            "yscale": options.yscale,
            "width_mm": options.width_mm,
            "height_mm": options.height_mm,
            "reverse_x": options.reverse_x,
        }
        if shared_x_layout is not None:
            plot_kwargs["xlim"] = shared_x_layout.display_bounds
            plot_kwargs["visible_xticks"] = shared_x_layout.visible_ticks
            plot_kwargs["legend_expand_axes"] = "y"
        if bundle == "frequency_sweep":
            plot_kwargs.update(_frequency_metric_axis_overrides(metric_name, series_list))
        if bundle == "stress_relaxation":
            plot_kwargs["y_padding_top"] = 0.12
            plot_kwargs["y_padding_bottom"] = 0.04
        if extra_curve_kwargs:
            plot_kwargs.update(extra_curve_kwargs)

        outputs.append(
            _render_curve_like_plot(
                filename=filename,
                template=template,
                series_list=series_list,
                options=options,
                show_markers=show_markers,
                base_kwargs=plot_kwargs,
            )
        )
    return outputs

def _render_standard_curve_template(
    *,
    template: str,
    input_path: Path,
    sheet: str | int,
    options: RenderOptions,
    show_markers: bool,
    extra_curve_kwargs: dict[str, object] | None = None,
) -> list[RenderedPlot]:
    normalized_dataset = build_normalized_dataset(input_path, sheet, options=options)
    if normalized_dataset.model in {"frequency_sweep", "temperature_sweep", "stress_relaxation"}:
        return _render_rheology_bundle(
            normalized_dataset.model,
            template,
            input_path,
            sheet,
            options,
            show_markers=show_markers,
            extra_curve_kwargs=extra_curve_kwargs,
        )
    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_series_scales(series_list, xscale=options.xscale, yscale=options.yscale)
    is_tensile_curve = looks_like_tensile_curve(series_list)
    validate_manual_axis_overrides(options, template=template, is_tensile_curve=is_tensile_curve)
    axis_mode = "auto_positive" if is_tensile_curve else "auto"
    rendered = _render_curve_like_plot(
        filename=f"{input_path.stem}_{template}.pdf",
        template=template,
        series_list=series_list,
        options=options,
        show_markers=show_markers,
        base_kwargs={
            "axis_mode": axis_mode,
            "preserve_stress_label": is_tensile_curve,
            **(extra_curve_kwargs or {}),
        },
    )
    secondary_binding = _resolve_secondary_y_axis_binding(
        template=template,
        series_list=series_list,
        options=options,
        preserve_stress_label=is_tensile_curve,
    )
    series_axes, series_colors = _fit_overlay_axis_bindings(
        rendered,
        series_list=series_list,
        scatter=False,
        secondary_binding=secondary_binding,
    )
    if template in {"curve", "point_line"}:
        rendered = _apply_curve_fit_overlay(
            rendered,
            template=template,
            series_list=series_list,
            options=options,
            scatter=False,
            series_axes=series_axes,
            series_colors=series_colors,
        )
    return [rendered]

def _render_curve(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    return _render_standard_curve_template(
        template="curve",
        input_path=input_path,
        sheet=sheet,
        options=options,
        show_markers=False,
    )

def _render_point_line(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    return _render_standard_curve_template(
        template="point_line",
        input_path=input_path,
        sheet=sheet,
        options=options,
        show_markers=True,
    )

def _render_area_curve(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    return _render_standard_curve_template(
        template="area_curve",
        input_path=input_path,
        sheet=sheet,
        options=options,
        show_markers=False,
        extra_curve_kwargs={"fill_to_axis": True},
    )

def _render_step_line(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    return _render_standard_curve_template(
        template="step_line",
        input_path=input_path,
        sheet=sheet,
        options=options,
        show_markers=False,
        extra_curve_kwargs={"line_drawstyle": "steps-mid"},
    )


def _right_margin_for_inline_stack_labels(options: RenderOptions) -> float | None:
    if options.series_label_mode != "inline":
        return None
    spacing = plot_style.current_spacing()
    return max(spacing.right_margin_mm, 15.0)


def _apply_stacked_inline_labels(ax: Axes, series_list) -> None:
    if len(series_list) <= 1:
        return
    for text in tuple(ax.texts):
        text.remove()
    lines = [
        line
        for line in ax.lines
        if str(line.get_label()).strip() and not str(line.get_label()).startswith("_")
    ]
    if not lines:
        return
    axes_transform = ax.transAxes.inverted()
    for series, line in zip(series_list, lines, strict=False):
        x_values = np.asarray(line.get_xdata(), dtype=float)
        y_values = np.asarray(line.get_ydata(), dtype=float)
        valid = np.isfinite(x_values) & np.isfinite(y_values)
        if not np.any(valid):
            continue
        data_points = np.column_stack([x_values[valid], y_values[valid]])
        axes_points = axes_transform.transform(ax.transData.transform(data_points))
        visible = (
            np.isfinite(axes_points[:, 0])
            & np.isfinite(axes_points[:, 1])
            & (axes_points[:, 0] >= 0.0)
            & (axes_points[:, 0] <= 1.0)
        )
        if not np.any(visible):
            visible = np.isfinite(axes_points[:, 0]) & np.isfinite(axes_points[:, 1])
        if not np.any(visible):
            continue
        visible_points = axes_points[visible]
        y_axes = float(np.clip(visible_points[np.argmax(visible_points[:, 0]), 1], 0.02, 0.98))
        ax.text(
            1.012,
            y_axes,
            series.sample,
            transform=ax.transAxes,
            ha="left",
            va="center",
            color=line.get_color(),
            fontsize=6.2,
            clip_on=False,
            zorder=5.0,
        )


def _render_stacked_curve(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_series_scales(series_list, xscale=options.xscale, yscale=options.yscale)
    validate_manual_axis_overrides(options, template="stacked_curve")
    label_mode = "edge" if options.series_label_mode == "inline" else "legend"
    fig, ax = plot_curves(
        series_list,
        show_markers=False,
        legend_mode="none" if label_mode == "edge" else _legend_mode_for_position(options.legend_position),
        xscale=options.xscale,
        yscale=options.yscale,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        right_margin_mm=_right_margin_for_inline_stack_labels(options),
        reverse_x=options.reverse_x,
        x_padding_fraction=options.x_padding_fraction,
        stack_mode="auto_vertical",
        stack_spacing_scale=options.stack_spacing_scale if options.stack_spacing_scale is not None else 1.0,
        series_label_mode=label_mode,
        series_label_side="right",
        baseline_mode=options.baseline,
        show_y_ticks=False,
        y_padding_top=0.08,
        y_padding_bottom=0.04,
    )
    if label_mode == "edge":
        _apply_stacked_inline_labels(ax, series_list)
    rendered = _rendered_plot_with_qa(
        filename=f"{input_path.stem}_stacked_curve.pdf",
        figure=fig,
        template="stacked_curve",
        options=options,
    )
    if rendered.figure.axes:
        _apply_curve_axis_labels(
            rendered.figure.axes[0],
            series_list[0],
            options,
            preserve_stress_label=False,
        )
    return [rendered]


def _render_stacked_area(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_series_scales(series_list, xscale=options.xscale, yscale=options.yscale)
    validate_manual_axis_overrides(options, template="stacked_area")
    label_mode = "edge" if options.series_label_mode == "inline" else "legend"
    fig, ax = plot_curves(
        series_list,
        show_markers=False,
        legend_mode="none" if label_mode == "edge" else _legend_mode_for_position(options.legend_position),
        xscale=options.xscale,
        yscale=options.yscale,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        right_margin_mm=_right_margin_for_inline_stack_labels(options),
        reverse_x=options.reverse_x,
        x_padding_fraction=options.x_padding_fraction,
        stack_mode="auto_vertical",
        stack_spacing_scale=options.stack_spacing_scale if options.stack_spacing_scale is not None else 1.0,
        series_label_mode=label_mode,
        series_label_side="right",
        baseline_mode=options.baseline,
        show_y_ticks=False,
        line_drawstyle="default",
        fill_to_axis=True,
        y_padding_top=0.08,
        y_padding_bottom=0.04,
    )
    if label_mode == "edge":
        _apply_stacked_inline_labels(ax, series_list)
    return [
        _rendered_plot_with_qa(
            filename=f"{input_path.stem}_stacked_area.pdf",
            figure=fig,
            template="stacked_area",
            options=options,
        )
    ]


def _render_segmented_stacked_curve(
    input_path: Path,
    sheet: str | int,
    options: RenderOptions,
) -> list[RenderedPlot]:
    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_manual_axis_overrides(options, template="segmented_stacked_curve")
    config = load_segmented_config(input_path, series_list, use_sidecar=options.use_sidecar)
    if options.series_order:
        config = replace(config, series_order=tuple(series.sample for series in series_list))
    fig, _ = plot_wide_nmr(
        series_list,
        config,
        width_mm=options.width_mm,
        height_mm=options.height_mm,
        reverse_x=options.reverse_x,
        baseline_mode=options.baseline,
    )
    return [
        _rendered_plot_with_qa(
            filename=f"{input_path.stem}_segmented_stacked_curve.pdf",
            figure=fig,
            template="segmented_stacked_curve",
            options=options,
        )
    ]

def _render_scatter(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_series_scales(series_list, xscale=options.xscale, yscale=options.yscale)
    is_tensile_curve = looks_like_tensile_curve(series_list)
    validate_manual_axis_overrides(options, template="scatter", is_tensile_curve=is_tensile_curve)
    axis_mode = "auto_positive" if is_tensile_curve else "auto"
    rendered = _render_curve_like_plot(
        filename=f"{input_path.stem}_scatter.pdf",
        template="scatter",
        series_list=series_list,
        options=options,
        show_markers=False,
        scatter=True,
        base_kwargs={
            "axis_mode": axis_mode,
            "preserve_stress_label": is_tensile_curve,
        },
    )
    secondary_binding = _resolve_secondary_y_axis_binding(
        template="scatter",
        series_list=series_list,
        options=options,
        preserve_stress_label=is_tensile_curve,
    )
    series_axes, series_colors = _fit_overlay_axis_bindings(
        rendered,
        series_list=series_list,
        scatter=True,
        secondary_binding=secondary_binding,
    )
    rendered = _apply_curve_fit_overlay(
        rendered,
        template="scatter",
        series_list=series_list,
        options=options,
        scatter=True,
        series_axes=series_axes,
        series_colors=series_colors,
    )
    return [rendered]

def _bubble_size_profile(values: np.ndarray) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.full(values.shape, 46.0, dtype=float)
    magnitude = np.abs(finite)
    low = float(np.percentile(magnitude, 10))
    high = float(np.percentile(magnitude, 90))
    if not np.isfinite(low) or not np.isfinite(high):
        return np.full(values.shape, 46.0, dtype=float)
    if np.isclose(high, low):
        midpoint = float(min(140.0, max(42.0, 46.0 + abs(high) * 0.16)))
        result = np.full(values.shape, midpoint, dtype=float)
        result[~np.isfinite(values)] = midpoint
        return result
    clipped = np.clip(np.abs(values), low, high)
    normalized = (clipped - low) / max(high - low, 1e-9)
    sizes = 34.0 + normalized * (160.0 - 34.0)
    sizes[~np.isfinite(values)] = 34.0
    return sizes

def _render_bubble_scatter(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_series_scales(series_list, xscale=options.xscale, yscale=options.yscale)
    is_tensile_curve = looks_like_tensile_curve(series_list)
    validate_manual_axis_overrides(options, template="bubble_scatter", is_tensile_curve=is_tensile_curve)
    axis_mode = "auto_positive" if is_tensile_curve else "auto"
    rendered = _render_curve_like_plot(
        filename=f"{input_path.stem}_bubble_scatter.pdf",
        template="bubble_scatter",
        series_list=series_list,
        options=options,
        show_markers=False,
        scatter=True,
        base_kwargs={
            "axis_mode": axis_mode,
            "preserve_stress_label": is_tensile_curve,
        },
    )
    ax = rendered.figure.axes[0]
    scatter_collections = [collection for collection in ax.collections if np.asarray(collection.get_offsets()).size]
    for series, collection in zip(series_list, scatter_collections, strict=False):
        y_values = series.data["y"].to_numpy(dtype=float)
        bubble_sizes = _bubble_size_profile(y_values)
        collection.set_sizes(bubble_sizes)
        collection.set_alpha(max(float(collection.get_alpha() or 0.0), 0.72))
    rendered = _rendered_plot_with_qa(
        filename=rendered.filename,
        figure=rendered.figure,
        template="bubble_scatter",
        options=options,
        autofixes_applied=(
            tuple(rendered.qa_report.autofixes_applied) if rendered.qa_report is not None else ()
        )
        + ("bubble_size_encoding",),
    )
    return [rendered]

def _fit_line_xy(series_list) -> tuple[np.ndarray, np.ndarray, str]:
    result = fit_linear_series_list(series_list)
    return result.x_line, result.y_line, result.legend_label

def _render_scatter_fit_like(
    input_path: Path,
    sheet: str | int,
    options: RenderOptions,
    *,
    template: str,
    filename_suffix: str,
) -> list[RenderedPlot]:
    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_series_scales(series_list, xscale=options.xscale, yscale=options.yscale)
    is_tensile_curve = looks_like_tensile_curve(series_list)
    validate_manual_axis_overrides(options, template=template, is_tensile_curve=is_tensile_curve)
    axis_mode = "auto_positive" if is_tensile_curve else "auto"
    rendered = _render_curve_like_plot(
        filename=f"{input_path.stem}_{filename_suffix}.pdf",
        template=template,
        series_list=series_list,
        options=options,
        show_markers=False,
        scatter=True,
        base_kwargs={
            "axis_mode": axis_mode,
            "preserve_stress_label": is_tensile_curve,
        },
    )
    ax = rendered.figure.axes[0]
    x_line, y_line, fit_label = _fit_line_xy(series_list)
    stroke = plot_style.current_stroke()
    ax.plot(
        x_line,
        y_line,
        color="black",
        linewidth=max(0.8, stroke.line_width_pt * 0.95),
        alpha=min(0.9, stroke.line_alpha),
        linestyle="--",
        label=fit_label,
        zorder=3.2,
    )
    if ax.get_legend() is None:
        ax.legend(loc="best", frameon=False)
    rendered = _rendered_plot_with_qa(
        filename=rendered.filename,
        figure=rendered.figure,
        template=template,
        options=options,
        autofixes_applied=(
            tuple(rendered.qa_report.autofixes_applied) if rendered.qa_report is not None else ()
        )
        + ("deterministic_linear_fit_overlay",),
    )
    return [rendered]

def _render_scatter_fit(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    return _render_scatter_fit_like(
        input_path,
        sheet,
        options,
        template="scatter_fit",
        filename_suffix="scatter_fit",
    )

def _render_replicate_band_like(
    input_path: Path,
    sheet: str | int,
    options: RenderOptions,
    *,
    template: str,
    filename_suffix: str,
) -> list[RenderedPlot]:
    normalized_dataset = build_normalized_dataset(input_path, sheet, options=options)
    if normalized_dataset.model in {"frequency_sweep", "temperature_sweep", "stress_relaxation"}:
        raise ValueError(f"{template} is not supported for rheology export bundles.")

    series_list = _load_filter_and_order_curve_series(input_path, sheet, options)
    validate_series_scales(series_list, xscale=options.xscale, yscale=options.yscale)
    is_tensile_curve = looks_like_tensile_curve(series_list)
    validate_manual_axis_overrides(options, template=template, is_tensile_curve=is_tensile_curve)
    axis_mode = "auto_positive" if is_tensile_curve else "auto"
    rendered = _render_curve_like_plot(
        filename=f"{input_path.stem}_{filename_suffix}.pdf",
        template=template,
        series_list=series_list,
        options=options,
        show_markers=False,
        base_kwargs={
            "axis_mode": axis_mode,
            "preserve_stress_label": is_tensile_curve,
        },
    )
    ax = rendered.figure.axes[0]
    x_band, mean_band, std_band = aligned_replicate_band(series_list)
    color = plot_style.get_categorical_palette(n_colors=1)[0]
    lower = mean_band - std_band
    upper = mean_band + std_band
    ax.fill_between(
        x_band,
        lower,
        upper,
        color=color,
        alpha=min(0.22, plot_style.current_stroke().max_fill_alpha),
        linewidth=0.0,
        zorder=2.0,
        label="mean ±1σ band",
    )
    ax.plot(
        x_band,
        mean_band,
        color=color,
        linewidth=max(1.0, plot_style.current_stroke().line_width_pt),
        linestyle="-",
        zorder=3.6,
        label="mean curve",
    )
    if ax.get_legend() is None:
        ax.legend(loc="best", frameon=False)
    rendered = _rendered_plot_with_qa(
        filename=rendered.filename,
        figure=rendered.figure,
        template=template,
        options=options,
        autofixes_applied=(
            tuple(rendered.qa_report.autofixes_applied) if rendered.qa_report is not None else ()
        )
        + ("replicate_mean_band_overlay",),
    )
    return [rendered]

def _render_mean_band(input_path: Path, sheet: str | int, options: RenderOptions) -> list[RenderedPlot]:
    return _render_replicate_band_like(
        input_path,
        sheet,
        options,
        template="mean_band",
        filename_suffix="mean_band",
    )
