"""Project a native style-transfer plan into its existing represented fields."""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any

from sciplot_core.studio_core.axis_presentation import AXIS_PT_STYLE_FIELDS
from sciplot_core.studio_core.series_encoding_contract import apply_native_series_style

LEGEND_POSITION_FIELDS = {
    "horzPosn": "horz_position", "vertPosn": "vert_position",
    "horzManual": "horz_manual", "vertManual": "vert_manual",
}


def _points(value: Any) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d*)?|\.\d+)\s*(pt|mm|cm|in|inch)\s*", str(value))
    if match is None:
        raise ValueError("A represented transferred style needs an absolute physical size.")
    result = float(match[1]) * {"pt": 1, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72, "inch": 72}[match[2]]
    if not math.isfinite(result):
        raise ValueError("A represented transferred style must be finite.")
    return result


def project_transferred_styles(spec: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Update only declared fields; all other native state remains opaque."""
    result = deepcopy(spec)
    series_by_path = {f"/page1/graph1/{item['name']}": item for item in result.get("series", [])}
    labels_by_path = {f"/page1/graph1/{item['name']}": item for item in result.get("direct_labels", [])}
    for operation in operations:
        path, setting, value = (operation[key] for key in ("current_widget", "setting", "after"))
        axis = result.get("axes", {}).get(path.removeprefix("/page1/graph1/"))
        if path in {"/page1/graph1/x", "/page1/graph1/y"} and isinstance(axis, dict):
            field = AXIS_PT_STYLE_FIELDS.get(setting)
            if field in axis:
                axis[field] = _points(value)
        elif path in series_by_path:
            apply_native_series_style(series_by_path[path], setting, _points(value) if setting.endswith("/width") else value)
        elif path == "/page1/graph1/key1":
            legend = result.get("legend", {})
            position = LEGEND_POSITION_FIELDS.get(setting)
            if position in legend:
                legend[position] = value
            elif setting == "Text/size" and "legend_font_size_pt" in result.get("style", {}):
                result["style"]["legend_font_size_pt"] = _points(value)
        elif path in labels_by_path and setting == "Text/size":
            label = labels_by_path[path]
            if "text_size_pt" in label:
                label["text_size_pt"] = _points(value)
    return result
