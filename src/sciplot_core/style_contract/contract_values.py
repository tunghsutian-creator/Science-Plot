"""Read hard style values from the canonical plot contract."""

from __future__ import annotations


def _contract_style_values(style: object) -> dict[str, object]:
    typography = getattr(style, "typography")
    stroke = getattr(style, "stroke")
    return {
        "typography.font_family": typography.font_family,
        "typography.font_size_pt": typography.font_size_pt,
        "typography.legend_font_size_pt": typography.legend_font_size_pt,
        "typography.panel_label_size_pt": typography.panel_label_size_pt,
        "stroke.axis_linewidth_pt": stroke.axis_linewidth_pt,
        "stroke.tick_width_pt": stroke.tick_width_pt,
        "stroke.tick_length_pt": stroke.tick_length_pt,
        "stroke.minor_tick_width_pt": stroke.minor_tick_width_pt,
        "stroke.minor_tick_length_pt": stroke.minor_tick_length_pt,
        "stroke.line_width_pt": stroke.line_width_pt,
        "stroke.marker_size_pt": stroke.marker_size_pt,
    }


__all__ = ["_contract_style_values"]
