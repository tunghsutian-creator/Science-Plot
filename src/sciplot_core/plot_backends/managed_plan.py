"""Veusz-only lowering of a fully resolved, backend-neutral PlotIR."""

from typing import Any

from .native_primitives import (native_name as native_name, dataset_name as dataset_name, number_unit as number_unit,
                                _text as _text, native_datasets as native_datasets)


def validate_capabilities(ir: dict[str, Any]) -> None:
    if ir.get("schema_version") == 2:
        from sciplot_core.plot_backends.figure_plan import validate_figure_capabilities
        validate_figure_capabilities(ir)
        return

    from sciplot_core.plot_document import DocumentError

    if any(series["style"]["line_join"] == "miter" for series in ir["series"]):
        raise DocumentError("unsupported_capability", "The Veusz managed compiler supports bevel and round line joins.",
                            issues=[{"path": "/series/style/line_join", "constraint": "supported_backend_capability"}])
    colors = [ir["background_color"], *[axis["line_color"] for axis in ir["axes"].values()],
              *[item["color"] for item in ir["annotations"]],
              *[series["style"][field] for series in ir["series"] for field in ("line_color", "marker_color")]]
    if any(len(color) != 7 for color in colors):
        raise DocumentError("unsupported_capability", "Managed Veusz colors currently require opaque RGB values.",
                            issues=[{"path": "/colors", "constraint": "opaque_rgb"}])


def drawing_plan(ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Return private native nodes. No template/theme/default interpretation occurs."""
    if ir.get("schema_version") == 2:
        from sciplot_core.plot_backends.figure_plan import drawing_plan as figure_plan
        return figure_plan(ir)

    size, margins = ir["dimensions"], ir["layout"]["margins_mm"]
    nodes: list[dict[str, Any]] = []

    def node(kind: str, path: str, settings: dict[str, Any]) -> None:
        nodes.append({"type": kind, "path": path, "settings": settings})

    node("document", "/", {"width": number_unit(size["width_mm"], "mm"),
                           "height": number_unit(size["height_mm"], "mm")})
    node("page", "/page1", {"width": number_unit(size["width_mm"], "mm"),
                             "height": number_unit(size["height_mm"], "mm"),
                             "Background/color": ir["background_color"], "Background/hide": False})
    graph = "/page1/graph1"
    node("graph", graph, {"Border/hide": True, **{
        f"{edge}Margin": number_unit(value, "mm") for edge, value in margins.items()}})
    for name, axis in ir["axes"].items():
        node("axis", f"{graph}/{name}", {
            "label": _text(axis["label"]), "direction": "horizontal" if name == "x" else "vertical",
            "hide": not axis["visible"], "min": axis["limits"][0], "max": axis["limits"][1],
            "log": axis["scale"] == "log", "autoMirror": False,
            "outerticks": axis["tick_direction"] == "out", "Line/hide": False,
            "Line/color": axis["line_color"], "Line/width": number_unit(axis["line_width_pt"], "pt"),
            "MajorTicks/manualTicks": axis["ticks"], "MajorTicks/hide": not bool(axis["ticks"]),
            "MajorTicks/color": axis["line_color"], "MajorTicks/length": number_unit(axis["tick_length_pt"], "pt"),
            "MajorTicks/width": number_unit(axis["line_width_pt"], "pt"), "MinorTicks/hide": True,
            "Label/font": axis["font_family"], "Label/size": number_unit(axis["font_size_pt"], "pt"),
            "Label/color": axis["line_color"], "Label/hide": not axis["label_visible"],
            "TickLabels/font": axis["font_family"], "TickLabels/size": number_unit(axis["font_size_pt"], "pt"),
            "TickLabels/color": axis["line_color"], "TickLabels/format": "Auto",
        })
    legend = ir["legend"]
    node("key", f"{graph}/legend", {
        "hide": not legend["visible"], "title": "", "horzPosn": "manual", "vertPosn": "manual",
        "horzManual": legend["position"][0], "vertManual": legend["position"][1],
        "Text/font": legend["font_family"], "Text/size": number_unit(legend["font_size_pt"], "pt"),
        "Border/hide": True, "Background/hide": True, "columns": 1,
    })
    for annotation in ir["annotations"]:
        node("label", f"{graph}/{native_name('annotation', annotation['id'])}", {
            "label": _text(annotation["text"]), "hide": not annotation["visible"],
            "positioning": annotation["coordinate_mode"], "xPos": [annotation["position"][0]],
            "yPos": [annotation["position"][1]], "Text/font": annotation["font_family"],
            "Text/size": number_unit(annotation["font_size_pt"], "pt"), "Text/color": annotation["color"],
        })
    for series in ir["series"]:
        style = series["style"]
        marker_visible = style["marker_visible"] and style["marker"] != "none"
        node("xy", f"{graph}/{native_name('series', series['id'])}", {
            "xData": dataset_name(series["dataset_id"], series["x_column"]),
            "yData": dataset_name(series["dataset_id"], series["y_column"]),
            "key": _text(series["label"]), "xAxis": "x", "yAxis": "y", "hide": False,
            "PlotLine/color": style["line_color"], "PlotLine/width": number_unit(style["line_width_pt"], "pt"),
            "PlotLine/style": {"solid": "solid", "dash": "dashed", "dot": "dotted"}[style["line_style"]],
            "PlotLine/joinStyle": style["line_join"], "PlotLine/hide": not style["line_visible"],
            "marker": style["marker"], "markerSize": number_unit(style["marker_size_pt"], "pt"),
            "MarkerFill/color": style["marker_color"], "MarkerLine/color": style["marker_color"],
            "MarkerLine/hide": not marker_visible, "MarkerFill/hide": not marker_visible,
            "MarkerLine/width": number_unit(style["marker_line_width_pt"], "pt"), "ErrorBarLine/hide": True,
            "FillAbove/hide": True, "FillBelow/hide": True,
        })
    # Page background exports identically into opaque PDF and TIFF canvases.
    node("rect", "/page1/background", {"positioning": "relative", "xPos": [0.5], "yPos": [0.5],
         "width": [1.0], "height": [1.0], "clip": True, "Fill/color": ir["background_color"],
         "Fill/hide": False, "Fill/transparency": 0, "Border/hide": True})
    return nodes


def apply_plan(interface: Any, ir: dict[str, Any]) -> None:
    for name, values in native_datasets(ir).items():
        interface.SetData(name, values)
    for node in drawing_plan(ir):
        path = node["path"]
        if path != "/":
            parent, name = path.rsplit("/", 1)
            interface.To(parent or "/")
            interface.Add(node["type"], name=name, autoadd=False)
        interface.To(path)
        for setting, value in node["settings"].items():
            try:
                interface.Set(setting, value)
            except Exception as exc:
                raise ValueError(f"Unsupported managed native setting {path}/{setting}: {value!r}") from exc
