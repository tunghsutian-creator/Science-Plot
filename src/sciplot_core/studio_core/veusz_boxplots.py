"""Render native Veusz boxplots from categorical contracts."""

from __future__ import annotations

from typing import Any

from sciplot_core.policy import (
    CATEGORICAL_BOX_FILL_FRACTION,
    CATEGORICAL_BOX_FILL_TRANSPARENCY,
    CATEGORICAL_BOX_LINE_WIDTH_PT,
    DEFAULT_PALETTE_COLORS,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LINE_WIDTH_PT,
    categorical_box_native_fill_scale,
    categorical_fill_color,
    categorical_keyline_color,
)

from sciplot_core.studio_core.veusz_primitives import _add_veusz_axis_line
from sciplot_core.studio_core.veusz_units import _pt


def add_veusz_native_boxplots(
    interface: Any,
    categorical: dict[str, Any] | None,
) -> None:
    """Add eligible boxplot summaries with unified physical styling."""

    if categorical is None or categorical.get("native_veusz_boxplot") is not True:
        return
    categorical_style = (
        categorical.get("visual_style")
        if isinstance(categorical.get("visual_style"), dict)
        else {}
    )
    box_groups = [
        group
        for group in categorical.get("groups", [])
        if isinstance(group, dict) and group.get("boxplot_eligible") is True
    ]
    box_line_width = float(
        categorical_style.get("box_line_width_pt", CATEGORICAL_BOX_LINE_WIDTH_PT)
    )
    for box_index, group in enumerate(box_groups, start=1):
        box_color = str(
            group.get("color")
            or DEFAULT_PALETTE_COLORS[(box_index - 1) % len(DEFAULT_PALETTE_COLORS)]
        )
        fill_fraction = float(
            categorical_style.get("box_fill_fraction", CATEGORICAL_BOX_FILL_FRACTION)
        )
        native_fill_fraction = fill_fraction * float(
            categorical_style.get(
                "box_native_fill_scale",
                categorical_box_native_fill_scale(
                    category_count=len(categorical.get("groups") or [])
                ),
            )
        )
        position = float(group["position"])
        median = float(group["descriptive_statistics"]["median"])
        _add_veusz_axis_line(
            interface,
            name=f"categorical_box_median_{box_index}",
            x_pos=position - fill_fraction / 2.0,
            y_pos=median,
            x_pos_2=position + fill_fraction / 2.0,
            y_pos_2=median,
            color=UNIFIED_FOREGROUND_COLOR,
            width_pt=UNIFIED_LINE_WIDTH_PT,
        )
        keyline_color = str(
            group.get("keyline_color") or categorical_keyline_color(box_color)
        )
        interface.Add(
            "boxplot",
            name=f"categorical_boxplot_{box_index}",
            autoadd=False,
        )
        interface.To(f"categorical_boxplot_{box_index}")
        interface.Set("values", (str(group["y_name"]),))
        interface.Set("posn", [position])
        interface.Set(
            "whiskermode",
            str(categorical.get("box_whisker_mode") or "1.5IQR"),
        )
        interface.Set("fillfraction", native_fill_fraction)
        interface.Set("meanmarker", "none")
        interface.Set("outliersmarker", "none")
        interface.Set(
            "Fill/color",
            str(group.get("fill_color") or categorical_fill_color(box_color)),
        )
        interface.Set(
            "Fill/transparency",
            int(
                categorical_style.get(
                    "box_fill_transparency",
                    CATEGORICAL_BOX_FILL_TRANSPARENCY,
                )
            ),
        )
        interface.Set("Border/color", keyline_color)
        interface.Set("Border/width", _pt(box_line_width))
        interface.Set("Border/hide", False)
        interface.Set("Whisker/color", UNIFIED_FOREGROUND_COLOR)
        interface.Set("Whisker/width", _pt(UNIFIED_LINE_WIDTH_PT))
        interface.Set("MarkersLine/hide", True)
        interface.Set("MarkersFill/hide", True)
        interface.To("..")
