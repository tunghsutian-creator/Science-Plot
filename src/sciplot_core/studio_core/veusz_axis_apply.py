"""Apply key placement and one complete axis contract to Veusz."""

from __future__ import annotations

from typing import Any
from sciplot_core.studio_render.categorical_values import (
    _veusz_axis_label,
)

from sciplot_core.studio_core.veusz_units import (
    _pt,
)


def _apply_key_position(
    interface: Any,
    mode: str,
    *,
    horz_position: str | None = None,
    vert_position: str | None = None,
    horz_manual: float | None = None,
    vert_manual: float | None = None,
) -> None:
    normalized = str(mode or "inside_best").strip().casefold()
    if normalized == "manual" or horz_position is not None or vert_position is not None:
        horz = str(horz_position or "manual")
        vert = str(vert_position or "manual")
        interface.Set("horzPosn", horz)
        interface.Set("vertPosn", vert)
        if horz == "manual":
            interface.Set(
                "horzManual", float(horz_manual if horz_manual is not None else 0.5)
            )
        if vert == "manual":
            interface.Set(
                "vertManual", float(vert_manual if vert_manual is not None else 0.5)
            )
        return
    if normalized in {"upper_right", "top_right"}:
        interface.Set("horzPosn", "right")
        interface.Set("vertPosn", "top")
        return
    if normalized in {"upper_left", "top_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "top")
        return
    if normalized in {"lower_left", "bottom_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "bottom")
        return
    interface.Set("horzPosn", "right")
    interface.Set("vertPosn", "bottom")


def _add_veusz_axis(
    interface: Any, axis: str, axis_spec: dict[str, Any], style: dict[str, Any]
) -> None:
    interface.Add("axis", name=axis, autoadd=False)
    interface.To(axis)
    interface.Set("label", _veusz_axis_label(axis_spec["label"]))
    if axis == "y":
        interface.Set("direction", "vertical")
    if axis_spec.get("mode") == "labels":
        interface.Set("mode", "labels")
    interface.Set("autoMirror", False)
    interface.Set("outerticks", True)
    foreground_color = str(axis_spec["foreground_color"])
    interface.Set("Line/color", foreground_color)
    interface.Set("Line/width", _pt(float(axis_spec["line_width_pt"])))
    interface.Set("Line/hide", False)
    interface.Set("Line/transparency", 0)
    interface.Set(
        "MajorTicks/width",
        _pt(float(axis_spec["major_tick_width_pt"])),
    )
    interface.Set(
        "MajorTicks/length",
        _pt(float(axis_spec["major_tick_length_pt"])),
    )
    interface.Set("MajorTicks/transparency", 0)
    interface.Set(
        "MinorTicks/width",
        _pt(float(axis_spec["minor_tick_width_pt"])),
    )
    interface.Set(
        "MinorTicks/length",
        _pt(float(axis_spec["minor_tick_length_pt"])),
    )
    interface.Set("MinorTicks/transparency", 0)
    interface.Set("MinorTicks/number", int(axis_spec.get("minor_tick_count") or 20))
    minor_ticks = (
        axis_spec.get("minor_ticks")
        if isinstance(axis_spec.get("minor_ticks"), list)
        else []
    )
    if minor_ticks:
        interface.Set("MinorTicks/hide", False)
        interface.Set("MinorTicks/manualTicks", [float(value) for value in minor_ticks])
    interface.Set("Label/size", _pt(float(axis_spec["label_size_pt"])))
    interface.Set("Label/color", foreground_color)
    interface.Set("Label/hide", False)
    interface.Set("Label/offset", _pt(float(style["axes_labelpad_pt"])))
    interface.Set(
        "TickLabels/size",
        _pt(float(axis_spec["tick_label_size_pt"])),
    )
    interface.Set("TickLabels/color", foreground_color)
    interface.Set("TickLabels/format", str(axis_spec.get("tick_format") or "Auto"))
    if (
        axis == "x"
        and axis_spec.get("mode") == "labels"
        and len(axis_spec.get("category_labels") or []) > 4
    ):
        interface.Set("TickLabels/rotate", "45")
    tick_offset = (
        style["xtick_major_pad_pt"] if axis == "x" else style["ytick_major_pad_pt"]
    )
    interface.Set("TickLabels/offset", _pt(float(tick_offset)))
    if axis == "y" and axis_spec.get("show_ticks") is False:
        interface.Set("MajorTicks/hide", True)
        interface.Set("MinorTicks/hide", True)
        interface.Set("TickLabels/hide", True)
    if axis_spec.get("min") is not None:
        interface.Set("min", float(axis_spec["min"]))
    if axis_spec.get("max") is not None:
        interface.Set("max", float(axis_spec["max"]))
    ticks = axis_spec.get("ticks") if isinstance(axis_spec.get("ticks"), list) else []
    if 1 < len(ticks) <= 12:
        interface.Set("MajorTicks/manualTicks", [float(value) for value in ticks])
    if axis_spec.get("scale") == "log":
        interface.Set("log", True)
    interface.To("..")
