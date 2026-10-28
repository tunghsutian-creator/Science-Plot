"""Measure actual painted component labels/swatches against grouped bars and SD."""
from __future__ import annotations

import math
from importlib import import_module
from typing import Any

from sciplot_core.foundation.rectangle_geometry import (
    rectangle_distance as _rectangle_distance,
    segment_box_distance as _segment_box,
)
from sciplot_core.veusz_audit.measurements import _distance_pt, _setting_hidden


def _painted_box(widget: Any, state: dict[str, Any], *, allow_empty: bool = False) -> list[float]:
    controlgraph = import_module("veusz.widgets.controlgraph")

    controls = state["helper"].getControlGraph(widget) or []
    if len(controls) != 1:
        raise ValueError("One complete painted component rectangle is required.")
    control = controls[0]
    if isinstance(control, controlgraph.ControlMovableBox):
        values = list(control.posn)
    elif isinstance(control, controlgraph.ControlResizableBox) and float(control.angle) == 0:
        x, y = control.posn
        width, height = control.dims
        values = [x-width/2, y-height/2, x+width/2, y+height/2]
    else:
        raise ValueError("Unsupported rotated or unmeasured component geometry.")
    box = [float(value) * 25.4 / 72 for value in values]
    if (not all(math.isfinite(value) for value in box) or box[2] < box[0] or box[3] < box[1]
            or (not allow_empty and (box[2] == box[0] or box[3] == box[1]))):
        raise ValueError("Component bounds must be positive and finite.")
    return box



def collect_segmented_legend_geometry(ordered: list[tuple[str, Any]],
                                      states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    controlgraph = import_module("veusz.widgets.controlgraph")

    labels: list[tuple[str, Any, dict[str, Any], list[float]]] = []
    marks: list[tuple[str, Any, dict[str, Any]]] = []
    unsupported: list[dict[str, str]] = []
    for path, widget in ordered:
        if _setting_hidden(widget.settings):
            continue
        legend = str(widget.name).startswith(("component_legend_label_", "component_legend_swatch_"))
        data = str(widget.name).startswith(("categorical_bar_fill_", "categorical_bar_error_", "categorical_bar_outline_"))
        if not legend and not data:
            continue
        try:
            state = states[path]
            if legend:
                labels.append((path, widget, state, _painted_box(widget, state)))
            else:
                marks.append((path, widget, state))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            unsupported.append({"path": path, "reason": str(exc)})
    records: list[dict[str, Any]] = []
    outside: list[str] = []
    for path, widget, state, box in labels:
        minimum = math.inf
        try:
            plot = states[str(widget.parent.path)]["bounds_mm"]
            if not isinstance(plot, list) or len(plot) != 4:
                raise ValueError("The actual fixed graph frame is unavailable.")
            if box[0] < plot[0] or box[1] < plot[1] or box[2] > plot[2] or box[3] > plot[3]:
                outside.append(path)
            for data_path, data, data_state in marks:
                if data.parent is not widget.parent:
                    continue
                if data.typename == "rect":
                    distance = _rectangle_distance(_painted_box(data, data_state, allow_empty=True), box)
                elif data.typename == "line":
                    controls = data_state["helper"].getControlGraph(data) or []
                    if len(controls) != 1 or not isinstance(controls[0], controlgraph.ControlLine):
                        raise ValueError(f"A complete painted bar/SD stroke is required: {data_path}")
                    width = _distance_pt(data.settings.Line.get("width"), data_state["helper"])
                    if width is None or width <= 0:
                        raise ValueError("The actual bar/SD stroke width is unavailable.")
                    x1, y1, x2, y2 = [float(value) * 25.4 / 72 for value in controls[0].line]
                    distance = max(0, _segment_box((x1, y1), (x2, y2), box)
                                   - math.sqrt(2) * width * 25.4 / 144)
                else:
                    raise ValueError("Only the existing grouped rectangle/line marks establish this clearance.")
                minimum = min(minimum, distance)
            if not math.isfinite(minimum):
                raise ValueError("No complete original grouped bar/SD geometry was measured.")
            records.append({"path": path, "graph_path": str(widget.parent.path), "page": state["page"],
                "bounds_mm": box, "minimum_curve_clearance_mm": minimum})
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            unsupported.append({"path": path, "reason": str(exc)})
    return {"kind": "sciplot_native_segmented_legend_geometry", "version": 1,
        "coverage_complete": not unsupported, "legends": records,
        "outside_plot_paths": sorted(outside),
        "data_paths": sorted(path for path, _, _ in marks), "unsupported": unsupported,
        "envelope": "actual_painted_component_boxes_and_grouped_bar_sd_strokes"}
