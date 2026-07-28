"""Apply one complete performance specification to a live Veusz document."""

from __future__ import annotations

from typing import Any

from sciplot_core.performance_veusz.style import (
    _pt,
    _cm_from_mm,
)

from sciplot_core.performance_veusz.contracts import (
    performance_polygon_contracts,
    performance_line_contracts,
    performance_label_contracts,
)

from sciplot_core.performance_veusz.widget_apply import (
    _add_label,
    _add_axis,
    _add_inside_key,
    _add_xy_series,
    _add_polygon,
    _add_line,
)


def apply_performance_veusz_spec(interface: Any, spec: dict[str, Any]) -> None:
    """Materialize the native editable document from the closed spec."""

    style = spec["style"]
    size_mm = spec["size_mm"]
    for item in spec["series"]:
        interface.ImportString(
            f"{item['x_name']}(numeric)",
            "\n".join(f"{float(value):.12g}" for value in item["x_values"]),
        )
        interface.ImportString(
            f"{item['y_name']}(numeric)",
            "\n".join(f"{float(value):.12g}" for value in item["y_values"]),
        )
    interface.Set("StyleSheet/Font/font", style["font_family"])
    interface.Set("StyleSheet/Font/size", _pt(float(style["font_size_pt"])))
    interface.Set("StyleSheet/Line/width", _pt(float(style["line_width_pt"])))
    interface.Set("width", f"{float(size_mm[0]):g}mm")
    interface.Set("height", f"{float(size_mm[1]):g}mm")
    interface.Add("page", name="page1", autoadd=False)
    interface.To("page1")
    interface.Set("width", f"{float(size_mm[0]):g}mm")
    interface.Set("height", f"{float(size_mm[1]):g}mm")
    interface.Set("Background/color", "white")
    interface.Set("Background/hide", False)
    labels = performance_label_contracts(spec)
    polygons = performance_polygon_contracts(spec)
    for label in labels:
        if label["parent"] == "page":
            _add_label(interface, label)
    for item in polygons:
        if item.get("parent") == "page":
            _add_polygon(interface, item)
    interface.Add("graph", name="graph1", autoadd=False)
    interface.To("graph1")
    interface.Set("Border/hide", True)
    margins = style["margins_mm"]
    interface.Set("leftMargin", _cm_from_mm(float(margins["left"])))
    interface.Set("rightMargin", _cm_from_mm(float(margins["right"])))
    interface.Set("topMargin", _cm_from_mm(float(margins["top"])))
    interface.Set("bottomMargin", _cm_from_mm(float(margins["bottom"])))
    _add_axis(interface, name="x", axis=spec["axes"]["x"], style=style)
    _add_axis(interface, name="y", axis=spec["axes"]["y"], style=style)
    _add_inside_key(interface, spec["legend"], style)
    for label in labels:
        if label["parent"] == "graph":
            _add_label(interface, label)
    for item in spec["series"]:
        _add_xy_series(interface, item, style)
    for item in polygons:
        if item.get("parent") != "page":
            _add_polygon(interface, item)
    for item in performance_line_contracts(spec):
        _add_line(interface, item)
    interface.To("..")
    interface.To("..")
