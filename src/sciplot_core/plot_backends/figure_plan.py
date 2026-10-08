"""Veusz capability contract and generic Figure/View/Scale drawing plan."""

from typing import Any

from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_backends.native_primitives import native_name, number_unit
from sciplot_core.plot_backends.house_guides import axis_node, axis_label_nodes, legend_nodes
from sciplot_core.plot_backends.figure_marks import graph_path, scale_name, mark_nodes, text_settings, line_settings


def grammar_capabilities() -> dict[str, Any]:
    return {"marks": ["line", "point", "bar", "errorbar", "band", "rule", "text"],
            "scale_transforms": ["linear", "log"], "multi_view": True, "multiple_scales": True}


def capability_profile() -> dict[str, Any]:
    return grammar_capabilities()


def validate_figure_capabilities(ir: dict[str, Any]) -> None:
    profile = grammar_capabilities()
    for scale in ir["scales"]:
        if scale["transform"] not in profile["scale_transforms"]:
            raise DocumentError("unsupported_capability", f"Veusz does not support {scale['transform']} managed scales.")
    for view in ir["views"]:
        for layer in view["layers"]:
            for mark in layer["marks"]:
                for field in ("fill_opacity", "line_opacity", "marker_opacity"):
                    opacity = mark["style"].get(field, 1.0) * 100
                    if abs(opacity - round(opacity)) > 1e-9:
                        raise DocumentError("unsupported_capability", "Managed Veusz opacity requires whole-percent precision.")
                if mark["type"] not in profile["marks"] or mark["style"].get("line_join") == "miter":
                    raise DocumentError("unsupported_capability", "Managed Veusz mark capability is not supported.")
    def colors(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith("color") and isinstance(child, str) and len(child) not in {7, 13}:
                    raise DocumentError("unsupported_capability", "Managed Veusz colors require opaque RGB; fill opacity is explicit.")
                colors(child)
        elif isinstance(value, list):
            for child in value:
                colors(child)
    colors(ir)


def page_label(identity: str, text: str, position: list[float], style: dict[str, Any],
               layout: dict[str, Any], *, role: str, view_id: str | None = None,
               angle: float = 0, allowed: list[float] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "label", "path": f"/page1/{native_name('text', identity)}",
        "settings": {"positioning": "relative", "xPos": [position[0] / layout["width_mm"]],
                     "yPos": [1 - position[1] / layout["height_mm"]], "hide": False, "angle": angle,
                     **text_settings(text, style)}, "semantic_id": identity, "role": role}
    if view_id is not None:
        result["view_id"] = view_id
    if allowed is not None:
        result["allowed_bounds_mm"] = allowed
    return result


def _axis_nodes(axis: dict[str, Any], scale: dict[str, Any], view: dict[str, Any],
                layout: dict[str, Any], panel: dict[str, Any]) -> list[dict[str, Any]]:
    if axis.get("text_layout") == "axis-metric-flow":
        return [axis_node(axis, scale, view, layout, panel)]
    style, side = axis["style"], axis["side"]
    low, high = scale["domain"]
    if scale["direction"] == "descending":
        low, high = high, low
    settings = {"direction": "horizontal" if scale["dimension"] == "x" else "vertical",
                "min": low, "max": high, "log": scale["transform"] == "log",
                "hide": not axis["visible"], "autoMirror": False, "reflect": False,
                "otherPosition": 1.0 if side in {"top", "right"} else 0.0,
                "outerticks": style["tick_direction"] == "out", "Line/hide": False,
                "Line/color": style["color"], "Line/width": number_unit(style["line_width_pt"], "pt"),
                "MajorTicks/manualTicks": axis["ticks"], "MajorTicks/hide": not bool(axis["ticks"]),
                "MajorTicks/color": style["color"], "MajorTicks/length": number_unit(style["tick_length_pt"], "pt"),
                "MajorTicks/width": number_unit(style["line_width_pt"], "pt"), "MinorTicks/hide": True,
                "Label/hide": True, "TickLabels/hide": True, "GridLines/hide": True}
    result = [{"type": "axis", "path": f"{graph_path(view['id'])}/{native_name('axis', axis['id'])}",
               "settings": settings}]
    if not axis["visible"] or axis["id"] in panel.get("suppressed_axis_ids", []):
        return result
    text_style = {"font_family": style["font_family"], "font_size_pt": style["font_size_pt"],
                  "color": style["color"], "align_h": axis.get("tick_alignment", "center"), "align_v": "center"}
    for index, (text, position) in enumerate(zip(axis["tick_labels"], axis["tick_positions_mm"], strict=True)):
        result.append(page_label(f"{axis['id']}:tick:{index}", text, position, text_style, layout,
                                 role="tick_label", view_id=view["id"], allowed=panel["cell_mm"]))
    if axis["label_visible"] and axis["label"]:
        result.append(page_label(axis["id"], axis["label"], axis["label_position_mm"],
                                 {**text_style, "align_h": "center"}, layout, role="axis_label",
                                 view_id=view["id"], angle=axis["label_angle"], allowed=panel["cell_mm"]))
    return result


def drawing_plan(ir: dict[str, Any]) -> list[dict[str, Any]]:
    layout, figure = ir["layout"], ir["figure"]
    width, height = layout["width_mm"], layout["height_mm"]
    nodes: list[dict[str, Any]] = [
        {"type": "document", "path": "/", "settings": {"width": number_unit(width, "mm"), "height": number_unit(height, "mm")}},
        {"type": "page", "path": "/page1", "settings": {"width": number_unit(width, "mm"), "height": number_unit(height, "mm"),
         "Background/color": figure["background_color"], "Background/hide": False}}]
    scales = {scale["id"]: scale for scale in ir["scales"]}
    page_foreground: list[dict[str, Any]] = []
    for annotation in ir["annotations"]:
        if annotation["visible"] and annotation["text"]:
            position = annotation["position_mm"]
            allowed = None
            if annotation["space"] != "figure":
                allowed = next(p["plot_mm"] for p in layout["panels"] if p["view_id"] == annotation["view_id"])
            page_foreground.append(page_label(annotation["id"], annotation["text"], position, annotation["style"], layout,
                role="panel_label" if annotation.get("role") == "panel_label" else "annotation",
                view_id=annotation.get("view_id"), allowed=allowed))
    for guide in ir["guides"]:
        if guide["visible"] and guide.get("text_layout") != "legend-metric-flow":
            page_foreground.extend(_guide_nodes(guide, ir))
    graph_nodes: list[dict[str, Any]] = []
    for view in ir["views"]:
        panel = next(p for p in layout["panels"] if p["view_id"] == view["id"])
        x, y, w, h = panel["plot_mm"]
        if view.get("panel_label"):
            page_foreground.append(page_label(view["id"] + ":panel-label", view["panel_label"],
                panel["panel_label_mm"], view["panel_label_style"], layout, role="panel_label",
                view_id=view["id"], allowed=panel["cell_mm"]))
        graph_nodes.append({"type": "graph", "path": graph_path(view["id"]), "settings": {
            "Border/hide": True, "Background/hide": "rendering_contract" not in ir,
            **({"Background/color": figure["background_color"]} if "rendering_contract" in ir else {}),
            "leftMargin": number_unit(x, "mm"), "topMargin": number_unit(y, "mm"),
            "rightMargin": number_unit(width - x - w, "mm"), "bottomMargin": number_unit(height - y - h, "mm")}})
        used = sorted({layer[dimension + "_scale"] for layer in view["layers"] for dimension in ("x", "y")})
        for identity in used:
            scale = scales[identity]
            low, high = scale["domain"]
            if scale["direction"] == "descending":
                low, high = high, low
            graph_nodes.append({"type": "axis", "path": f"{graph_path(view['id'])}/{scale_name(identity)}", "settings": {
                "direction": "horizontal" if scale["dimension"] == "x" else "vertical", "min": low, "max": high,
                "log": scale["transform"] == "log", "hide": True, "autoMirror": False}})
        for axis in view["axes"]:
            for node in _axis_nodes(axis, scales[axis["scale_id"]], view, layout, panel):
                (graph_nodes if node["type"] == "axis" else page_foreground).append(node)
            graph_nodes.extend(axis_label_nodes(axis, scales[axis["scale_id"]], view, scales))
        for guide in ir["guides"]:
            if guide.get("view_id") == view["id"] and guide.get("text_layout") == "legend-metric-flow":
                guide_nodes = legend_nodes(guide, ir)
                if guide_nodes is None:
                    raise DocumentError("unsupported_capability", "Resolved legend flow has unsupported symbol channels.")
                graph_nodes.extend(guide_nodes)
        # Veusz draws children in reverse order, so highest canonical z comes first.
        for layer in sorted(view["layers"], key=lambda item: (item["z_order"], item["id"]), reverse=True):
            for mark in reversed(layer["marks"]):
                graph_nodes.extend(mark_nodes(ir, view, layer, mark))
    # Top-level labels precede graphs because native page children also draw reversed.
    nodes.extend(page_foreground)
    nodes.extend(graph_nodes)
    nodes.append({"type": "rect", "path": "/page1/background", "settings": {
        "positioning": "relative", "xPos": [0.5], "yPos": [0.5], "width": [1.0], "height": [1.0],
        "clip": True, "Fill/color": figure["background_color"], "Fill/hide": False,
        "Fill/transparency": 0, "Border/hide": True}})
    return nodes


def _guide_nodes(guide: dict[str, Any], ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Draw resolved entry labels/symbol boxes, without native legend inference."""
    layout = ir["layout"]
    layers = {layer["id"]: layer for view in ir["views"] for layer in view["layers"]}
    nodes: list[dict[str, Any]] = []
    for index, entry in enumerate(guide["entries"]):
        style = {**guide["style"], "align_h": "left", "align_v": "center"}
        identity = f"{guide['id']}:entry:{index}"
        nodes.append(page_label(identity, entry["label"], entry["label_mm"], style, layout, role="legend",
                                 view_id=guide.get("view_id"), allowed=guide["rect_mm"]))
        x, y, w, h = entry["symbol_mm"]
        for mark in reversed(layers[entry["layer_id"]]["marks"]):
            kind, values = mark["type"], mark["style"]
            settings: dict[str, Any] = {"positioning": "relative", "xPos": [x / layout["width_mm"]],
                "yPos": [1 - (y + h / 2) / layout["height_mm"]], "hide": False}
            native_type = "line"
            if kind == "point":
                nodes.extend(_legend_point(identity + mark["id"], values, entry["symbol_mm"], layout))
                continue
            if kind in {"bar", "band"}:
                native_type = "rect"
                settings.update({"xPos": [(x + w / 2) / layout["width_mm"]],
                    "width": [w / layout["width_mm"]], "height": [h / layout["height_mm"]],
                    "Fill/color": values["fill_color"], "Fill/hide": False,
                    "Fill/transparency": round((1 - values["fill_opacity"]) * 100),
                    "Border/hide": values["border_width_pt"] == 0, "Border/color": values["border_color"],
                    "Border/width": number_unit(values["border_width_pt"], "pt")})
            elif kind in {"line", "rule", "errorbar"}:
                settings.update({"mode": "point-to-point", "xPos2": [(x + w) / layout["width_mm"]],
                    "yPos2": settings["yPos"], **line_settings(values)})
            else:
                continue
            nodes.append({"type": native_type, "path": f"/page1/{native_name('legend', identity + mark['id'])}",
                          "settings": settings})
    return nodes


def _legend_point(identity: str, style: dict[str, Any], rectangle: list[float], layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Use the same native marker glyph/physical size as the layer, not an ellipse proxy."""
    x, y, width, height = rectangle
    path = "/page1/" + native_name("legend-point", identity)
    nodes = [{"type": "graph", "path": path, "settings": {"Border/hide": True, "Background/hide": True,
        "leftMargin": number_unit(x, "mm"), "topMargin": number_unit(y, "mm"),
        "rightMargin": number_unit(layout["width_mm"] - x - width, "mm"),
        "bottomMargin": number_unit(layout["height_mm"] - y - height, "mm")}}]
    for axis in ("x", "y"):
        nodes.append({"type": "axis", "path": path + "/" + axis, "settings": {"hide": True,
            "direction": "horizontal" if axis == "x" else "vertical", "min": 0.0, "max": 1.0, "autoMirror": False}})
    nodes.append({"type": "xy", "path": path + "/symbol", "settings": {"xData": [0.5], "yData": [0.5],
        "xAxis": "x", "yAxis": "y", "key": "", "PlotLine/hide": True, "ErrorBarLine/hide": True,
        "FillAbove/hide": True, "FillBelow/hide": True, "marker": style["marker"],
        "markerSize": number_unit(style["marker_size_pt"], "pt"), "MarkerLine/hide": False,
        "MarkerFill/hide": False, "MarkerLine/color": style["marker_color"], "MarkerFill/color": style["marker_color"],
        "MarkerLine/width": number_unit(style["marker_line_width_pt"], "pt"),
        **({"MarkerFill/transparency": round((1-style["marker_opacity"])*100),
            "MarkerLine/transparency": round((1-style["marker_opacity"])*100)} if "marker_opacity" in style else {})}})
    return nodes
