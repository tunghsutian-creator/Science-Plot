"""Declare implemented templates and editable option sets."""

from __future__ import annotations


VEUSZ_IMPLEMENTED_TEMPLATE_IDS = frozenset(
    {
        "curve",
        "point_line",
        "stacked_curve",
        "bar",
        "box",
        "box_strip",
        "heatmap",
        "scatter",
        "polar_curve",
    }
)


VEUSZ_REQUIRED_EDITABLE_OPTIONS = {
    "heatmap": frozenset(
        {
            "size",
            "x_min",
            "x_max",
            "y_min",
            "y_max",
            "x_label_override",
            "y_label_override",
            "show_colorbar",
            "data_variables",
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
            "contour_labels",
            "highlight_contour_levels",
            "highlight_contour_color",
            "highlight_contour_line_style",
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
            "reference_guides",
            "style_preset",
            "palette_preset",
        }
    ),
}


VEUSZ_TEMPLATE_COLOR_OPTIONS = {
    "heatmap": frozenset(
        {
            "colormap_name",
            "colormap_colors",
            "color_invert",
            "contour_color",
            "highlight_contour_color",
            "colorbar_foreground_color",
            "colorbar_background_color",
        }
    ),
}


def validate_veusz_template_id(template: object) -> str:
    """Return a production template id or fail before document generation."""

    normalized = str(template or "").strip()
    if normalized not in VEUSZ_IMPLEMENTED_TEMPLATE_IDS:
        known = ", ".join(sorted(VEUSZ_IMPLEMENTED_TEMPLATE_IDS))
        raise ValueError(
            f"Template `{normalized or template}` is not implemented by SciPlot's "
            f"Veusz document builder. Supported templates: {known}."
        )
    return normalized
