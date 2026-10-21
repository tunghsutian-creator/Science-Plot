"""Resolve presentation lines from the immutable measured datasets, never vice versa."""
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_transforms.display import interpolate_display


def resolve_display_curves(views: list[dict[str, Any]], datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for view in views:
        for layer in view["layers"]:
            columns = datasets[layer["dataset_id"]]["columns"]
            x_column, y_column = (layer["mappings"][channel] for channel in ("x", "y"))
            x, y = columns[x_column]["values"], columns[y_column]["values"]
            for mark in layer["marks"]:
                if mark["type"] == "line" and "interpolation" in mark:
                    result[mark["id"]] = {"source_dataset_id": layer["dataset_id"],
                        "x_column": x_column, "y_column": y_column,
                        "input_numeric_hash": canonical_json_sha256({"x": x, "y": y}, allow_nan=False),
                        "curve": interpolate_display(x, y, **mark["interpolation"])}
    return result
