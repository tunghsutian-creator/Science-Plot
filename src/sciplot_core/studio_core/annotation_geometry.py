"""Compile validated annotation records into closed native widget settings."""

from __future__ import annotations

from typing import Any

from sciplot_core.policy import UNIFIED_FONT_FAMILY, UNIFIED_FONT_SIZE_PT, UNIFIED_FOREGROUND_COLOR, UNIFIED_LINE_WIDTH_PT
from sciplot_core.studio_core.annotation_contracts import PREFIX, annotation_records
from sciplot_core.studio_core.series_request import veusz_literal_text


def annotation_widgets(spec: dict[str, Any]) -> list[dict[str, Any]]:
    widgets = []
    for record in annotation_records(spec):
        name = PREFIX + record["id"]
        parent = record["parent_path"]
        if record["op"] == "add_reference_line":
            start = {a: spec["axes"][a]["min"] for a in ("x", "y")}
            end = {a: spec["axes"][a]["max"] for a in ("x", "y")}
            start[record["axis"]] = end[record["axis"]] = record["value"]
            widgets.append(_line(name, parent, "axes", start, end, arrow=False))
            continue
        position = record["position"]
        widgets.append({"path": f"{parent}/{name}", "name": name, "parent": parent,
                        "type": "label", "settings": {
            "hide": False, "label": veusz_literal_text(record["text"]),
            "positioning": position["mode"], "xAxis": "x", "yAxis": "y",
            "xPos": [position["x"]], "yPos": [position["y"]],
            "alignHorz": "left", "alignVert": "bottom", "angle": 0.0,
            "margin": "0pt", "clip": False,
            "Text/font": UNIFIED_FONT_FAMILY, "Text/size": f"{UNIFIED_FONT_SIZE_PT:g}pt",
            "Text/color": UNIFIED_FOREGROUND_COLOR, "Text/hide": False,
            "Text/bold": False, "Text/italic": False,
            "Background/hide": True, "Border/hide": True,
        }})
        if "arrow_to" in record:
            widgets.append(_line(name + "_arrow", parent, position["mode"], position,
                                 record["arrow_to"], arrow=True))
    if len({widget["path"] for widget in widgets}) != len(widgets):
        raise ValueError("Annotation IDs collide with a generated arrow path; use distinct IDs.")
    return widgets


def _line(name: str, parent: str, mode: str, start: dict[str, Any], end: dict[str, Any],
          *, arrow: bool) -> dict[str, Any]:
    return {"path": f"{parent}/{name}", "name": name, "parent": parent, "type": "line",
            "settings": {
                "hide": False, "positioning": mode, "xAxis": "x", "yAxis": "y",
                "mode": "point-to-point", "xPos": [start["x"]], "yPos": [start["y"]],
                "length": [0.2], "angle": [0.0],
                "xPos2": [end["x"]], "yPos2": [end["y"]], "clip": True,
                "Line/color": UNIFIED_FOREGROUND_COLOR,
                "Line/width": f"{UNIFIED_LINE_WIDTH_PT:g}pt", "Line/style": "solid" if arrow else "dashed",
                "Line/transparency": 0, "Line/hide": False,
                "arrowleft": "none", "arrowright": "arrow" if arrow else "none",
                "arrowSize": "5pt", "Fill/color": UNIFIED_FOREGROUND_COLOR,
                "Fill/hide": not arrow, "Fill/transparency": 0,
            }}
