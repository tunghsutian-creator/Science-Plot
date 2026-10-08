"""Resolve axes and semantic legend entries into physical text and symbol anchors."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from sciplot_core.plot_document.errors import fail

from .decorations import PT_MM, guide_size, text_width_mm


def _fraction(value: float, scale: dict[str, Any]) -> float:
    low, high = scale["domain"]
    if scale["transform"] == "log":
        fraction = (math.log(value) - math.log(low)) / (math.log(high) - math.log(low))
    elif scale["transform"] == "linear":
        fraction = (value - low) / (high - low)
    else:
        fail("figure_layout_scale_unsupported", "This layout version supports linear and log scales.", "/scales", "capability")
    return 1.0 - fraction if scale["direction"] == "descending" else fraction


def resolve_axis_text(layout: dict[str, Any], axes: list[dict[str, Any]],
                      scales: list[dict[str, Any]]) -> list[dict[str, Any]]:
    panels = {panel["view_id"]: panel for panel in layout["panels"]}
    scale_lookup = {scale["id"]: scale for scale in scales}
    result = deepcopy(axes)
    for axis in result:
        panel = panels[axis["view_id"]]
        x, y, width, height = panel["plot_mm"]
        font = float(axis["style"]["font_size_pt"])
        tick = float(axis["style"]["tick_length_pt"]) * PT_MM
        offset = 2.0 + tick + font * PT_MM * 0.8
        positions = []
        for value in axis["ticks"]:
            fraction = _fraction(float(value), scale_lookup[axis["scale_id"]])
            positions.append({
                "bottom": [x + fraction * width, y + height + offset],
                "top": [x + fraction * width, y - offset],
                "left": [x - tick - 2.0, y + (1.0 - fraction) * height],
                "right": [x + width + tick + 2.0, y + (1.0 - fraction) * height],
            }[axis["side"]])
        widest = max((text_width_mm(label, font) for label in axis["tick_labels"]), default=0.0)
        label_offset = offset + font * PT_MM * 1.8 + 1.5
        vertical_offset = tick + 2.0 + widest + font * PT_MM * 1.0 + 1.5
        axis["tick_positions_mm"] = positions
        axis["tick_alignment"] = {"bottom": "center", "top": "center", "left": "right", "right": "left"}[axis["side"]]
        axis["label_position_mm"] = {
            "bottom": [x + width / 2, y + height + label_offset],
            "top": [x + width / 2, y - label_offset],
            "left": [x - vertical_offset, y + height / 2],
            "right": [x + width + vertical_offset, y + height / 2],
        }[axis["side"]]
        axis["label_angle"] = 0 if axis["side"] in {"bottom", "top"} else 90
        axis["decorations_visible"] = bool(axis["visible"] and axis["id"] not in panel["suppressed_axis_ids"])
    return result


def resolve_guides(layout: dict[str, Any], guides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    panels = {panel["view_id"]: panel for panel in layout["panels"]}
    result = deepcopy(guides)
    for guide in result:
        width, height = guide_size(guide)
        view_id = guide.get("view_id")
        if view_id is None:
            rectangle = layout["figure_guide_bounds_mm"]
            if not guide["visible"]:
                rectangle = [0.0, 0.0, width, height]
            if rectangle is None:
                fail("figure_layout_legend_missing", "A visible figure legend needs a reserved area.", "/guides", "reserved_area")
            x, y = rectangle[:2]
        else:
            x0, y0, plot_width, plot_height = panels[view_id]["plot_mm"]
            if guide["location"] not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
                fail("figure_layout_guide_location", "View legends need a view-corner location.", "/guides", "guide_scope")
            if guide["visible"] and (width + 2.0 > plot_width or height + 2.0 > plot_height):
                fail("figure_layout_legend_no_space", "The view legend exceeds its plot area.", "/guides", "legend_space", guide_id=guide["id"])
            x = x0 + 1.0 if guide["location"].endswith("left") else x0 + plot_width - width - 1.0
            y = y0 + 1.0 if guide["location"].startswith("top") else y0 + plot_height - height - 1.0
            rectangle = [x, y, width, height]
        guide["rect_mm"] = list(rectangle)
        columns = int(guide["columns"])
        row_height = float(guide["style"]["font_size_pt"]) * PT_MM * 1.8
        cell_width = (width - 4.0) / columns
        for index, entry in enumerate(guide["entries"]):
            column, row = index % columns, index // columns
            line_y = y + 2.0 + (row + 0.5) * row_height
            symbol_height = min(row_height * 0.55, 2.5)
            entry["symbol_mm"] = [x + 2.0 + column * cell_width, line_y - symbol_height / 2, 6.0, symbol_height]
            entry["label_mm"] = [x + 10.0 + column * cell_width, line_y]
    return result
