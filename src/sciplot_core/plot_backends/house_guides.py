"""Lower resolved metric-flow axes and line/point legends to native widgets.

This module consumes PlotIR only. House values, inheritance, membership and
ordering are resolved upstream; no policy or template is loaded here.
"""

from typing import Any

from sciplot_core.plot_backends.figure_marks import graph_path, line_settings, scale_name
from sciplot_core.plot_backends.native_primitives import _text, native_name, number_unit


def axis_node(axis: dict[str, Any], scale: dict[str, Any], view: dict[str, Any],
              layout: dict[str, Any], panel: dict[str, Any]) -> dict[str, Any]:
    """Use the same native label/tick metric flow as the legacy axis renderer."""
    del layout  # The containing graph already owns the resolved physical frame.
    style = axis["style"]
    low, high = scale["domain"]
    if scale["direction"] == "descending":
        low, high = high, low
    decorations = axis["visible"] and axis["id"] not in panel["suppressed_axis_ids"]
    settings: dict[str, Any] = {
        "direction": "horizontal" if scale["dimension"] == "x" else "vertical",
        "min": low, "max": high, "log": scale["transform"] == "log",
        "hide": not axis["visible"], "autoMirror": False, "reflect": False,
        "otherPosition": 1.0 if axis["side"] in {"top", "right"} else 0.0,
        "outerticks": style["tick_direction"] == "out",
        "label": ("".join("\\italic{" + _text(run["text"]) + "}" if run["italic"] else _text(run["text"])
                          for run in axis["label_runs"]) if "label_runs" in axis else _text(axis["label"])),
        "mode": "labels" if axis["tick_notation"] == "labels" else "numeric",
        "Line/hide": False, "Line/color": style["color"],
        "Line/width": number_unit(style["line_width_pt"], "pt"), "Line/transparency": 0,
        "MajorTicks/manualTicks": axis["ticks"], "MajorTicks/hide": not bool(axis["ticks"]),
        "MajorTicks/color": style["tick_color"],
        "MajorTicks/width": number_unit(style["major_tick_width_pt"], "pt"),
        "MajorTicks/length": number_unit(style["tick_length_pt"], "pt"),
        "MajorTicks/transparency": 0,
        "MinorTicks/manualTicks": axis["minor_ticks"],
        "MinorTicks/number": style["minor_tick_count"],
        "MinorTicks/hide": not style["minor_ticks_visible"],
        "MinorTicks/color": style["tick_color"],
        "MinorTicks/width": number_unit(style["minor_tick_width_pt"], "pt"),
        "MinorTicks/length": number_unit(style["minor_tick_length_pt"], "pt"),
        "MinorTicks/transparency": 0,
        "Label/hide": not (decorations and axis["label_visible"]),
        "Label/offset": number_unit(style["label_padding_pt"], "pt"),
        "TickLabels/hide": not (decorations and bool(axis["ticks"])),
        "TickLabels/offset": number_unit(style["tick_label_padding_pt"], "pt"),
        "TickLabels/format": {"general": "Auto", "power10": "%Ve", "labels": "Auto"}[axis["tick_notation"]],
        "GridLines/hide": not style["grid_visible"],
        "MinorGridLines/hide": not style["minor_grid_visible"],
    }
    for prefix in ("Label", "TickLabels"):
        settings.update({
            f"{prefix}/font": style["font_family"],
            f"{prefix}/size": number_unit(style["font_size_pt"], "pt"),
            f"{prefix}/color": style["color"],
            f"{prefix}/bold": style["font_weight"] == "bold",
        })
    result: dict[str, Any] = {
        "type": "axis", "path": f"{graph_path(view['id'])}/{native_name('axis', axis['id'])}",
        "settings": settings,
    }
    if decorations and (axis["ticks"] or (axis["label_visible"] and axis["label"])):
        result.update(semantic_id=axis["id"], role="axis_label", view_id=view["id"],
                      allowed_bounds_mm=panel["cell_mm"])
    return result


