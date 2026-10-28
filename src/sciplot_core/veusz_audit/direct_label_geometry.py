"""Actual painted inline text versus fixed frames and complete visible XY marks."""
from __future__ import annotations

import math
import re
from typing import Any

from sciplot_core.foundation.rectangle_geometry import rectangle_distance
from sciplot_core.studio_render.direct_label_layout import NATIVE_TEXT_GUARD_MM
from sciplot_core.veusz_audit.legend_geometry import _curve_distance
from sciplot_core.veusz_audit.measurements import _setting_hidden
from sciplot_core.veusz_audit.segmented_legend_geometry import _painted_box


def collect_direct_label_geometry(ordered: list[tuple[str, Any]],
                                  states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Read existing native paint state; never rearrange a current document.

    Selection for a blocking publication contract belongs to the persisted new
    layout version, not to a label string or an old VSZ's widget names.
    """
    labels: list[tuple[str, Any, dict[str, Any], list[float], list[float]]] = []
    hidden: list[str] = []
    curves: list[tuple[str, Any]] = []
    hidden_curves: list[tuple[str, Any]] = []
    unsupported: list[dict[str, str]] = []
    for path, widget in ordered:
        if widget.typename == "xy":
            (hidden_curves if _setting_hidden(widget.settings) else curves).append((path, widget))
        if widget.typename != "label" or re.fullmatch(r"label_\d+", str(widget.name)) is None:
            continue
        if _setting_hidden(widget.settings) or _setting_hidden(widget.settings.Text):
            hidden.append(path)
            continue
        try:
            state = states[path]
            box = _painted_box(widget, state)
            if not _setting_hidden(widget.settings.Border) or not _setting_hidden(widget.settings.Background):
                raise ValueError("Automatic inline text clearance requires its recorded transparent undecorated label.")
            guard = NATIVE_TEXT_GUARD_MM
            reserved = [box[0]-guard, box[1]-guard, box[2]+guard, box[3]+guard]
            labels.append((path, widget, state, box, reserved))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            unsupported.append({"path": path, "reason": str(exc)})
    records, outside = [], []
    for path, widget, state, box, reserved in labels:
        try:
            plot = states[str(widget.parent.path)]["bounds_mm"]
            if (not isinstance(plot, list) or len(plot) != 4
                    or not all(isinstance(value, int | float) and math.isfinite(value) for value in plot)):
                raise ValueError("The actual fixed graph frame is unavailable.")
            if reserved[0] < plot[0] or reserved[1] < plot[1] or reserved[2] > plot[2] or reserved[3] > plot[3]:
                outside.append(path)
            distances = [_curve_distance(curve, states[curve_path], reserved)
                for curve_path, curve in curves if curve.parent is widget.parent]
            if not distances or not all(math.isfinite(value) and value >= 0 for value in distances):
                raise ValueError("Every visible curve must have supported complete native geometry.")
            peers = [rectangle_distance(reserved, other_box) for other_path, other, _, _, other_box in labels
                     if other_path != path and other.parent is widget.parent]
            records.append({"path": path, "graph_path": str(widget.parent.path), "page": state["page"],
                "bounds_mm": box, "guarded_bounds_mm": reserved,
                "minimum_curve_clearance_mm": min(distances),
                "minimum_label_clearance_mm": min(peers) if peers else None})
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            unsupported.append({"path": path, "reason": str(exc)})
    return {"kind": "sciplot_native_direct_label_geometry", "version": 1,
        "coverage_complete": not unsupported, "labels": records, "hidden_labels": sorted(hidden),
        "outside_plot_paths": sorted(outside), "data_paths": sorted(path for path, _ in curves),
        "hidden_data_paths": sorted(path for path, _ in hidden_curves), "unsupported": unsupported,
        "text_guard_mm": NATIVE_TEXT_GUARD_MM,
        "envelope": "native_text_renderer_bounds_with_overhang_guard_and_complete_visible_xy_geometry"}
