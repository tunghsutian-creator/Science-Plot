from __future__ import annotations

from typing import Any

from sciplot_core._utils import json_safe

SCALAR_VISUAL_CONTRACT_FIELDS = (
    "z_min",
    "z_max",
    "zscale",
    "z_ticks",
    "z_tick_format",
    "show_colorbar",
    "colormap_name",
    "colormap_colors",
    "color_invert",
    "field_mapping",
    "field_draw_mode",
    "field_transparency",
    "show_contours",
    "contour_levels",
    "contour_color",
    "contour_line_style",
    "contour_line_width_pt",
    "contour_labels",
    "highlight_contour_levels",
    "highlight_contour_color",
    "highlight_contour_line_style",
    "highlight_contour_line_width_pt",
    "colorbar_direction",
    "colorbar_manual_position",
    "colorbar_width_mm",
    "colorbar_height_mm",
    "colorbar_horz_manual",
    "colorbar_vert_manual",
    "colorbar_label_size_pt",
    "colorbar_tick_label_size_pt",
    "colorbar_line_width_pt",
    "colorbar_border_width_pt",
    "colorbar_major_tick_width_pt",
    "colorbar_major_tick_length_pt",
    "colorbar_minor_tick_width_pt",
    "colorbar_minor_tick_length_pt",
    "colorbar_foreground_color",
    "colorbar_background_color",
    "colorbar_background_transparency",
    "colorbar_background_x_fraction",
    "colorbar_background_y_fraction",
    "colorbar_background_width_fraction",
    "colorbar_background_height_fraction",
)


def scalar_visual_contract(
    value: object,
    *,
    label: str,
) -> dict[str, Any]:
    """Project one scalar field onto its closed scientific visual contract."""

    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object.")
    missing = [
        field
        for field in SCALAR_VISUAL_CONTRACT_FIELDS
        if field not in value
    ]
    if missing:
        raise ValueError(
            f"{label} is missing scalar visual fields: {missing}"
        )
    return json_safe(
        {
            field: value[field]
            for field in SCALAR_VISUAL_CONTRACT_FIELDS
        }
    )


__all__ = [
    "SCALAR_VISUAL_CONTRACT_FIELDS",
    "scalar_visual_contract",
]
