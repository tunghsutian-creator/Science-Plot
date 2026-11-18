"""Extract the admitted old saved XY subset from an actual Veusz document."""
from importlib import import_module
import math
import re
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import DocumentError
from sciplot_core.style_values import normalize_line_style
from sciplot_core.veusz_worker.document_edit import loaded_native_document


def unsupported(message: str) -> NoReturn:
    raise DocumentError("legacy_conversion_unsupported", message)


def _reject_unmapped(group: Any, permitted: set[str], prefix: str = "") -> None:
    for name, setting in group.setdict.items():
        field = prefix + name
        if field in permitted:
            continue
        if hasattr(setting, "setdict"):
            _reject_unmapped(setting, permitted, field + "/")
        elif not setting.isDefault():
            unsupported(f"The saved setting {field} is outside the supported conversion subset.")


def _distance(value: str, *, unit: str) -> float:
    match = re.fullmatch(r"([\d.]+)(mm|cm|pt)", value)
    if match is None:
        unsupported(f"The saved dimension {value!r} is not a supported physical size.")
    factors = {"mm": 1, "cm": 10, "pt": 25.4 / 72}
    return float(match[1]) * factors[match[2]] / factors[unit]


def inspect_legacy_xy(document: Path) -> dict[str, Any]:
    digest = file_sha256(document)
    with loaded_native_document(document) as loaded:
        if any(getattr(loaded.evaluate, name) for name in ("def_imports", "def_definitions", "def_colors", "def_colormaps")):
            unsupported("The saved document uses custom definitions, colors, or imports.")
        root = loaded.basewidget
        if len(root.children) != 1 or root.children[0].typename != "page":
            unsupported("Conversion currently requires one saved page.")
        page = root.children[0]
        if len(page.children) != 1 or page.children[0].typename != "graph":
            unsupported("Conversion currently requires one Cartesian graph.")
        graph = page.children[0]
        axes = {widget.settings.direction: widget for widget in graph.children if widget.typename == "axis"}
        curves = [widget for widget in graph.children if widget.typename == "xy"]
        if (set(axes) != {"horizontal", "vertical"} or len(curves) != 1
                or len(graph.children) != 3 or any(widget.children for widget in graph.children)):
            unsupported("Conversion currently supports exactly two ordinary axes and one XY curve, without other objects.")
        curve = curves[0].settings
        default_root = import_module("veusz.document").Document().basewidget
        if root.settings.get("StyleSheet").saveText(True) != default_root.settings.get("StyleSheet").saveText(True):
            unsupported("The saved document uses a custom stylesheet.")
        _reject_unmapped(root.settings, {"width", "height", "StyleSheet"})
        _reject_unmapped(page.settings, {"width", "height"})
        _reject_unmapped(graph.settings, {"leftMargin", "rightMargin", "topMargin", "bottomMargin"})
        _reject_unmapped(curve, {"xData", "yData", "xAxis", "yAxis", "color", "marker", "markerSize",
            "PlotLine/color", "PlotLine/width", "PlotLine/style", "PlotLine/hide"})
        if curve.xAxis != axes["horizontal"].name or curve.yAxis != axes["vertical"].name:
            unsupported("The XY curve does not use the two supported Cartesian axes.")
        if curve.xData == curve.yData or set(loaded.data) != {curve.xData, curve.yData}:
            unsupported("Only the two embedded datasets consumed by the saved XY curve can be converted.")
        coordinates = {}
        axis_facts = {}
        for dimension, direction, name in (("x", "horizontal", curve.xData), ("y", "vertical", curve.yData)):
            dataset = loaded.data[name]
            if (type(dataset).__module__ != "veusz.datasets.oned" or type(dataset).__name__ != "Dataset"
                    or any(getattr(dataset, key, None) is not None for key in ("linked", "serr", "nerr", "perr"))
                    or dataset.tags):
                unsupported(f"The {dimension} dataset uses links, expressions, errors, or tags.")
            values = [float(value) for value in dataset.data]
            if len(values) < 2 or not all(math.isfinite(value) for value in values):
                unsupported(f"The {dimension} dataset must contain at least two finite values.")
            coordinates[dimension] = values
            axis = axes[direction]
            _reject_unmapped(axis.settings, {"direction", "label", "min", "max", "MajorTicks/manualTicks"})
            if isinstance(axis.settings.min, str) or isinstance(axis.settings.max, str):
                unsupported(f"The {dimension} axis requires saved explicit linear limits.")
            low, high = map(float, axis.getPlottedRange())
            ticks = [float(value) for value in axis.majortickscalc]
            if not low < high or not low <= min(values) <= max(values) <= high:
                unsupported(f"The {dimension} axis has reversed bounds or hides saved values.")
            axis_facts[dimension] = {"label": axis.settings.label, "domain": [low, high], "ticks": ticks}
        if len(coordinates["x"]) != len(coordinates["y"]):
            unsupported("Saved X and Y arrays have different lengths.")

        def color(value: str) -> str:
            palette = loaded.evaluate.colors
            instance = palette.get(palette.getIndex(1) if value == "auto" else value)
            if not instance.isValid() or instance.alpha() != 255:
                unsupported("The saved curve color is outside the supported opaque colors.")
            return str(instance.name())

        marks = []
        if not curve.PlotLine.hide:
            line_color = curve.color if curve.PlotLine.color == "auto" else curve.PlotLine.color
            try:
                line_style = normalize_line_style(curve.PlotLine.style)
            except ValueError:
                unsupported("The saved line pattern is outside the supported visible styles.")
            marks.append({"id": "mark:line", "type": "line", "style": {
                "line_color": color(line_color), "line_width_pt": _distance(curve.PlotLine.width, unit="pt"),
                "line_style": line_style}})
        if curve.marker != "none":
            marker = {"circle": "circle", "square": "square", "diamond": "diamond",
                      "triangle": "triangle", "cross": "cross", "plus": "plus"}.get(curve.marker)
            if marker is None:
                unsupported("The saved marker is outside the supported marker shapes.")
            edge_color, fill_color = (color(curve.color if part.color == "auto" else part.color)
                                      for part in (curve.MarkerLine, curve.MarkerFill))
            if edge_color != fill_color or curve.MarkerLine.hide or curve.MarkerFill.hide:
                unsupported("The saved marker uses separately styled outline and fill.")
            marks.append({"id": "mark:points", "type": "point", "style": {
                "marker": marker, "marker_size_pt": _distance(curve.markerSize, unit="pt"),
                "marker_color": fill_color, "marker_line_width_pt": _distance(curve.MarkerLine.width, unit="pt")}})
        if not marks:
            unsupported("The saved XY curve has no visible marks.")
        layout = {"width_mm": _distance(page.settings.width, unit="mm"), "height_mm": _distance(page.settings.height, unit="mm"),
                  "outer_margins_mm": {side: _distance(getattr(graph.settings, side + "Margin"), unit="mm")
                                       for side in ("left", "right", "top", "bottom")}}
    if file_sha256(document) != digest:
        raise ValueError("The original native document changed during conversion inspection.")
    return {"document_sha256": digest, "coordinates": coordinates, "axes": axis_facts,
            "marks": marks, "layout": layout}
