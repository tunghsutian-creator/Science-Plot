"""Declare validated render option keys, delivery names, and base defaults."""

from __future__ import annotations

import math
from typing import Any

from sciplot_core.policy.visual_identity import (
    DEFAULT_FIGURE_SIZE,
    DEFAULT_PALETTE_PRESET,
)

from sciplot_core.policy.frame_export import (
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_LEGEND_FONT_SIZE_PT,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_TICK_WIDTH_PT,
    UNIFIED_TICK_LENGTH_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_MINOR_TICK_LENGTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_HARD_OPTION_KEYS,
)

from sciplot_core.policy.categorical import (
    DEFAULT_CATEGORICAL_SUMMARY,
    CATEGORICAL_SUMMARY_OPTIONS,
    DEFAULT_RAW_POINT_JITTER_FRACTION,
    MAX_RAW_POINT_JITTER_FRACTION,
)

RENDER_OPTION_KEYS = frozenset(
    {
        "size",
        "xscale",
        "yscale",
        "reverse_x",
        "x_min",
        "x_max",
        "y_min",
        "y_max",
        "x_padding_fraction",
        "x_tick_density",
        "y_tick_density",
        "x_tick_edge_labels",
        "y_tick_edge_labels",
        "x_tick_format",
        "y_tick_format",
        "x_ticks",
        "y_ticks",
        "minor_tick_count",
        "x_minor_tick_count",
        "y_minor_tick_count",
        "x_minor_ticks",
        "y_minor_ticks",
        "show_y_ticks",
        "series_order",
        "series_include",
        "series_styles",
        "line_style_sequence",
        "marker_sequence",
        "marker_size",
        "marker_fill_mode",
        "summary_statistic",
        "raw_point_jitter_fraction",
        "palette_colors",
        "font_size_pt",
        "legend_font_size_pt",
        "axis_linewidth_pt",
        "tick_width_pt",
        "tick_length_pt",
        "minor_tick_width_pt",
        "minor_tick_length_pt",
        "line_width_pt",
        "line_alpha",
        "marker_alpha",
        "marker_line_width_pt",
        "series_offsets",
        "stack_spacing_scale",
        "stack_peak_envelope",
        "legend_position",
        "legend_curve_clearance_mm",
        "legend_edge_padding_mm",
        "series_label_mode",
        "x_label_override",
        "y_label_override",
        "baseline",
        "show_colorbar",
        "zscale",
        "z_min",
        "z_max",
        "z_ticks",
        "z_tick_format",
        "z_label_override",
        "colormap_name",
        "colormap_colors",
        "color_invert",
        "field_mapping",
        "field_draw_mode",
        "field_transparency",
        "contour_levels",
        "contour_color",
        "contour_line_style",
        "contour_line_width_pt",
        "contour_labels",
        "highlight_contour_levels",
        "highlight_contour_color",
        "highlight_contour_line_style",
        "highlight_contour_line_width_pt",
        "colorbar_width_mm",
        "colorbar_height_mm",
        "colorbar_direction",
        "colorbar_manual_position",
        "colorbar_horz_manual",
        "colorbar_vert_manual",
        "colorbar_foreground_color",
        "colorbar_background_color",
        "colorbar_background_transparency",
        "colorbar_background_x_fraction",
        "colorbar_background_y_fraction",
        "colorbar_background_width_fraction",
        "colorbar_background_height_fraction",
        "style_preset",
        "palette_preset",
        "visual_theme_id",
        "fit_options",
        "extra_x_axis",
        "extra_y_axis",
        "x_axis_breaks",
        "y_axis_breaks",
        "reference_guides",
        "reference_line",
        "reference_band",
        "text_annotations",
        "shape_annotations",
        "analytical_layers",
        "data_variables",
        "data_transforms",
    }
)


