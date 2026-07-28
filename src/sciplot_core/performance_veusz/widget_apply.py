"""Add performance axes, keys, series, polygons, lines, and labels to Veusz."""

from __future__ import annotations

from typing import Any
from sciplot_core.materials_rules import format_plot_text_units
from sciplot_core.policy import (
    UNIFIED_LEGEND_KEY_LENGTH_MM,
)

from sciplot_core.performance_veusz.style import (
    _pt,
    _literal_text,
)


def _add_label(interface: Any, item: dict[str, Any]) -> None:
    interface.Add("label", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("positioning", item["positioning"])
    interface.Set("xAxis", item["x_axis"])
    interface.Set("yAxis", item["y_axis"])
    interface.Set("xPos", [float(item["x"])])
    interface.Set("yPos", [float(item["y"])])
    interface.Set("label", _literal_text(item["label"]))
    interface.Set("alignHorz", item["align"])
    interface.Set("alignVert", item["valign"])
    interface.Set("angle", float(item["angle_degrees"]))
    interface.Set("margin", _pt(float(item["margin_pt"])))
    interface.Set("clip", bool(item["clip"]))
    interface.Set("hide", False)
    interface.Set("Text/size", _pt(float(item["text_size_pt"])))
    interface.Set("Text/color", item["text_color"])
    interface.Set("Text/hide", bool(item["text_hide"]))
    interface.Set("Background/color", item["background_color"])
    interface.Set(
        "Background/transparency",
        int(item["background_transparency"]),
    )
    interface.Set("Background/hide", bool(item["background_hide"]))
    interface.Set("Border/color", item["border_color"])
    interface.Set("Border/width", _pt(float(item["border_width_pt"])))
    interface.Set("Border/style", item["border_style"])
    interface.Set("Border/transparency", int(item["border_transparency"]))
    interface.Set("Border/hide", bool(item["border_hide"]))
    interface.To("..")


def _add_axis(
    interface: Any,
    *,
    name: str,
    axis: dict[str, Any],
    style: dict[str, Any],
) -> None:
    interface.Add("axis", name=name, autoadd=False)
    interface.To(name)
    interface.Set("label", format_plot_text_units(axis["label"]))
    if name == "y":
        interface.Set("direction", "vertical")
    interface.Set("autoMirror", False)
    interface.Set("outerticks", True)
    hidden = bool(axis.get("hidden"))
    foreground = str(axis["foreground_color"])
    interface.Set("Line/color", foreground)
    interface.Set("Line/width", _pt(float(axis["line_width_pt"])))
    interface.Set("Line/hide", hidden)
    interface.Set("Line/transparency", 0)
    interface.Set("MajorTicks/width", _pt(float(axis["major_tick_width_pt"])))
    interface.Set("MajorTicks/length", _pt(float(axis["major_tick_length_pt"])))
    interface.Set("MajorTicks/hide", hidden)
    interface.Set("MajorTicks/transparency", 0)
    interface.Set("MinorTicks/width", _pt(float(axis["minor_tick_width_pt"])))
    interface.Set("MinorTicks/length", _pt(float(axis["minor_tick_length_pt"])))
    interface.Set("MinorTicks/number", int(axis["minor_tick_count"]))
    interface.Set("MinorTicks/hide", hidden)
    interface.Set("MinorTicks/transparency", 0)
    interface.Set("Label/size", _pt(float(axis["label_size_pt"])))
    interface.Set("Label/color", foreground)
    interface.Set("Label/hide", hidden or not bool(axis["label"]))
    interface.Set("Label/offset", _pt(float(style["axes_labelpad_pt"])))
    interface.Set("TickLabels/size", _pt(float(axis["tick_label_size_pt"])))
    interface.Set("TickLabels/color", foreground)
    interface.Set("TickLabels/format", axis["tick_format"])
    interface.Set("TickLabels/hide", hidden)
    interface.Set(
        "TickLabels/offset",
        _pt(
            float(style["xtick_major_pad_pt" if name == "x" else "ytick_major_pad_pt"])
        ),
    )
    interface.Set("min", float(axis["min"]))
    interface.Set("max", float(axis["max"]))
    interface.To("..")


def _apply_inside_key_position(interface: Any, legend: dict[str, Any]) -> None:
    mode = str(legend.get("mode") or "inside_best").strip().casefold()
    horz_position = legend.get("horz_position")
    vert_position = legend.get("vert_position")
    if mode == "manual" or horz_position is not None or vert_position is not None:
        horz = str(horz_position or "manual")
        vert = str(vert_position or "manual")
        interface.Set("horzPosn", horz)
        interface.Set("vertPosn", vert)
        if horz == "manual":
            interface.Set(
                "horzManual",
                float(
                    legend["horz_manual"]
                    if legend.get("horz_manual") is not None
                    else 0.5
                ),
            )
        if vert == "manual":
            interface.Set(
                "vertManual",
                float(
                    legend["vert_manual"]
                    if legend.get("vert_manual") is not None
                    else 0.5
                ),
            )
        return
    if mode in {"upper_right", "top_right"}:
        interface.Set("horzPosn", "right")
        interface.Set("vertPosn", "top")
        return
    if mode in {"upper_left", "top_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "top")
        return
    if mode in {"lower_left", "bottom_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "bottom")
        return
    interface.Set("horzPosn", "right")
    interface.Set("vertPosn", "bottom")


def _add_inside_key(
    interface: Any,
    legend: dict[str, Any],
    style: dict[str, Any],
) -> None:
    if not bool(legend.get("show")):
        return
    interface.Add("key", name="key1", autoadd=False)
    interface.To("key1")
    interface.Set("title", "")
    interface.Set("Text/size", _pt(float(style["legend_font_size_pt"])))
    interface.Set(
        "keyLength",
        f"{UNIFIED_LEGEND_KEY_LENGTH_MM / 10.0:.2f}cm",
    )
    interface.Set("marginSize", 0.15)
    interface.Set("columns", int(legend.get("columns") or 1))
    _apply_inside_key_position(interface, legend)
    interface.Set("Background/hide", not bool(style["legend_frameon"]))
    interface.Set("Border/hide", not bool(style["legend_frameon"]))
    interface.To("..")


def _add_xy_series(
    interface: Any,
    item: dict[str, Any],
    style: dict[str, Any],
) -> None:
    interface.Add("xy", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("xData", item["x_name"])
    interface.Set("yData", item["y_name"])
    interface.Set("key", _literal_text(item["legend_key"]))
    interface.Set("ErrorBarLine/hide", True)
    interface.Set("PlotLine/color", item["color"])
    interface.Set("PlotLine/style", item["line_style"])
    interface.Set("PlotLine/width", _pt(float(item["line_width_pt"])))
    interface.Set("PlotLine/transparency", 8)
    interface.Set("PlotLine/hide", bool(item["plot_line_hide"]))
    interface.Set("marker", item["marker"])
    interface.Set("markerSize", _pt(float(item["marker_size_pt"])))
    interface.Set("MarkerFill/color", item["marker_fill_color"])
    interface.Set("MarkerFill/transparency", 5)
    interface.Set("MarkerFill/hide", False)
    interface.Set("MarkerLine/color", item["color"])
    interface.Set(
        "MarkerLine/width",
        _pt(float(style["marker_line_width_pt"])),
    )
    interface.Set("MarkerLine/transparency", 5)
    interface.Set("MarkerLine/hide", False)
    interface.To("..")


def _add_polygon(interface: Any, item: dict[str, Any]) -> None:
    interface.Add("polygon", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("positioning", item["positioning"])
    interface.Set("xAxis", item["x_axis"])
    interface.Set("yAxis", item["y_axis"])
    interface.Set("xPos", item["xPos"])
    interface.Set("yPos", item["yPos"])
    interface.Set("hide", False)
    interface.Set("Line/color", item["line_color"])
    interface.Set("Line/width", _pt(float(item["line_width_pt"])))
    interface.Set("Line/style", item["line_style"])
    interface.Set("Line/transparency", int(item["line_transparency"]))
    interface.Set("Line/hide", bool(item["line_hide"]))
    interface.Set("Fill/color", item["fill_color"])
    interface.Set("Fill/transparency", int(item["fill_transparency"]))
    interface.Set("Fill/hide", bool(item["fill_hide"]))
    interface.To("..")


def _add_line(interface: Any, item: dict[str, Any]) -> None:
    interface.Add("line", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("positioning", item["positioning"])
    interface.Set("xAxis", item["x_axis"])
    interface.Set("yAxis", item["y_axis"])
    interface.Set("mode", item["mode"])
    interface.Set("xPos", item["xPos"])
    interface.Set("yPos", item["yPos"])
    interface.Set("xPos2", item["xPos2"])
    interface.Set("yPos2", item["yPos2"])
    interface.Set("clip", bool(item["clip"]))
    interface.Set("hide", False)
    interface.Set("Line/color", item["line_color"])
    interface.Set("Line/width", _pt(float(item["line_width_pt"])))
    interface.Set("Line/style", item["line_style"])
    interface.Set("Line/transparency", int(item["line_transparency"]))
    interface.Set("Line/hide", bool(item["line_hide"]))
    interface.Set("arrowleft", item["arrow_left"])
    interface.Set("arrowright", item["arrow_right"])
    interface.Set("Fill/hide", bool(item["fill_hide"]))
    interface.To("..")
