"""Generic resolved mark lowering; scientific names never select native behavior."""

from math import log10
from typing import Any

from sciplot_core.plot_backends.native_primitives import dataset_name, native_name, number_unit, _text


def graph_path(view_id: str) -> str:
    return f"/page1/{native_name('view', view_id)}"


def scale_name(scale_id: str) -> str:
    return native_name("scale", scale_id)


def mark_path(view_id: str, layer_id: str, mark_id: str) -> str:
    return f"{graph_path(view_id)}/{native_name('mark', layer_id + '/' + mark_id)}"


def fraction(value: float, scale: dict[str, Any]) -> float:
    low, high = scale["domain"]
    if scale["transform"] == "log":
        value, low, high = log10(value), log10(low), log10(high)
    result = (value - low) / (high - low)
    return float(1 - result if scale["direction"] == "descending" else result)


def coordinates(ir: dict[str, Any], layer: dict[str, Any]) -> dict[str, list[Any]]:
    columns = ir["datasets"][layer["dataset_id"]]["columns"]
    return {channel: list(columns[column]["values"]) for channel, column in layer["mappings"].items()}


def mark_geometry(ir: dict[str, Any], view: dict[str, Any], layer: dict[str, Any], mark: dict[str, Any]) -> list[dict[str, Any]]:
    """Explicit mark geometry retains original source ordering and missing breaks."""
    data = coordinates(ir, layer)
    kind = mark["type"]
    if kind in {"line", "point"}:
        return [{"xData": dataset_name(layer["dataset_id"], layer["mappings"]["x"]),
                 "yData": dataset_name(layer["dataset_id"], layer["mappings"]["y"])}]
    rows = list(zip(data["x"], data["y"], strict=True))
    scales = {scale["id"]: scale for scale in ir["scales"]}
    x_scale, y_scale = scales[layer["x_scale"]], scales[layer["y_scale"]]
    if kind == "band":
        runs: list[list[tuple[float, float, float]]] = [[]]
        for x, low, high in zip(data["x"], data["y_low"], data["y_high"], strict=True):
            if None in (x, low, high):
                if runs[-1]:
                    runs.append([])
            else:
                runs[-1].append((x, low, high))
        return [{"xPos": [r[0] for r in run] + [r[0] for r in reversed(run)],
                 "yPos": [r[1] for r in run] + [r[2] for r in reversed(run)]}
                for run in runs if len(run) >= 2]
    result: list[dict[str, Any]] = []
    for index, (x, y) in enumerate(rows):
        if x is None or y is None:
            continue
        if kind == "bar":
            half, baseline = mark["width_data"] / 2, mark["baseline"]
            if mark["style"].get("baseline_border_visible") is False and mark["style"]["border_width_pt"] > 0:
                # Separate three-sided outlines preserve the absence of a baseline
                # stroke. Put them before the fill for native reverse paint order.
                for x1, y1, x2, y2 in ((x - half, baseline, x - half, y),
                                     (x + half, baseline, x + half, y), (x - half, y, x + half, y)):
                    result.append({"xPos": [x1], "yPos": [y1], "xPos2": [x2], "yPos2": [y2]})
            result.append({"xPos": [x - half, x + half, x + half, x - half],
                           "yPos": [baseline, baseline, y, y]})
        elif kind == "errorbar":
            low, high = data["y_low"][index], data["y_high"][index]
            if low is None or high is None:
                continue
            result.append({"xPos": [x], "yPos": [low], "xPos2": [x], "yPos2": [high]})
            panel = next(p for p in ir["layout"]["panels"] if p["view_id"] == view["id"])
            half_cap = mark["style"]["cap_width_pt"] * 25.4 / 72 / panel["plot_mm"][2] / 2
            fx = fraction(x, x_scale)
            for end in (low, high):
                fy = fraction(end, y_scale)
                result.append({"positioning": "relative", "xPos": [fx - half_cap], "yPos": [fy],
                               "xPos2": [fx + half_cap], "yPos2": [fy]})
        elif kind == "rule":
            if mark["orientation"] == "vertical":
                result.append({"xPos": [x], "yPos": [y_scale["domain"][0]],
                               "xPos2": [x], "yPos2": [y_scale["domain"][1]]})
            else:
                result.append({"xPos": [x_scale["domain"][0]], "yPos": [y],
                               "xPos2": [x_scale["domain"][1]], "yPos2": [y]})
        elif kind == "text":
            result.append({"xPos": [x], "yPos": [y]})
    return result


