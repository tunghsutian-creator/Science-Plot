"""Configure the Veusz page, graph, axes, annotations, and native key."""

from __future__ import annotations

from typing import Any

from sciplot_core.policy import UNIFIED_LEGEND_KEY_LENGTH_MM
from sciplot_core.studio_render.value_parsing import _optional_float

from sciplot_core.studio_core.context import _normalize_optional_string
from sciplot_core.studio_core.veusz_axis_apply import (
    _add_veusz_axis,
    _apply_key_position,
)
from sciplot_core.studio_core.veusz_legends import (
    _add_veusz_categorical_component_legend,
    _add_veusz_curve_factor_legend,
    _add_veusz_direct_labels,
    _add_veusz_impact_point_line_error_bars,
)
from sciplot_core.studio_core.veusz_primitives import _add_veusz_scalar_field
from sciplot_core.studio_core.veusz_units import _cm_from_mm, _pt


def create_veusz_page_and_graph(
    interface: Any,
    *,
    style: dict[str, Any],
    axes: dict[str, Any],
    size_mm: list[float],
) -> None:
    """Create a fixed-size white page and publication-frame graph."""

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
    interface.Add("graph", name="graph1", autoadd=False)
    interface.To("graph1")
    interface.Set("Border/hide", True)
    margins = style["margins_mm"]
    interface.Set("leftMargin", _cm_from_mm(float(margins["left"])))
    interface.Set("rightMargin", _cm_from_mm(float(margins["right"])))
    interface.Set("topMargin", _cm_from_mm(float(margins["top"])))
    interface.Set("bottomMargin", _cm_from_mm(float(margins["bottom"])))
    _add_veusz_axis(interface, "x", axes["x"], style)
    _add_veusz_axis(interface, "y", axes["y"], style)


def add_veusz_graph_annotations(
    interface: Any,
    *,
    spec: dict[str, Any],
    categorical: dict[str, Any] | None,
    style: dict[str, Any],
) -> None:
    """Add labels, custom legends, scalar fields, key, and error bars."""

    # Veusz paints graph children in reverse object-tree order. Add direct
    # labels before plotters so the labels paint last.
    _add_veusz_direct_labels(interface, spec)
    _add_veusz_categorical_component_legend(interface, spec)
    _add_veusz_curve_factor_legend(interface, spec)
    scalar = (
        spec.get("scalar_field") if isinstance(spec.get("scalar_field"), dict) else None
    )
    if scalar is not None:
        _add_veusz_scalar_field(interface, scalar)
    _add_native_veusz_key(interface, legend=spec["legend"], style=style)
    # Add error bars before data plotters so reverse painting keeps them visible.
    _add_veusz_impact_point_line_error_bars(interface, categorical)


def _add_native_veusz_key(
    interface: Any,
    *,
    legend: dict[str, Any],
    style: dict[str, Any],
) -> None:
    if not legend["show"] or legend.get("presentation_kind") in {
        "segmented_component",
        "factorized_curve",
    }:
        return
    interface.Add("key", name="key1", autoadd=False)
    interface.To("key1")
    interface.Set("title", "")
    interface.Set("Text/size", _pt(float(style["legend_font_size_pt"])))
    interface.Set(
        "keyLength",
        f"{UNIFIED_LEGEND_KEY_LENGTH_MM / 10.0:.2f}cm",
    )
    interface.Set("marginSize", 0.15)
    interface.Set("columns", int(legend["columns"]))
    _apply_key_position(
        interface,
        str(legend.get("mode") or "inside_best"),
        horz_position=_normalize_optional_string(legend.get("horz_position")),
        vert_position=_normalize_optional_string(legend.get("vert_position")),
        horz_manual=_optional_float(legend.get("horz_manual")),
        vert_manual=_optional_float(legend.get("vert_manual")),
    )
    interface.Set("Background/hide", not bool(style["legend_frameon"]))
    interface.Set("Border/hide", not bool(style["legend_frameon"]))
    interface.To("..")
