"""Compact transport projections preserve scientific uncertainty and revisions."""

from __future__ import annotations

from typing import Any


def _compact_object(item: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in item.items() if key != "settings"}
    settings = item.get("settings")
    if isinstance(settings, dict):
        context = {key: settings[key] for key in (
            "key", "label", "text", "xData", "yData", "xAxis", "yAxis", "hide", "log",
        ) if key in settings}
        if context:
            result["display_context"] = context
    return result


def compact_result(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    selected = payload.get("selected_figure")
    if isinstance(selected, dict):
        # Full native setting trees may contain large arrays. Editable fields
        # retain their current values and exact paths, so no extra query is needed.
        result["selected_figure"] = {
            **selected,
            "objects": {
                path: _compact_object(item)
                for path, item in selected.get("objects", {}).items()
            },
        }
    # Signed edit state stays in the saved review. Clients apply by review_path;
    # they do not echo or reconstruct these potentially large byte inventories.
    if payload.get("kind") == "sciplot_document_edit_preview":
        result.pop("base_state", None)
    return result