def axis_label_nodes(axis: dict[str, Any], scale: dict[str, Any], view: dict[str, Any],
                     scales: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Explicit label providers use axis metrics; no synthetic scientific dataset."""
    if axis.get("tick_notation") != "labels":
        return []
    horizontal = scale["dimension"] == "x"
    other_id = view["layers"][0]["y_scale" if horizontal else "x_scale"]
    other = scales[other_id]["domain"][0]
    settings: dict[str, Any] = {
        "xAxis": native_name("axis", axis["id"]) if horizontal else scale_name(other_id),
        "yAxis": scale_name(other_id) if horizontal else native_name("axis", axis["id"]),
        "hide": False, "key": "", "marker": "none", "PlotLine/hide": True,
        "MarkerLine/hide": True, "MarkerFill/hide": True, "ErrorBarLine/hide": True,
        "FillAbove/hide": True, "FillBelow/hide": True, "Label/hide": True,
    }
    return [{"type": "xy", "path": f"{graph_path(view['id'])}/{native_name('axis-label', axis['id'] + ':' + str(index))}",
             "settings": {**settings, "labels": _text(label), "xData": [tick if horizontal else other],
                          "yData": [other if horizontal else tick]}}
            for index, (tick, label) in enumerate(zip(axis["ticks"], axis["tick_labels"], strict=True))]


def legend_nodes(guide: dict[str, Any], ir: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return a closed native key plan, or None for an unsupported guide shape.

    Each entry gets one data-free XY symbol provider combining its resolved
    line and point channels. The native key's explicit order includes only
    these providers, so drawing-layer order and extra plotters cannot add,
    duplicate or reorder labels. Complex marks retain the caller's explicit
    generic-guide path rather than silently losing their symbols.
    """
    view_id = guide.get("view_id")
    if view_id is None or guide["scope"] != "view":
        return None
    if not guide["visible"]:
        return []
    layers = {layer["id"]: layer for view in ir["views"] if view["id"] == view_id
              for layer in view["layers"]}
    entries = guide["entries"]
    for entry in entries:
        kinds = [mark["type"] for mark in entry["marks"]]
        if (not kinds or any(kind not in {"line", "point"} for kind in kinds)
                or len(kinds) != len(set(kinds)) or entry["layer_id"] not in layers):
            return None
    panel = next(panel for panel in ir["layout"]["panels"] if panel["view_id"] == view_id)
    parent, style = graph_path(view_id), guide["style"]
    providers = [_symbol_provider(guide, entry, layers[entry["layer_id"]], index, parent)
                 for index, entry in enumerate(entries)]
    settings: dict[str, Any] = {
        "hide": False, "title": "", "order": ",".join(node["path"].rsplit("/", 1)[1] for node in providers),
        "orderswap": False, "exclude": "", "symbolswap": False,
        "Text/font": style["font_family"], "Text/size": number_unit(style["font_size_pt"], "pt"),
        "Text/color": style["color"], "Text/bold": style["font_weight"] == "bold", "Text/hide": False,
        "keyLength": number_unit(style["key_length_mm"], "mm"), "marginSize": style["margin_size"],
        "columns": guide["columns"], "Background/hide": not style["frame_visible"],
        "Border/hide": not style["frame_visible"],
        "horzPosn": "left" if guide["location"].endswith("left") else "right",
        "vertPosn": "top" if guide["location"].startswith("top") else "bottom",
    }
    if "position_fraction" in guide:
        horizontal, vertical = guide["position_fraction"]
        settings.update(horzPosn="manual", vertPosn="manual",
                        horzManual=horizontal, vertManual=vertical)
    key = {"type": "key", "path": f"{parent}/{native_name('legend', guide['id'])}",
           "settings": settings, "semantic_id": guide["id"], "role": "legend", "view_id": view_id,
           "allowed_bounds_mm": panel["plot_mm"]}
    # Graph children paint backwards. Providers contain no data, and the key
    # precedes actual marks when the caller assembles the drawing plan.
    return [key, *providers]


def _symbol_provider(guide: dict[str, Any], entry: dict[str, Any], layer: dict[str, Any],
                     index: int, parent: str) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "hide": False, "xData": [], "yData": [], "key": _text(entry["label"]),
        "xAxis": scale_name(layer["x_scale"]), "yAxis": scale_name(layer["y_scale"]),
        "PlotLine/hide": True, "marker": "none", "MarkerLine/hide": True, "MarkerFill/hide": True,
        "ErrorBarLine/hide": True, "FillAbove/hide": True, "FillBelow/hide": True,
    }
    for mark in entry["marks"]:
        style = mark["style"]
        if mark["type"] == "line":
            settings.update(line_settings(style, "PlotLine"))
        elif mark["type"] == "point":
            settings.update({
                "marker": style["marker"], "markerSize": number_unit(style["marker_size_pt"], "pt"),
                "MarkerLine/hide": False, "MarkerFill/hide": False,
                "MarkerLine/color": style["marker_color"], "MarkerFill/color": style["marker_color"],
                "MarkerLine/width": number_unit(style["marker_line_width_pt"], "pt"),
                "MarkerLine/transparency": round((1 - style["marker_opacity"]) * 100),
                "MarkerFill/transparency": round((1 - style["marker_opacity"]) * 100),
                "thinfactor": style["marker_thin_factor"],
            })
    return {"type": "xy", "path": f"{parent}/{native_name('legend-symbol', guide['id'] + ':' + str(index))}",
            "settings": settings}
