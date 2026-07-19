from __future__ import annotations

import re
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


def _normalize_opaque_hex_color(value: object) -> str:
    color = str(value).strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", color) is None:
        raise ValueError(
            "Scalar-field colormap_colors must use #RRGGBB or "
            "#RRGGBBAA hexadecimal values."
        )
    alpha = color[7:9] if len(color) == 9 else "FF"
    if alpha.casefold() != "ff":
        raise ValueError(
            "Scalar-field colormap_colors must be fully opaque so "
            "the scientific field cannot disappear."
        )
    return color


def normalize_opaque_colormap_colors(
    value: object,
    *,
    default_colors: tuple[str, ...] = (),
) -> list[str]:
    """Validate a visible, scientifically distinguishable scalar colormap."""

    source = default_colors if value is None else value
    if not isinstance(source, list | tuple) or len(source) < 2:
        raise ValueError(
            "Scalar-field colormap_colors must contain at least two "
            "opaque hexadecimal colors."
        )
    colors = [_normalize_opaque_hex_color(item) for item in source]
    if len({color[:7].casefold() for color in colors}) < 2:
        raise ValueError(
            "Scalar-field colormap_colors must contain at least two "
            "visually distinct colors."
        )
    return colors


def opaque_color_to_veusz_rgba(value: object) -> tuple[int, int, int, int]:
    color = _normalize_opaque_hex_color(value)
    return (
        int(color[1:3], 16),
        int(color[3:5], 16),
        int(color[5:7], 16),
        255,
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
    "normalize_opaque_colormap_colors",
    "opaque_color_to_veusz_rgba",
    "scalar_visual_contract",
]
