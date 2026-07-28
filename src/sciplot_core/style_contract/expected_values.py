"""Build expected shared hard-style values."""

from __future__ import annotations

from sciplot_core.policy import (
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_BOTTOM_MARGIN_MM,
    UNIFIED_FONT_FAMILY,
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_LEGEND_FONT_SIZE_PT,
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MINOR_TICK_LENGTH_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_PANEL_LABEL_SIZE_PT,
    UNIFIED_RIGHT_MARGIN_MM,
    UNIFIED_TICK_LENGTH_PT,
    UNIFIED_TICK_WIDTH_PT,
    UNIFIED_TOP_MARGIN_MM,
)


def _expected_render_hard_values() -> dict[str, float]:
    return {
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


def _expected_optional_hard_values() -> dict[str, float]:
    return {
        **_expected_render_hard_values(),
        "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
        "contour_line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "highlight_contour_line_width_pt": UNIFIED_LINE_WIDTH_PT,
    }


def _expected_contract_style_values() -> dict[str, object]:
    return {
        "typography.font_family": (UNIFIED_FONT_FAMILY,),
        "typography.font_size_pt": UNIFIED_FONT_SIZE_PT,
        "typography.legend_font_size_pt": UNIFIED_LEGEND_FONT_SIZE_PT,
        "typography.panel_label_size_pt": UNIFIED_PANEL_LABEL_SIZE_PT,
        "stroke.axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "stroke.tick_width_pt": UNIFIED_TICK_WIDTH_PT,
        "stroke.tick_length_pt": UNIFIED_TICK_LENGTH_PT,
        "stroke.minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
        "stroke.minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
        "stroke.line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "stroke.marker_size_pt": UNIFIED_MARKER_SIZE_PT,
    }


def _expected_global_frame() -> dict[str, float]:
    return {
        "left_margin_mm": UNIFIED_LEFT_MARGIN_MM,
        "right_margin_mm": UNIFIED_RIGHT_MARGIN_MM,
        "bottom_margin_mm": UNIFIED_BOTTOM_MARGIN_MM,
        "top_margin_mm": UNIFIED_TOP_MARGIN_MM,
    }
