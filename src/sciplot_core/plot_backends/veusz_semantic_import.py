"""Advertise only native semantic properties with a closed audited owner."""

from copy import deepcopy
import math
from typing import Any

from sciplot_core.studio_core.annotation_axes import axis_unit, require_scope
from sciplot_core.studio_core.annotation_legend import require_native_legend
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError


def axis_properties(obj: dict[str, Any], target: dict[str, Any],
                    widget: dict[str, Any], spec: dict[str, Any]) -> None:
    name = widget["name"]
    if name not in {"x", "y"} or target["object_path"] != f"/page1/graph1/{name}":
        return
    try:
        require_scope(spec)
    except AnnotationOperationError:
        return
    axis = spec.get("axes", {}).get(name, {})
    options, settings = spec.get("render_options", {}), widget.get("settings", {})
    bounds = [settings.get("min"), settings.get("max")]
    if (axis.get("scale") != "linear" or axis.get("mode", "numeric") != "numeric"
            or any(options.get(key) for key in (f"{name}_axis_breaks", f"extra_{name}_axis"))
            or any(type(value) not in {int, float} for value in bounds)
            or bounds != [axis.get("min"), axis.get("max")] or bounds[0] == bounds[1]):
        return
    low, high = sorted(bounds)
    if any(type(value) in {int, float} and math.isfinite(value) and not low <= value <= high
           for series in spec.get("series", []) for value in series.get(f"{name}_values", [])):
        # This executor cannot reintroduce existing clipping during rollback.
        # A clipped viewport remains owned by the explicit legacy range contract.
        return
    obj["properties"]["axis.limits"] = bounds
    obj["capabilities"]["axis.limits"] = {"type": "number_pair", "risk": "review",
                                          "direction": "ascending" if bounds[0] < bounds[1] else "descending"}
    target["properties"]["axis.limits"] = {"kind": "axis_limits", "axis": name,
                                          "unit": axis_unit(spec, name), "current_value": bounds}


def legend_properties(obj: dict[str, Any], target: dict[str, Any],
                      widget: dict[str, Any], spec: dict[str, Any]) -> None:
    if target["object_path"] != "/page1/graph1/key1":
        return
    try:
        legend = require_native_legend(spec)
    except AnnotationOperationError:
        return
    settings = widget.get("settings", {})
    if settings.get("hide") != (not legend["show"]):
        return
    obj["properties"]["legend.visible"] = legend["show"]
    obj["capabilities"]["legend.visible"] = {"type": "boolean", "risk": "review"}
    target["properties"]["legend.visible"] = {"kind": "legend_visibility", "current_value": legend["show"]}
    names = ("horzPosn", "vertPosn", "horzManual", "vertManual")
    fields = {field["setting_path"] for field in widget["editable_fields"]}
    if any(name not in settings or target["object_path"] + "/" + name not in fields for name in names):
        return
    placement = {name: settings[name] for name in names}
    if any(type(placement[name]) not in {float, int} or not 0 <= placement[name] <= 1 for name in names[2:]):
        return
    manual = all(placement[name] == "manual" for name in names[:2])
    value = [placement["horzManual"], placement["vertManual"]] if manual else None
    obj["properties"]["legend.position"] = value
    obj["capabilities"]["legend.position"] = {"type": "number_pair", "risk": "review",
                                              "coordinate_mode": "relative", "nullable": True}
    target["properties"]["legend.position"] = {"kind": "legend_position", "current_value": value,
                                              "initial_placement": deepcopy(placement), "placement": placement}


def managed_annotation(record: dict[str, Any], path: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if record["op"] != "add_annotation" or "peak_anchor" in record:
        return None
    kind = "title" if record["id"] == "spectrum_title" else "annotation"
    obj: dict[str, Any] = {"kind": kind, "label": record["text"], "properties": {
        kind + ".visible": True, kind + ".text": record["text"]}, "capabilities": {
        kind + ".visible": {"type": "boolean", "risk": "presentation" if kind == "title" else "review"},
        kind + ".text": {"type": "string", "risk": "review", "min_length": 1,
                          "max_length": 500, "non_blank": True}}}
    if kind == "annotation":
        position = record["position"]
        obj["properties"]["annotation.position"] = [position["x"], position["y"]]
        cap: dict[str, Any] = {"type": "number_pair", "risk": "review", "coordinate_mode": position["mode"]}
        if position["mode"] == "axes":
            cap["units"] = {"x": position["x_unit"], "y": position["y_unit"]}
        obj["capabilities"]["annotation.position"] = cap
    target = {"object_path": path, "annotation": deepcopy(record), "properties": {
        prop: {"kind": "annotation"} for prop in obj["properties"]}}
    return obj, target