VALIDATED_VISUAL_OVERRIDE_KEYS = (
    frozenset(
        {
            "size",
            "x_tick_density",
            "y_tick_density",
            "x_tick_edge_labels",
            "y_tick_edge_labels",
            "minor_tick_count",
            "series_order",
            "series_styles",
            "line_style_sequence",
            "marker_sequence",
            "marker_size",
            "marker_fill_mode",
            "raw_point_jitter_fraction",
            "palette_colors",
            "font_size_pt",
            "legend_font_size_pt",
            "axis_linewidth_pt",
            "tick_width_pt",
            "tick_length_pt",
            "minor_tick_width_pt",
            "minor_tick_length_pt",
            "line_width_pt",
            "line_alpha",
            "marker_alpha",
            "marker_line_width_pt",
            "legend_position",
            "legend_curve_clearance_mm",
            "legend_edge_padding_mm",
            "series_label_mode",
            "colormap_name",
            "colormap_colors",
            "color_invert",
            "contour_color",
            "contour_line_style",
            "contour_line_width_pt",
            "contour_labels",
            "highlight_contour_color",
            "highlight_contour_line_style",
            "highlight_contour_line_width_pt",
            "colorbar_width_mm",
            "colorbar_height_mm",
            "colorbar_direction",
            "colorbar_manual_position",
            "colorbar_horz_manual",
            "colorbar_vert_manual",
            "colorbar_foreground_color",
            "colorbar_background_color",
            "colorbar_background_transparency",
            "colorbar_background_x_fraction",
            "colorbar_background_y_fraction",
            "colorbar_background_width_fraction",
            "colorbar_background_height_fraction",
            "style_preset",
            "palette_preset",
            "visual_theme_id",
        }
    )
    - UNIFIED_HARD_OPTION_KEYS
)


DELIVERY_DIR = "delivery"


DELIVERY_DATA_DIR = "data"


DELIVERY_FIGURES_DIR = "figures"


DELIVERY_PDF_DIR = DELIVERY_FIGURES_DIR


DELIVERY_TIFF_DIR = DELIVERY_FIGURES_DIR


DELIVERY_PROJECT_DIR = "project"


DELIVERY_LAUNCHER = "Open_in_Veusz.command"


DELIVERY_EDITABLE_DIR = "editable"


DELIVERY_INTERNAL_DIR = "_sciplot_internal"


DEFAULT_RENDER_OPTIONS: dict[str, Any] = {
    "legend_position": "auto",
    "series_label_mode": "legend",
    "visual_theme_id": "clean_light",
    "style_preset": "nature",
    "size": DEFAULT_FIGURE_SIZE,
    "palette_preset": DEFAULT_PALETTE_PRESET,
    "font_size_pt": UNIFIED_FONT_SIZE_PT,
    "legend_font_size_pt": UNIFIED_LEGEND_FONT_SIZE_PT,
    "axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
    "tick_width_pt": UNIFIED_TICK_WIDTH_PT,
    "tick_length_pt": UNIFIED_TICK_LENGTH_PT,
    "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
    "minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
    "line_width_pt": UNIFIED_LINE_WIDTH_PT,
    "marker_size": UNIFIED_MARKER_SIZE_PT,
    "marker_line_width_pt": UNIFIED_MARKER_LINE_WIDTH_PT,
}


AUTOPLOT_RENDER_OPTIONS: dict[str, Any] = {
    key: DEFAULT_RENDER_OPTIONS[key]
    for key in (
        "visual_theme_id",
        "style_preset",
        "size",
        "palette_preset",
    )
}


def normalize_categorical_summary(value: object) -> str:
    normalized = str(value or DEFAULT_CATEGORICAL_SUMMARY).strip().casefold()
    if normalized not in CATEGORICAL_SUMMARY_OPTIONS:
        known = ", ".join(CATEGORICAL_SUMMARY_OPTIONS)
        raise ValueError(f"Unknown categorical summary `{value}`. Available: {known}.")
    return normalized


def normalize_raw_point_jitter_fraction(value: object) -> float:
    if value in (None, ""):
        return DEFAULT_RAW_POINT_JITTER_FRACTION
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Raw-point jitter fraction must be a finite number between 0 and 0.35."
        ) from exc
    if (
        not math.isfinite(normalized)
        or not 0.0 <= normalized <= MAX_RAW_POINT_JITTER_FRACTION
    ):
        raise ValueError(
            "Raw-point jitter fraction must be a finite number between 0 and 0.35."
        )
    return normalized
