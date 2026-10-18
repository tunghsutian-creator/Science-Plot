"""Covered native display values; no semantic adoption of unknown VSZ state."""

from __future__ import annotations

import math
from importlib import import_module
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.rheology_tts_presentation_audit import native_legend_position_fields

CORNERS = {"top-left": "upper_left", "top-right": "upper_right",
           "bottom-left": "lower_left", "bottom-right": "lower_right"}


def native_targets(figure: dict[str, Any]) -> dict[str, Any]:
    """Cheap target metadata from an already successfully created native spec."""
    targets = {}
    for panel in figure["panels"]:
        if panel["legend"]:
            targets[f"legend:{panel['id']}"] = {"kind": "legend", "label": panel["id"],
                                               "properties": ["legend.location"]}
        for index, note in enumerate(panel["notes"]):
            targets[f"annotation:{panel['id']}:note_{index}"] = {"kind": "annotation", "label": str(note["text"]),
                "properties": ["annotation.text", "annotation.x", "annotation.y"]}
    return targets


def _field(value: Any) -> dict[str, Any]:
    return {"value": value, "kind": "exact", "setting": None, "indices": ()}


def display_targets(document: Any, figure: dict[str, Any]) -> dict[str, Any]:
    """Expose only existing known keys and scalar, relative note widgets."""
    CommandInterface = import_module("veusz.document").CommandInterface

    interface = CommandInterface(document)
    result = {}
    for panel in figure["panels"]:
        graph = f"/page1/{panel['id']}"
        children = interface.GetChildren(graph)
        if panel["legend"] and "key1" in children:
            path = graph + "/key1"
            interface.To(path)
            values = {key: interface.Get(key) for key in ("horzPosn", "vertPosn")}
            current = next((name for name, native in CORNERS.items()
                if all(values[key] == field["value"] for key, field in
                       native_legend_position_fields(native).items())), None)
            result[f"legend:{panel['id']}"] = {
                "kind": "legend", "label": panel["id"], "path": path,
                "properties": {"legend.location": current}, "native_fields": values}
        for index, _note in enumerate(panel["notes"]):
            name = f"note_{index}"
            if name not in children:
                continue
            path = graph + "/" + name
            widget = document.resolveWidgetPath(document.basewidget, path)
            if widget.typename != "label":
                continue
            interface.To(path)
            if interface.Get("positioning") != "relative":
                continue
            x, y = interface.Get("xPos"), interface.Get("yPos")
            if (not isinstance(x, (list, tuple)) or not isinstance(y, (list, tuple))
                    or len(x) != 1 or len(y) != 1
                    or any(not isinstance(v, (int, float)) or not math.isfinite(v)
                           for v in (x[0], y[0]))):
                continue
            text = interface.Get("label")
            if not isinstance(text, str):
                continue
            result[f"annotation:{panel['id']}:{name}"] = {
                "kind": "annotation", "label": text, "path": path,
                "properties": {"annotation.text": text, "annotation.x": x[0], "annotation.y": y[0]},
                "native_fields": {"label": text, "xPos": list(x), "yPos": list(y)}}
    return result


def read_display_state(path: Path, figure: dict[str, Any]) -> dict[str, Any]:
    document = import_module("veusz.document")
    from sciplot_core.rheology_tts_native import audit_native_figure

    before = file_sha256(path)
    audit = audit_native_figure(path, figure, check_presentation=False)
    doc = document.Document()
    doc.load(str(path))
    targets = display_targets(doc, figure)
    if before != file_sha256(path):
        raise ValueError("Native document changed during display inspection.")
    return {"document_sha256": before, "targets": targets, "scientific_audit": audit,
            "panel_widget_order": {panel["id"]: list(doc.resolveWidgetPath(doc.basewidget,
                f"/page1/{panel['id']}").childnames) for panel in figure["panels"]}}


def patch_display_document(path: Path, out: Path, figure: dict[str, Any], changes: list[dict[str, Any]],
                           expected_sha256: str) -> dict[str, Any]:
    """Validate known display targets again inside the native worker."""
    document = import_module("veusz.document")
    from sciplot_core.rheology_tts_native_edit import restyle_native_document

    if file_sha256(path) != expected_sha256:
        raise ValueError("Native display revision is stale.")
    doc = document.Document()
    doc.load(str(path))
    targets = display_targets(doc, figure)
    native_targets, seen = [], set()
    for change in changes:
        identifier, prop = change["target"], change["property"]
        target = targets.get(identifier)
        if target is None or prop not in target["properties"]:
            raise ValueError("Native display target/property is not supported by this object.")
        if (identifier, prop) in seen:
            raise ValueError("Duplicate native display target/property.")
        seen.add((identifier, prop))
        if target["native_fields"] != change["before_native"]:
            raise ValueError("Native display target changed after inspection.")
        value = change["value"]
        if prop == "legend.location":
            if value not in CORNERS:
                raise ValueError("Native legend requires a supported named corner.")
            fields = native_legend_position_fields(CORNERS[value])
        elif prop == "annotation.text":
            if not isinstance(value, str) or not 0 < len(value) <= 500:
                raise ValueError("Annotation text requires 1–500 characters.")
            fields = {"label": _field(value)}
        else:
            if (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("Native annotation coordinates require relative values from 0 to 1.")
            fields = {"xPos" if prop == "annotation.x" else "yPos": _field([value])}
        old = {name: _field(target["native_fields"][name]) for name in fields}
        native_targets.append((target["path"], old, fields))
    return restyle_native_document(path, out, figure, figure, expected_sha256,
                                   targets_override=native_targets, preserve_native=True)
