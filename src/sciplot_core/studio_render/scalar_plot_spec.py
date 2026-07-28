"""Build the renderer-neutral contract for scalar-field plots."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.policy import (
    DEFAULT_LOG_TICK_FORMAT,
    DEFAULT_SCALAR_FIELD_COLORMAP_ID,
    DEFAULT_SCALAR_FIELD_COLORS,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LINE_WIDTH_PT,
)
from sciplot_core.scalar_visual import (
    normalize_opaque_colormap_colors,
)

from sciplot_core.studio_render.models import (
    SCALAR_FIELD_TEMPLATE_IDS,
    _VeuszStyleContract,
)

from sciplot_core.studio_render.style_contract import (
    _veusz_style_contract,
)

from sciplot_core.studio_render.value_parsing import (
    _optional_float,
    _float_tuple,
)


def _scalar_field_plot_contract(
    axis_info: dict[str, Any],
    *,
    render_options: dict[str, Any],
    template_id: str,
    style: _VeuszStyleContract | None = None,
) -> dict[str, Any] | None:
    source = axis_info.get("scalar_field")
    if template_id not in SCALAR_FIELD_TEMPLATE_IDS or not isinstance(source, dict):
        return None
    style = style or _veusz_style_contract(render_options)
    data_min = float(source["z_data_min"])
    data_max = float(source["z_data_max"])
    z_min = _optional_float(render_options.get("z_min"))
    z_max = _optional_float(render_options.get("z_max"))
    z_min = data_min if z_min is None else z_min
    z_max = data_max if z_max is None else z_max
    if not math.isfinite(z_min) or not math.isfinite(z_max) or z_min >= z_max:
        raise ValueError(
            "Scalar-field z_min and z_max must be finite and strictly increasing."
        )
    zscale = str(render_options.get("zscale") or "linear").strip().casefold()
    if zscale == "log" and z_min <= 0.0:
        raise ValueError("Scalar-field logarithmic color scaling requires z_min > 0.")
    colors = normalize_opaque_colormap_colors(
        render_options.get("colormap_colors"),
        default_colors=DEFAULT_SCALAR_FIELD_COLORS,
    )
    try:
        field_transparency_raw = render_options.get("field_transparency")
        field_transparency = int(
            0 if field_transparency_raw is None else field_transparency_raw
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Scalar-field transparency must be an integer percentage."
        ) from exc
    if not 0 <= field_transparency < 100:
        raise ValueError(
            "Scalar-field transparency must be between 0 and 99 so the "
            "scientific field remains visible."
        )
    direction = (
        str(render_options.get("colorbar_direction") or "horizontal").strip().casefold()
    )
    if direction not in {"horizontal", "vertical"}:
        raise ValueError(
            "Scalar-field colorbar direction must be horizontal or vertical."
        )
    colorbar_manual_position = render_options.get("colorbar_manual_position") is True
    try:
        width_value = render_options.get("colorbar_width_mm")
        height_value = render_options.get("colorbar_height_mm")
        background_transparency_value = render_options.get(
            "colorbar_background_transparency"
        )
        background_x_value = render_options.get("colorbar_background_x_fraction")
        background_y_value = render_options.get("colorbar_background_y_fraction")
        background_width_value = render_options.get(
            "colorbar_background_width_fraction"
        )
        background_height_value = render_options.get(
            "colorbar_background_height_fraction"
        )
        horz_manual_value = render_options.get("colorbar_horz_manual")
        vert_manual_value = render_options.get("colorbar_vert_manual")
        colorbar_width_mm = float(31.0 if width_value is None else width_value)
        colorbar_height_mm = float(2.4 if height_value is None else height_value)
        colorbar_background_transparency = int(
            0
            if background_transparency_value is None
            else background_transparency_value
        )
        colorbar_background_x_fraction = float(
            0.5 if background_x_value is None else background_x_value
        )
        colorbar_background_y_fraction = float(
            0.86 if background_y_value is None else background_y_value
        )
        colorbar_background_width_fraction = float(
            0.44 if background_width_value is None else background_width_value
        )
        colorbar_background_height_fraction = float(
            0.24 if background_height_value is None else background_height_value
        )
        colorbar_horz_manual = float(
            0.86 if horz_manual_value is None else horz_manual_value
        )
        colorbar_vert_manual = float(
            0.18 if vert_manual_value is None else vert_manual_value
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Scalar-field colorbar geometry must be numeric.") from exc
    if (
        not math.isfinite(colorbar_width_mm)
        or not math.isfinite(colorbar_height_mm)
        or colorbar_width_mm <= 0.0
        or colorbar_height_mm <= 0.0
    ):
        raise ValueError(
            "Scalar-field colorbar width and height must be finite and positive."
        )
    if direction == "horizontal" and not (
        5.0 <= colorbar_width_mm <= 50.0 and 0.5 <= colorbar_height_mm <= 8.0
    ):
        raise ValueError(
            "Horizontal scalar-field colorbars must remain within the bounded "
            "5..50 mm by 0.5..8 mm auxiliary envelope."
        )
    if direction == "vertical" and not (
        0.5 <= colorbar_width_mm <= 8.0 and 5.0 <= colorbar_height_mm <= 50.0
    ):
        raise ValueError(
            "Vertical scalar-field colorbars must remain within the bounded "
            "0.5..8 mm by 5..50 mm auxiliary envelope."
        )
    if (
        not math.isfinite(colorbar_horz_manual)
        or not math.isfinite(colorbar_vert_manual)
        or not 0.0 <= colorbar_horz_manual <= 1.0
        or not 0.0 <= colorbar_vert_manual <= 1.0
    ):
        raise ValueError(
            "Scalar-field manual colorbar coordinates must be finite fractions "
            "between 0 and 1."
        )
    if not 0 <= colorbar_background_transparency <= 100:
        raise ValueError(
            "Scalar-field colorbar background transparency must be between 0 and 100."
        )
    background_geometry = (
        colorbar_background_x_fraction,
        colorbar_background_y_fraction,
        colorbar_background_width_fraction,
        colorbar_background_height_fraction,
    )
    if (
        any(not math.isfinite(value) for value in background_geometry)
        or colorbar_background_width_fraction <= 0.0
        or colorbar_background_height_fraction <= 0.0
    ):
        raise ValueError(
            "Scalar-field colorbar background geometry must be finite with "
            "positive width and height."
        )
    background_color = str(
        render_options.get("colorbar_background_color") or ""
    ).strip()
    if background_color:
        left = colorbar_background_x_fraction - colorbar_background_width_fraction / 2.0
        right = (
            colorbar_background_x_fraction + colorbar_background_width_fraction / 2.0
        )
        top_band_start = (
            colorbar_background_y_fraction - colorbar_background_height_fraction / 2.0
        )
        bottom = (
            colorbar_background_y_fraction + colorbar_background_height_fraction / 2.0
        )
        background_area = (
            colorbar_background_width_fraction * colorbar_background_height_fraction
        )
        if direction != "horizontal" or colorbar_manual_position:
            raise ValueError(
                "Automatic scalar-field colorbar backgrounds are limited to "
                "the default horizontal top auxiliary band."
            )
        if (
            colorbar_background_transparency < 80
            or colorbar_background_width_fraction > 0.55
            or colorbar_background_height_fraction > 0.25
            or background_area > 0.12
            or left < 0.0
            or right > 1.0
            or top_band_start < 0.70
            or bottom > 1.0
        ):
            raise ValueError(
                "Scalar-field colorbar backgrounds must be semitransparent "
                "and confined to the bounded horizontal top auxiliary band."
            )
    contour_levels = [
        value
        for value in _float_tuple(render_options.get("contour_levels"))
        if z_min <= value <= z_max
    ]
    highlight_levels = [
        value
        for value in _float_tuple(render_options.get("highlight_contour_levels"))
        if z_min <= value <= z_max
    ]
    show_contours = bool(contour_levels)
    return {
        **json_safe(source),
        "z_min": z_min,
        "z_max": z_max,
        "zscale": zscale,
        "z_ticks": list(_float_tuple(render_options.get("z_ticks"))),
        "z_tick_format": str(
            render_options.get("z_tick_format")
            or (DEFAULT_LOG_TICK_FORMAT if zscale == "log" else "Auto")
        ),
        "show_colorbar": render_options.get("show_colorbar") is not False,
        "colormap_name": str(
            render_options.get("colormap_name") or DEFAULT_SCALAR_FIELD_COLORMAP_ID
        ),
        "colormap_colors": colors,
        "color_invert": render_options.get("color_invert") is True,
        "field_mapping": str(render_options.get("field_mapping") or "bounds"),
        "field_draw_mode": str(render_options.get("field_draw_mode") or "rectangles"),
        "field_transparency": field_transparency,
        "show_contours": show_contours,
        "contour_levels": contour_levels,
        "contour_color": str(render_options.get("contour_color") or "#FFFFFF"),
        "contour_line_style": str(render_options.get("contour_line_style") or "solid"),
        "contour_line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "contour_labels": render_options.get("contour_labels") is True,
        "highlight_contour_levels": highlight_levels,
        "highlight_contour_color": str(
            render_options.get("highlight_contour_color") or UNIFIED_FOREGROUND_COLOR
        ),
        "highlight_contour_line_style": str(
            render_options.get("highlight_contour_line_style") or "dashed"
        ),
        "highlight_contour_line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "colorbar_direction": direction,
        "colorbar_manual_position": colorbar_manual_position,
        "colorbar_width_mm": colorbar_width_mm,
        "colorbar_height_mm": colorbar_height_mm,
        "colorbar_horz_manual": colorbar_horz_manual,
        "colorbar_vert_manual": colorbar_vert_manual,
        "colorbar_label_size_pt": style.font_size_pt,
        "colorbar_tick_label_size_pt": style.font_size_pt,
        "colorbar_line_width_pt": style.axis_linewidth_pt,
        "colorbar_border_width_pt": style.axis_linewidth_pt,
        "colorbar_major_tick_width_pt": style.tick_width_pt,
        "colorbar_major_tick_length_pt": style.tick_length_pt,
        "colorbar_minor_tick_width_pt": style.minor_tick_width_pt,
        "colorbar_minor_tick_length_pt": style.minor_tick_length_pt,
        "colorbar_foreground_color": str(
            render_options.get("colorbar_foreground_color") or UNIFIED_FOREGROUND_COLOR
        ),
        "colorbar_background_color": background_color,
        "colorbar_background_transparency": (colorbar_background_transparency),
        "colorbar_background_x_fraction": (colorbar_background_x_fraction),
        "colorbar_background_y_fraction": (colorbar_background_y_fraction),
        "colorbar_background_width_fraction": (colorbar_background_width_fraction),
        "colorbar_background_height_fraction": (colorbar_background_height_fraction),
    }
