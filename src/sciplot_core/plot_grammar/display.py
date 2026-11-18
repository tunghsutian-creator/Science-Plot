"""Resolve presentation lines from the immutable measured datasets, never vice versa."""
import math
from typing import Any

from sciplot_core.plot_document.errors import fail

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_transforms.display import interpolate_display


def resolve_display_curves(views: list[dict[str, Any]], datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for view in views:
        if "display_stack" in view:
            result.update(_stacked_curves(view, datasets))
            continue
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


def validate_stack_view(view: dict[str, Any], scales: dict[str, Any]) -> None:
    layers = view["layers"]
    axes = {(layer["x_scale"], layer["y_scale"]) for layer in layers}
    if len(layers) < 2 or len(axes) != 1 or not all(
        len(layer["marks"]) == 1 and layer["marks"][0]["type"] == "line"
        and "interpolation" not in layer["marks"][0] and {"x", "y"} == set(layer["mappings"])
        and scales.get(layer["y_scale"], {}).get("transform") == "linear" for layer in layers
    ):
        fail("figure_display_stack_scope", "A spectral stack requires multiple linear-Y line-only curves sharing the same axes.",
             "/views/display_stack", "stack_scope")


def _stacked_curves(view: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    from sciplot_core.studio_render.series_transforms import stack_display_responses

    records = []
    for layer in view["layers"]:
        columns = datasets[layer["dataset_id"]]["columns"]
        x_column, y_column = (layer["mappings"][channel] for channel in ("x", "y"))
        records.append((layer, x_column, y_column, columns[x_column]["values"], columns[y_column]["values"]))
    responses = stack_display_responses([
        tuple(float("nan") if xv is None or yv is None else yv for xv, yv in zip(x, y, strict=True))
        for _, _, _, x, y in records])
    group_hash = canonical_json_sha256({"policy": view["display_stack"], "members": [
        {"layer_id": layer["id"], "dataset_id": layer["dataset_id"], "x": x, "y": y}
        for layer, _, _, x, y in records]}, allow_nan=False)
    result = {}
    for (layer, x_column, y_column, x, y), response in zip(records, responses, strict=True):
        if any(xv is not None and yv is not None and not math.isfinite(shift)
               for xv, yv, shift in zip(x, y, response, strict=True)):
            fail("figure_display_stack_nonfinite", "The presentation stack could not retain finite response geometry.",
                 "/views/display_stack", "finite_display_coordinates")
        mark, = layer["marks"]
        result[mark["id"]] = {"source_dataset_id": layer["dataset_id"], "x_column": x_column, "y_column": y_column,
            "input_numeric_hash": canonical_json_sha256({"x": x, "y": y}, allow_nan=False), "stack_input_hash": group_hash,
            "curve": {"x": x, "y": [None if xv is None or yv is None else shift
                                      for xv, yv, shift in zip(x, y, response, strict=True)]}}
    return result


def stack_labels(views: list[dict[str, Any]], scales: dict[str, Any], layout: dict[str, Any],
                 display: dict[str, Any], *, font_size_pt: float) -> list[dict[str, Any]]:
    """Derive complete source labels from the same shifted curves in the physical frame."""
    from sciplot_core.studio_render.direct_label_layout import automatic_label_boxes_for_frame
    from sciplot_core.studio_render.models import StudioPreparationBlocked, StudioSeries, _VeuszStyleContract

    result = []
    for view in views:
        if "display_stack" not in view:
            continue
        layers = [layer for layer in view["layers"] if layer.get("visible", True)]
        if not layers:
            continue
        panel = next(item for item in layout["panels"] if item["view_id"] == view["id"])
        _, _, width, height = panel["plot_mm"]
        axes = {dimension: scales[layers[0][dimension + "_scale"]] for dimension in ("x", "y")}
        domains = {dim: axis["domain"][::-1] if axis["direction"] == "descending" else axis["domain"]
                   for dim, axis in axes.items()}
        series = []
        for layer in layers:
            mark, = layer["marks"]
            curve = display[mark["id"]]["curve"]
            xs, ys = (tuple(float("nan") if value is None else value for value in curve[dim]) for dim in ("x", "y"))
            series.append(StudioSeries(layer["label"], "x", "y", xs, ys,
                mark["style"]["line_color"], line_width=mark["style"]["line_width_pt"],
                line_style=mark["style"]["line_style"]))
        try:
            anchors = automatic_label_boxes_for_frame(series, bounds=(*domains["x"], *domains["y"]),
                width=width, height=height, style=_VeuszStyleContract(font_size_pt=font_size_pt), side="left",
                xlog=axes["x"]["transform"] == "log")
        except StudioPreparationBlocked as exc:
            fail("figure_display_stack_label_layout", str(exc), "/views/display_stack", "inline_label_clearance")
        for item, layer, (x, y) in zip(series, layers, anchors, strict=True):
            result.append({"id": layer["id"] + ":stack-label", "text": item.label, "visible": True,
                "space": "data", "view_id": view["id"], "x_scale": layer["x_scale"], "y_scale": layer["y_scale"],
                "x": x, "y": y, "style": {"font_size_pt": font_size_pt, "color": item.color,
                                        "align_h": "left", "align_v": "top"}})
    return result
