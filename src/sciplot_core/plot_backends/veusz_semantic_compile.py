"""Compile reviewed semantic properties without inferring native object meaning."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from sciplot_core.plot_document import DocumentError


def preflight_hidden_positions(binding: dict[str, Any], new_document: dict[str, Any],
                               diff: list[dict[str, Any]], updates: dict[str, Any],
                               operations: list[dict[str, Any]] | None) -> None:
    """A hidden text edit has no native candidate, but coordinates still have an owner."""
    hidden = [item["target"] for item in diff if item["property"] == "annotation.position"
              and not new_document["presentation"]["objects"][item["target"]]["properties"]["annotation.visible"]]
    if not hidden:
        return
    from sciplot_core.studio_core.annotation_axes import change_display_range
    from sciplot_core.studio_core.annotation_contracts import normalize_position

    spec = json.loads(Path(binding["spec"]).read_bytes())
    for operation in operations or []:
        if operation["op"] == "set_axis_limits":
            change_display_range(spec, operation)
    for identifier in hidden:
        normalize_position(spec, updates["targets"][identifier]["annotation"]["position"])


def semantic_change(target: dict[str, Any], native: dict[str, Any], previous: Any,
                    current: Any, changes: list[dict[str, Any]], operations: list[dict[str, Any]]) -> None:
    if native["current_value"] != previous:
        raise DocumentError("backend_binding_mismatch", "The native binding differs from the current document property.")
    kind = native["kind"]
    if kind == "axis_limits":
        operations.append({"op": "set_axis_limits", "axis": native["axis"], "unit": native["unit"],
                           "expected_min": previous[0], "expected_max": previous[1],
                           "min": current[0], "max": current[1], "allow_clipping": False})
    elif kind == "legend_visibility":
        operations.append({"op": "set_legend_visibility", "expected_visible": previous, "visible": current})
    elif kind == "legend_position":
        placement = (deepcopy(native["initial_placement"]) if current is None else
                     {"horzPosn": "manual", "vertPosn": "manual", "horzManual": current[0], "vertManual": current[1]})
        for name, value in placement.items():
            if native["placement"][name] != value:
                changes.append({"object_path": target["object_path"], "setting_path": target["object_path"] + "/" + name,
                                "expected_value": native["placement"][name], "value": value})
        native["placement"] = placement
    else:
        raise DocumentError("backend_property_unsupported", "This native property executor is not supported.")
    native["current_value"] = deepcopy(current)


def annotation_change(old: dict[str, Any], new: dict[str, Any], target: dict[str, Any]) -> list[dict[str, Any]]:
    prior = deepcopy(target["annotation"])
    prefix = "title" if "title.visible" in old else "annotation"
    replacement = {**prior, "text": new[prefix + ".text"]}
    if "annotation.position" in new:
        x, y = new["annotation.position"]
        replacement["position"] = {**prior["position"], "x": x, "y": y}
    operations = []
    if old[prefix + ".visible"] and not new[prefix + ".visible"]:
        operations.append({"op": "remove_annotation", "id": prior["id"], "expected_annotation": prior})
    elif not old[prefix + ".visible"] and new[prefix + ".visible"]:
        operations.append(replacement)
    elif new[prefix + ".visible"] and replacement != prior:
        operations.append({"op": "update_annotation", "id": prior["id"],
                           "expected_annotation": prior, "replacement": replacement})
    target["annotation"] = replacement
    return operations
