"""Add XY, line, contour, and scalar-field primitives to a Veusz document."""

from __future__ import annotations

from typing import Any
from sciplot_core.policy import (
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LINE_WIDTH_PT,
)
from sciplot_core.scalar_visual import (
    normalize_opaque_colormap_colors,
    opaque_color_to_veusz_rgba,
)
from sciplot_core.studio_render.categorical_values import (
    _veusz_axis_label,
)

from sciplot_core.studio_core.series_request import (
    _veusz_literal_text,
)

from sciplot_core.studio_core.veusz_units import (
    _pt,
    _cm_from_mm,
    _alpha_to_transparency,
)


def _add_veusz_xy_series(
    interface: Any,
    item: dict[str, Any],
    style: dict[str, Any],
) -> None:
    interface.Add("xy", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("xData", item["x_name"])
    interface.Set("yData", item["y_name"])
    interface.Set(
        "key",
        _veusz_literal_text(item.get("legend_key", item["label"])),
    )
    interface.Set("PlotLine/color", item["color"])
    interface.Set("PlotLine/style", item.get("line_style") or "solid")
    interface.Set("MarkerFill/color", item.get("marker_fill_color") or item["color"])
    interface.Set("MarkerLine/color", item.get("marker_line_color") or item["color"])
    interface.Set(
        "MarkerLine/width",
        _pt(float(item.get("marker_line_width_pt") or style["marker_line_width_pt"])),
    )
    interface.Set("marker", item["marker"])
    # Veusz's XY legend renderer always asks the error-bar painter to draw a
    # key sample.  With the default ``bar`` error style, datasets without
    # errors still produce zero-length strokes at the centre of the legend
    # line, which rasterize as a small dot.  Studio XY series do not carry
    # error datasets, so hide that unused channel explicitly for every shared
    # XY-based template (curve, point_line, stacked_curve, and raw-point
    # layers).  Real categorical error bars are separate native line objects.
    interface.Set("ErrorBarLine/hide", True)
    if str(item.get("marker") or "none").strip().casefold() == "none":
        interface.Set("MarkerFill/hide", True)
        interface.Set("MarkerLine/hide", True)
    if item.get("marker_line_hide") is True:
        interface.Set("MarkerLine/hide", True)
    if item.get("plot_line_hide") is True:
        interface.Set("PlotLine/hide", True)
    if item.get("raw_points_visible") is False:
        interface.Set("MarkerFill/hide", True)
        interface.Set("MarkerLine/hide", True)
    interface.Set(
        "PlotLine/transparency", _alpha_to_transparency(float(style["line_alpha"]))
    )
    interface.Set(
        "MarkerFill/transparency",
        _alpha_to_transparency(float(item.get("marker_alpha", style["marker_alpha"]))),
    )
    interface.Set(
        "MarkerLine/transparency",
        _alpha_to_transparency(float(item.get("marker_alpha", style["marker_alpha"]))),
    )
    if item.get("line_width_pt") is not None:
        interface.Set("PlotLine/width", _pt(float(item["line_width_pt"])))
    marker = str(item.get("marker") or "none")
    if item.get("marker_size_pt") is not None:
        interface.Set("markerSize", _pt(float(item["marker_size_pt"])))
    elif marker != "none":
        interface.Set("markerSize", _pt(float(style["marker_size_pt"])))
    marker_thin_factor = max(1, int(item.get("marker_thin_factor") or 1))
    if marker_thin_factor > 1:
        interface.Set("thinfactor", marker_thin_factor)
    interface.To("..")


def _add_veusz_axis_line(
    interface: Any,
    *,
    name: str,
    x_pos: float,
    y_pos: float,
    x_pos_2: float,
    y_pos_2: float,
    color: str,
    width_pt: float,
) -> None:
    interface.Add("line", name=name, autoadd=False)
    interface.To(name)
    interface.Set("positioning", "axes")
    interface.Set("xAxis", "x")
    interface.Set("yAxis", "y")
    interface.Set("mode", "point-to-point")
    interface.Set("xPos", [x_pos])
    interface.Set("yPos", [y_pos])
    interface.Set("xPos2", [x_pos_2])
    interface.Set("yPos2", [y_pos_2])
    interface.Set("clip", True)
    interface.Set("hide", False)
    interface.Set("Line/color", color)
    interface.Set("Line/width", _pt(width_pt))
    interface.Set("Line/style", "solid")
    interface.Set("Line/transparency", 0)
    interface.Set("Line/hide", False)
    interface.Set("arrowleft", "none")
    interface.Set("arrowright", "none")
    interface.Set("Fill/hide", True)
    interface.To("..")


def _add_veusz_contour(
    interface: Any,
    *,
    name: str,
    data_name: str,
    levels: list[float],
    color: str,
    line_style: str,
    line_width_pt: float,
    show_labels: bool,
) -> None:
    if not levels:
        return
    interface.Add("contour", name=name, autoadd=False)
    interface.To(name)
    interface.Set("data", data_name)
    interface.Set("scaling", "manual")
    interface.Set("manualLevels", [float(value) for value in levels])
    interface.Set("numLevels", len(levels))
    interface.Set("Lines/lines", [(line_style, _pt(line_width_pt), color, False)])
    interface.Set("Fills/hide", True)
    interface.Set("SubLines/hide", True)
    interface.Set("ContourLabels/hide", not show_labels)
    interface.Set("keyLevels", False)
    interface.To("..")


def _add_veusz_scalar_field(interface: Any, scalar: dict[str, Any]) -> None:
    data_name = str(scalar["data_name"])
    interface.SetData2D(
        data_name,
        scalar["z_values"],
        xcent=[float(value) for value in scalar["x_values"]],
        ycent=[float(value) for value in scalar["y_values"]],
    )
    colormap_name = str(scalar["colormap_name"])
    colormap = [
        opaque_color_to_veusz_rgba(value)
        for value in normalize_opaque_colormap_colors(scalar["colormap_colors"])
    ]
    interface.AddCustom("colormap", colormap_name, colormap, mode="replace")
    # Veusz paints graph children in reverse object-tree order. Add overlays
    # first and the opaque image last so contours and the colorbar remain
    # visible above the scalar field.
    if scalar.get("show_contours") is True:
        _add_veusz_contour(
            interface,
            name="field_contours",
            data_name=data_name,
            levels=[float(value) for value in scalar.get("contour_levels") or []],
            color=str(scalar.get("contour_color") or "#FFFFFF"),
            line_style=str(scalar.get("contour_line_style") or "solid"),
            line_width_pt=UNIFIED_LINE_WIDTH_PT,
            show_labels=bool(scalar.get("contour_labels")),
        )
    _add_veusz_contour(
        interface,
        name="field_highlight_contours",
        data_name=data_name,
        levels=[float(value) for value in scalar.get("highlight_contour_levels") or []],
        color=str(scalar.get("highlight_contour_color") or UNIFIED_FOREGROUND_COLOR),
        line_style=str(scalar.get("highlight_contour_line_style") or "dashed"),
        line_width_pt=UNIFIED_LINE_WIDTH_PT,
        show_labels=False,
    )
    if scalar.get("show_colorbar") is True:
        interface.Add("colorbar", name="field_colorbar", autoadd=False)
        interface.To("field_colorbar")
        # Veusz WidgetChoice stores the sibling widget name, not an absolute
        # object-tree path.  An absolute path silently leaves the colorbar
        # detached and falls back to a synthetic 0--1 scale.
        interface.Set("widgetName", "field_image")
        # Keep the colorbar numerically identical to the image even though the
        # colorbar is created first to satisfy Veusz's reverse paint order.
        interface.Set("min", float(scalar["z_min"]))
        interface.Set("max", float(scalar["z_max"]))
        direction = (
            str(scalar.get("colorbar_direction") or "horizontal").strip().casefold()
        )
        if direction not in {"horizontal", "vertical"}:
            direction = "horizontal"
        interface.Set("direction", direction)
        if scalar.get("colorbar_manual_position") is True:
            interface.Set("horzPosn", "manual")
            interface.Set("vertPosn", "manual")
            interface.Set("horzManual", float(scalar["colorbar_horz_manual"]))
            interface.Set("vertManual", float(scalar["colorbar_vert_manual"]))
        elif direction == "horizontal":
            interface.Set("horzPosn", "right")
            interface.Set("vertPosn", "top")
        else:
            interface.Set("horzPosn", "manual")
            interface.Set("vertPosn", "manual")
            interface.Set("horzManual", float(scalar["colorbar_horz_manual"]))
            interface.Set("vertManual", float(scalar["colorbar_vert_manual"]))
        interface.Set("width", _cm_from_mm(float(scalar["colorbar_width_mm"])))
        interface.Set("height", _cm_from_mm(float(scalar["colorbar_height_mm"])))
        interface.Set(
            "label",
            _veusz_axis_label(str(scalar.get("z_label") or "Z")),
        )
        interface.Set("autoMirror", False)
        interface.Set("outerticks", True)
        foreground_color = str(
            scalar.get("colorbar_foreground_color") or UNIFIED_FOREGROUND_COLOR
        )
        interface.Set("Line/color", foreground_color)
        interface.Set("Line/width", _pt(float(scalar["colorbar_line_width_pt"])))
        interface.Set("Line/hide", False)
        interface.Set("Line/transparency", 0)
        interface.Set("Border/color", foreground_color)
        interface.Set("Border/width", _pt(float(scalar["colorbar_border_width_pt"])))
        interface.Set("Border/hide", False)
        interface.Set("Border/transparency", 0)
        interface.Set(
            "MajorTicks/width",
            _pt(float(scalar["colorbar_major_tick_width_pt"])),
        )
        interface.Set(
            "MajorTicks/length",
            _pt(float(scalar["colorbar_major_tick_length_pt"])),
        )
        interface.Set("MajorTicks/hide", False)
        interface.Set("MajorTicks/transparency", 0)
        interface.Set(
            "MinorTicks/width",
            _pt(float(scalar["colorbar_minor_tick_width_pt"])),
        )
        interface.Set(
            "MinorTicks/length",
            _pt(float(scalar["colorbar_minor_tick_length_pt"])),
        )
        interface.Set("MinorTicks/hide", False)
        interface.Set("MinorTicks/transparency", 0)
        interface.Set(
            "Label/size",
            _pt(float(scalar["colorbar_label_size_pt"])),
        )
        interface.Set("Label/color", foreground_color)
        interface.Set("Label/hide", False)
        interface.Set(
            "TickLabels/size",
            _pt(float(scalar["colorbar_tick_label_size_pt"])),
        )
        interface.Set("TickLabels/color", foreground_color)
        interface.Set("TickLabels/hide", False)
        interface.Set("TickLabels/format", str(scalar.get("z_tick_format") or "Auto"))
        z_ticks = (
            scalar.get("z_ticks") if isinstance(scalar.get("z_ticks"), list) else []
        )
        if 1 < len(z_ticks) <= 12:
            interface.Set("MajorTicks/manualTicks", [float(value) for value in z_ticks])
        interface.To("..")
    background_color = str(scalar.get("colorbar_background_color") or "").strip()
    if scalar.get("show_colorbar") is True and background_color:
        interface.Add("rect", name="field_colorbar_background", autoadd=False)
        interface.To("field_colorbar_background")
        interface.Set("positioning", "relative")
        interface.Set("xPos", [float(scalar["colorbar_background_x_fraction"])])
        interface.Set("yPos", [float(scalar["colorbar_background_y_fraction"])])
        interface.Set(
            "width",
            [float(scalar["colorbar_background_width_fraction"])],
        )
        interface.Set(
            "height",
            [float(scalar["colorbar_background_height_fraction"])],
        )
        interface.Set("clip", True)
        interface.Set("Fill/color", background_color)
        interface.Set("Fill/hide", False)
        interface.Set(
            "Fill/transparency",
            int(scalar["colorbar_background_transparency"]),
        )
        interface.Set("Border/hide", True)
        interface.To("..")
    interface.Add("image", name="field_image", autoadd=False)
    interface.To("field_image")
    interface.Set("data", data_name)
    interface.Set("min", float(scalar["z_min"]))
    interface.Set("max", float(scalar["z_max"]))
    interface.Set("colorScaling", str(scalar["zscale"]))
    interface.Set("colorMap", colormap_name)
    interface.Set("colorInvert", bool(scalar.get("color_invert")))
    interface.Set("mapping", str(scalar.get("field_mapping") or "bounds"))
    interface.Set("drawMode", str(scalar.get("field_draw_mode") or "rectangles"))
    interface.Set(
        "transparency",
        int(scalar.get("field_transparency") or 0),
    )
    interface.To("..")
