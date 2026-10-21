"""Whole-batch layout mutations; no I/O, rendering or source interpretation."""

from typing import Any, cast

from .errors import AssemblyError


def _panel(document: dict[str, Any], identity: str) -> dict[str, Any]:
    for panel in document["panels"]:
        if panel["id"] == identity:
            return cast(dict[str, Any], panel)
    raise AssemblyError("assembly_panel_missing", "The operation requires an existing panel ID.")


def _move(document: dict[str, Any], panel: dict[str, Any], operation: dict[str, Any]) -> None:
    row, column = operation["row"], operation["column"]
    if operation.get("swap", False):
        peers = [other for other in document["panels"] if other is not panel
                 and other["row"] <= row < other["row"] + other["row_span"]
                 and other["column"] <= column < other["column"] + other["column_span"]]
        if len(peers) == 1:
            peer = peers[0]
            if (row, column) != (peer["row"], peer["column"]):
                raise AssemblyError("assembly_swap_anchor", "Swap targets must be the other panel's starting cell.")
            peer["row"], peer["column"] = panel["row"], panel["column"]
    panel["row"], panel["column"] = row, column


def apply_batch(document: dict[str, Any], operations: list[dict[str, Any]]) -> None:
    for operation in operations:
        kind = operation["op"]
        if kind == "add_panel":
            if any(panel["id"] == operation["panel"]["id"] for panel in document["panels"]):
                raise AssemblyError("assembly_duplicate_id", "An added panel needs a unique ID.")
            document["panels"].append(operation["panel"])
        elif kind in {"set_grid", "set_spacing", "set_page"}:
            document["layout"].update({key: value for key, value in operation.items() if key != "op"})
        else:
            panel = _panel(document, operation["id"])
            if kind == "remove_panel":
                document["panels"].remove(panel)
            elif kind == "move_panel":
                _move(document, panel, operation)
            elif kind == "set_span":
                panel.update(row_span=operation["row_span"], column_span=operation["column_span"])
            elif kind == "set_label":
                panel["label"] = operation["label"]
            elif kind == "set_crop":
                panel["crop"] = operation["crop"]
            elif kind == "replace_panel":
                panel["source"] = operation["source"]