def line_settings(style: dict[str, Any], prefix: str = "Line") -> dict[str, Any]:
    result = {f"{prefix}/color": style["line_color"],
              f"{prefix}/width": number_unit(style["line_width_pt"], "pt"), f"{prefix}/hide": False}
    if "line_style" in style:
        result[f"{prefix}/style"] = {"solid": "solid", "dash": "dashed", "dot": "dotted"}[style["line_style"]]
    if "line_opacity" in style:
        result[f"{prefix}/transparency"] = round((1 - style["line_opacity"]) * 100)
    # Joins apply to XY polylines. A free Line/legend segment has no vertices
    # to join and its native settings do not expose joinStyle.
    if prefix == "PlotLine" and "line_join" in style:
        result[f"{prefix}/joinStyle"] = style["line_join"]
    return result


def text_settings(text: str, style: dict[str, Any]) -> dict[str, Any]:
    return {"label": _text(text), "Text/font": style["font_family"],
            "Text/size": number_unit(style["font_size_pt"], "pt"), "Text/color": style["color"],
            "Text/hide": False, **({"Text/bold": style["font_weight"] == "bold"} if "font_weight" in style else {}), "alignHorz": style["align_h"].replace("center", "centre"),
            "alignVert": style["align_v"].replace("center", "centre"), "margin": "0pt",
            "Border/hide": True, "Background/hide": True, "clip": False}


def mark_nodes(ir: dict[str, Any], view: dict[str, Any], layer: dict[str, Any], mark: dict[str, Any]) -> list[dict[str, Any]]:
    kind, style = mark["type"], mark["style"]
    base: dict[str, Any] = {"hide": False, "xAxis": scale_name(layer["x_scale"]),
                            "yAxis": scale_name(layer["y_scale"])}
    native_type = {"line": "xy", "point": "xy", "bar": "polygon", "band": "polygon",
                   "rule": "line", "errorbar": "line", "text": "label"}[kind]
    if kind in {"line", "point"}:
        base.update({"key": "", "PlotLine/hide": kind != "line", "marker": "none",
                     "MarkerLine/hide": True, "MarkerFill/hide": True, "ErrorBarLine/hide": True,
                     "FillAbove/hide": True, "FillBelow/hide": True})
        if kind == "line":
            base.update(line_settings(style, "PlotLine"))
        else:
            base.update({"marker": style["marker"], "markerSize": number_unit(style["marker_size_pt"], "pt"),
                         "MarkerLine/hide": False, "MarkerFill/hide": False,
                         "MarkerLine/color": style["marker_color"], "MarkerFill/color": style["marker_color"],
                         "MarkerLine/width": number_unit(style["marker_line_width_pt"], "pt")})
            if "marker_opacity" in style:
                base.update({"MarkerFill/transparency": round((1 - style["marker_opacity"]) * 100),
                    "MarkerLine/transparency": round((1 - style["marker_opacity"]) * 100),
                    "thinfactor": style["marker_thin_factor"]})
    else:
        base["positioning"] = "axes"
        if kind in {"bar", "band"}:
            base.update({"Fill/color": style["fill_color"], "Fill/transparency": round((1 - style["fill_opacity"]) * 100),
                         "Fill/hide": False, "Line/color": style["border_color"],
                         "Line/width": number_unit(style["border_width_pt"], "pt"),
                         "Line/hide": style["border_width_pt"] == 0})
        elif kind in {"rule", "errorbar"}:
            base.update({"mode": "point-to-point", "clip": True, "arrowleft": "none", "arrowright": "none",
                         **line_settings(style)})
        else:
            base.update(text_settings(mark["text"], style))
    path = mark_path(view["id"], layer["id"], mark["id"])
    nodes = []
    for index, geometry in enumerate(mark_geometry(ir, view, layer, mark)):
        settings, node_type = {**base, **geometry}, native_type
        if kind == "bar" and style.get("baseline_border_visible") is False:
            if "xPos2" in geometry:
                node_type = "line"
                settings = {"hide": False, "positioning": "axes", "xAxis": base["xAxis"], "yAxis": base["yAxis"],
                    "mode": "point-to-point", "clip": True, "arrowleft": "none", "arrowright": "none", "Fill/hide": True,
                    **line_settings({"line_color": style["border_color"], "line_width_pt": style["border_width_pt"]}), **geometry}
            else:
                settings["Line/hide"] = True
        nodes.append({"type": node_type, "path": path if index == 0 else f"{path}_{index}",
                      "settings": settings, "semantic_id": mark["id"], "view_id": view["id"],
                      "role": "annotation" if kind == "text" else "mark"})
    return nodes
