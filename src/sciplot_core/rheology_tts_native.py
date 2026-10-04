"""Native Veusz page composition and exact saved-data audits for TTS suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from sciplot_core.policy import (
    CATEGORICAL_BAR_LINE_WIDTH_PT,
    UNIFIED_PANEL_LABEL_SIZE_PT,
)
from sciplot_core.studio_core.veusz_axis_apply import _add_veusz_axis
from sciplot_core.studio_core.veusz_data_import import import_veusz_spec_data
from sciplot_core.studio_core.veusz_graph_setup import _add_native_veusz_key
from sciplot_core.studio_core.veusz_primitives import (
    _add_veusz_axis_line,
    _add_veusz_xy_series,
)
from sciplot_core.studio_core.veusz_units import _pt
from sciplot_core.rheology_tts_presentation_audit import (
    audit_legend_presentation,
    audit_series_presentation,
)
from sciplot_core.rheology_tts_errors import (
    apply_native_errors,
    audit_native_errors,
    bind_native_errors,
)


def _label(
    interface: Any,
    name: str,
    text: str,
    x: float,
    y: float,
    *,
    size: float,
    bold: bool = False,
    align: str = "left",
) -> None:
    interface.Add("label", name=name, autoadd=False)
    interface.To(name)
    interface.Set("label", text)
    interface.Set("xPos", [x])
    interface.Set("yPos", [y])
    interface.Set("alignHorz", align)
    interface.Set("alignVert", "bottom")
    interface.Set("Text/size", _pt(size))
    interface.Set("Text/bold", bold)
    interface.Set("Text/color", "black")
    interface.To("..")


def save_native_figure(figure: dict[str, Any], path: Path) -> None:
    """Create graphs with shared axis/series primitives and save with native API."""
    from veusz import document
    from veusz.document import CommandInterface

    doc = document.Document()
    doc._sciplot_write_full_precision = True
    interface = CommandInterface(doc)
    width, height = figure["width_mm"], figure["height_mm"]
    style = figure["panels"][0]["style"]
    interface.Set("StyleSheet/Font/font", style["font_family"])
    interface.Set("StyleSheet/Font/size", _pt(style["font_size_pt"]))
    interface.Set("width", f"{width:g}mm")
    interface.Set("height", f"{height:g}mm")
    interface.Add("page", name="page1", autoadd=False)
    interface.To("page1")
    interface.Set("width", f"{width:g}mm")
    interface.Set("height", f"{height:g}mm")
    interface.Set("Background/color", "white")
    interface.Set("Background/hide", False)
    for panel in figure["panels"]:
        _panel(interface, panel, width, height)
    # Veusz paints siblings in reverse; this last rectangle is behind all graphs.
    interface.Add("rect", name="page_export_background", autoadd=False)
    interface.To("page_export_background")
    for setting, value in {
        "positioning": "relative",
        "xPos": [0.5],
        "yPos": [0.5],
        "width": [1.0],
        "height": [1.0],
        "Fill/color": "white",
        "Fill/hide": False,
        "Fill/transparency": 0,
        "Border/hide": True,
    }.items():
        interface.Set(setting, value)
    interface.Save(str(path))


def _panel(interface: Any, panel: dict[str, Any], width: float, height: float) -> None:
    style, axes = panel["style"], panel["axes"]
    left, top, panel_width, panel_height = panel["rect_mm"]
    margins = style["margins_mm"]
    top_margin = (
        float(margins["top"])
        if panel.get("standard_frame")
        else max(float(margins["top"]), 7.0)
    )
    import_veusz_spec_data(
        interface, series=panel["series"], axes=axes, categorical=None
    )
    bind_native_errors(interface, panel["series"])
    interface.To("/page1")
    interface.Add("graph", name=panel["id"], autoadd=False)
    interface.To(panel["id"])
    interface.Set("Border/hide", True)
    for name, value in {
        "leftMargin": left + margins["left"],
        "rightMargin": width - left - panel_width + margins["right"],
        "topMargin": top + top_margin,
        "bottomMargin": height - top - panel_height + margins["bottom"],
    }.items():
        interface.Set(name, f"{value:g}mm")
    for axis in ("x", "y"):
        _add_veusz_axis(interface, axis, axes[axis], style)
    if panel["x_tick_labels"]:
        interface.Set("x/TickLabels/hide", True)
        interface.Set("x/Label/offset", "10pt")
        lo, hi = axes["x"]["min"], axes["x"]["max"]
        for index, (value, label) in enumerate(
            zip(axes["x"]["ticks"], panel["x_tick_labels"], strict=True)
        ):
            _label(
                interface,
                f"tick_{index}",
                str(label),
                (value - lo) / (hi - lo),
                -0.08,
                size=style["font_size_pt"],
                align="centre",
            )
    if panel["legend"]:
        _add_native_veusz_key(
            interface,
            legend={"show": True, "columns": 1, "mode": str(panel["legend"])},
            style=style,
        )
    for index, note in enumerate(panel["notes"]):
        _label(
            interface,
            f"note_{index}",
            str(note["text"]),
            float(note["x"]),
            float(note["y"]),
            size=style["legend_font_size_pt"],
        )
    for item in panel["series"]:
        if item["kind"] == "bar":
            _bar(interface, item, axes)
        else:
            _add_veusz_xy_series(interface, item, style)
        apply_native_errors(interface, item)
    for index, ref in enumerate(panel["reference_lines"]):
        axis, value = ref["axis"], float(ref["value"])
        if axis not in ("x", "y"):
            raise ValueError("Reference lines require axis x or y.")
        x1, x2 = (value, value) if axis == "x" else (axes["x"]["min"], axes["x"]["max"])
        y1, y2 = (value, value) if axis == "y" else (axes["y"]["min"], axes["y"]["max"])
        _add_veusz_axis_line(
            interface,
            name=f"reference_{index}",
            x_pos=x1,
            y_pos=y1,
            x_pos_2=x2,
            y_pos_2=y2,
            color=ref.get("color", "#777777"),
            width_pt=style["axis_linewidth_pt"],
        )
        ref_style = ref.get("style", "dashed")
        interface.Set(
            f"reference_{index}/Line/style",
            {"dash": "dashed", "dot": "dotted"}.get(ref_style, ref_style),
        )
        if ref.get("label"):
            _label(
                interface,
                f"reference_label_{index}",
                str(ref["label"]),
                0.03,
                0.03,
                size=style["legend_font_size_pt"],
            )
    interface.To("/page1")
    _label(
        interface,
        f"title_{panel['id']}",
        panel["title"],
        (left + margins["left"]) / width,
        1 - (top + 4) / height,
        size=UNIFIED_PANEL_LABEL_SIZE_PT,
        bold=True,
    )


def _bar(interface: Any, item: dict[str, Any], axes: dict[str, Any]) -> None:
    interface.Add("bar", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("direction", "vertical")
    interface.Set("mode", "grouped")
    interface.Set("posn", item["x_name"])
    interface.Set("lengths", [item["y_name"]])
    interface.Set("keys", [item["legend_key"]])
    positions = item["x_values"]
    # Native single-point bar uses the whole plot width as its group width.
    # Convert the declared width in X units; no artificial zero-valued bars.
    spacing = (
        float(axes["x"]["max"]) - float(axes["x"]["min"])
        if len(positions) == 1
        else min(abs(b - a) for a, b in zip(positions[:-1], positions[1:], strict=True))
    )
    if spacing <= 0:
        raise ValueError("Bar positions must have nonzero separation.")
    interface.Set("barfill", float(item["bar_width"]) / spacing)
    interface.Set("groupfill", 1.0)
    interface.Set("errorstyle", "none")
    interface.Set(
        "BarFill/fills",
        [
            (
                "solid",
                item["color"],
                False,
                0,
                _pt(CATEGORICAL_BAR_LINE_WIDTH_PT),
                "solid",
                "5pt",
                "white",
                0,
                True,
            )
        ],
    )
    interface.Set(
        "BarLine/lines",
        [("solid", _pt(CATEGORICAL_BAR_LINE_WIDTH_PT), item["color"], True)],
    )
    interface.To("..")


def audit_native_figure(
    path: Path, figure: dict[str, Any], *, check_presentation: bool = False
) -> dict[str, Any]:
    """Reload saved VSZ and compare every data array and native plot binding."""
    from veusz import document
    from veusz.document import CommandInterface

    doc = document.Document()
    doc.load(str(path))
    interface = CommandInterface(doc)
    expected_data: set[str] = set()
    expected_plots: set[str] = set()
    expected_graphs = {f"/page1/{panel['id']}" for panel in figure["panels"]}
    panels = []
    presentation = []
    legends = []
    differences = []
    for panel in figure["panels"]:
        native_path = f"/page1/{panel['id']}"
        legend = audit_legend_presentation(interface, panel)
        legends.append(legend)
        differences.extend(
            {"widget_path": legend["widget_path"], **field}
            for field in legend["fields"]
            if not field["matches"]
        )
        count = 0
        for item in panel["series"]:
            expected_plots.add(f"{native_path}/{item['name']}")
            for axis in ("x", "y"):
                name = item[f"{axis}_name"]
                expected_data.add(name)
                if name not in doc.data or not np.array_equal(
                    doc.data[name].data, item[f"{axis}_values"]
                ):
                    raise ValueError(
                        f"Saved native data differs from source-bound analysis: {name}"
                    )
            audit_native_errors(doc, item)
            count += len(item["x_values"])
            interface.To(f"{native_path}/{item['name']}")
            if item["kind"] == "bar":
                actual = (interface.Get("posn"), tuple(interface.Get("lengths")))
                expected = (item["x_name"], (item["y_name"],))
            else:
                actual = (interface.Get("xData"), interface.Get("yData"))
                expected = (item["x_name"], item["y_name"])
            if actual != expected:
                raise ValueError(
                    f"Native plot points at different datasets: {native_path}"
                )
            evidence = audit_series_presentation(
                interface, item, panel, f"{native_path}/{item['name']}"
            )
            presentation.append(evidence)
            differences.extend(
                {"widget_path": evidence["widget_path"], **field}
                for field in evidence["fields"]
                if not field["matches"]
            )
        interface.To(native_path)
        if interface.Get("hide") is not False:
            differences.append(
                {
                    "widget_path": native_path,
                    "field": "hide",
                    "expected": False,
                    "actual": interface.Get("hide"),
                    "matches": False,
                }
            )
        frame = {
            name: interface.Get(name)
            for name in ("leftMargin", "rightMargin", "topMargin", "bottomMargin")
        }
        panels.append(
            {
                "id": panel["id"],
                "series_count": len(panel["series"]),
                "point_count": count,
                "error_point_count": sum(
                    len(item.get("error_values", [])) for item in panel["series"]
                ),
                "frame_settings": frame,
            }
        )
    if set(doc.data) != expected_data:
        raise ValueError("Saved document contains an unexpected dataset inventory.")
    actual_plots: set[str] = set()
    actual_graphs: set[str] = set()

    def collect(native_path: str, widget: Any) -> None:
        if widget.typename in {"xy", "bar"}:
            actual_plots.add(native_path)
        if widget.typename == "graph":
            actual_graphs.add(native_path)

    doc.walkNodes(collect, nodetypes=("widget",))
    if actual_plots != expected_plots or actual_graphs != expected_graphs:
        raise ValueError(
            "Saved document contains an unexpected graph or plotted-series inventory."
        )
    interface.To("/page1")
    if interface.Get("hide") is not False:
        differences.append(
            {
                "widget_path": "/page1",
                "field": "hide",
                "expected": False,
                "actual": interface.Get("hide"),
                "matches": False,
            }
        )
    if check_presentation and differences:
        first = differences[0]
        raise ValueError(
            f"Saved native presentation differs from resolved contract: {first['widget_path']} {first['field']} is {first['actual']!r}, expected {first['expected']!r}."
        )
    return {
        "kind": "sciplot_rheology_tts_native_audit",
        "version": 1,
        "status": "passed",
        "scope": "Exact saved numeric arrays and plot bindings; resolved creation presentation enforced."
        if check_presentation
        else "Exact saved numeric arrays and plot bindings; current native presentation is authoritative and differences are recorded.",
        "presentation": {
            "mode": "resolved_creation_contract"
            if check_presentation
            else "saved_native_authority",
            "template_match": not differences,
            "status": "matched" if not differences else "differs",
            "differences": differences,
            "series": presentation,
            "legends": legends,
        },
        "page_width": interface.Get("width"),
        "page_height": interface.Get("height"),
        "dataset_count": len(expected_data),
        "graph_count": len(actual_graphs),
        "plotted_series_count": len(actual_plots),
        "panels": panels,
    }
