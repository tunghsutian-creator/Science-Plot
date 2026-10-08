"""Conservative physical decoration budgets; final native metrics are audited."""

from __future__ import annotations

import unicodedata
from typing import Any

PT_MM = 25.4 / 72.0


def text_width_mm(text: str, font_size_pt: float) -> float:
    """An explicit conservative estimate, never presented as native text bounds."""
    cells = sum(1.7 if unicodedata.east_asian_width(char) in {"W", "F"} else 1.0 for char in text)
    return cells * font_size_pt * PT_MM * 0.72


def suppression(layout: dict[str, Any], axes: list[dict[str, Any]]) -> set[str]:
    cells = {cell["view_id"]: cell for cell in layout["cells"]}
    hidden: set[str] = set()
    for group in layout.get("resolve", []):
        for dimension in ("x", "y"):
            if group.get(dimension) != "shared":
                continue
            candidates = [axis for axis in axes if axis["view_id"] in group["views"]
                          and axis["side"] in ({"bottom", "top"} if dimension == "x" else {"left", "right"})
                          and axis["visible"]]
            for axis in candidates:
                own = cells[axis["view_id"]]
                for other in candidates:
                    if other["id"] == axis["id"] or other["scale_id"] != axis["scale_id"] or other["side"] != axis["side"]:
                        continue
                    peer = cells[other["view_id"]]
                    aligned = own["column"] == peer["column"] if dimension == "x" else own["row"] == peer["row"]
                    outer = {"bottom": peer["row"] > own["row"], "top": peer["row"] < own["row"],
                             "left": peer["column"] < own["column"], "right": peer["column"] > own["column"]}[axis["side"]]
                    if aligned and outer:
                        hidden.add(axis["id"])
    return hidden


def decoration_budget(axes: list[dict[str, Any]], hidden: set[str], *, panel_label_height_mm: float,
                      has_label: bool) -> dict[str, float]:
    budget = {side: 2.0 for side in ("left", "right", "top", "bottom")}
    budget.update(min_width=12.0, min_height=12.0)
    if has_label:
        budget["top"] += panel_label_height_mm
    for axis in axes:
        if not axis["visible"] or axis["id"] in hidden:
            continue
        font = float(axis["style"]["font_size_pt"])
        tick_length = float(axis["style"]["tick_length_pt"]) * PT_MM
        ticks = axis.get("tick_labels", ["−0.00000", "0.00000"])
        widest = max((text_width_mm(str(label), font) for label in ticks), default=0.0)
        label = str(axis["label"]) if axis["label_visible"] else ""
        horizontal = axis["side"] in {"bottom", "top"}
        thickness = font * PT_MM * 1.7 if horizontal else widest
        thickness += tick_length + 2.0
        if label:
            thickness += font * PT_MM * 1.8 + 1.5
            key = "min_width" if horizontal else "min_height"
            budget[key] = max(budget[key], text_width_mm(label, font) + 3.0)
        budget[axis["side"]] += thickness
        if horizontal:
            # End ticks extend half their measured width past the plot spine.
            budget["left"] = max(budget["left"], widest * 0.5 + 1.5)
            budget["right"] = max(budget["right"], widest * 0.5 + 1.5)
        else:
            budget["top"] = max(budget["top"], font * PT_MM + 1.5)
            budget["bottom"] = max(budget["bottom"], font * PT_MM + 1.5)
    return budget


def guide_size(guide: dict[str, Any]) -> tuple[float, float]:
    font = float(guide["style"]["font_size_pt"])
    labels = [str(entry["label"]) for entry in guide.get("entries", [])]
    columns = int(guide["columns"])
    rows = (len(labels) + columns - 1) // columns
    cell_width = max((text_width_mm(label, font) for label in labels), default=0.0) + 9.0
    return columns * cell_width + 4.0, rows * font * PT_MM * 1.8 + 4.0
