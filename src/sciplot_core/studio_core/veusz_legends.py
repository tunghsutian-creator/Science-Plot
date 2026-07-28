"""Add categorical, factorized, direct-label, and impact annotations to Veusz."""

from __future__ import annotations

from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_BAR_WIDTH_FRACTION,
    CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
    UNIFIED_LINE_WIDTH_PT,
)

from sciplot_core.studio_core.series_request import (
    _veusz_literal_text,
)

from sciplot_core.studio_core.veusz_units import (
    _pt,
)

from sciplot_core.studio_core.legend_contracts import (
    _categorical_component_legend_label_contracts,
    _categorical_component_legend_rect_contracts,
    _curve_factor_legend_label_contracts,
    _curve_factor_legend_condition_rect_contracts,
    _curve_factor_legend_line_contracts,
)


def _add_veusz_categorical_component_legend(
    interface: Any,
    spec: dict[str, Any],
) -> None:
    # Veusz paints graph children in reverse order. Labels are added first so
    # they paint over, rather than under, the segmented colour swatches.
    for item in _categorical_component_legend_label_contracts(spec):
        interface.Add("label", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("positioning", item["positioning"])
        interface.Set("xAxis", item["x_axis"])
        interface.Set("yAxis", item["y_axis"])
        interface.Set("xPos", [float(item["x"])])
        interface.Set("yPos", [float(item["y"])])
        interface.Set("label", _veusz_literal_text(item["label"]))
        interface.Set("alignHorz", item["align"])
        interface.Set("alignVert", item["valign"])
        interface.Set("angle", float(item["angle_degrees"]))
        interface.Set("margin", _pt(float(item["margin_pt"])))
        interface.Set("clip", item["clip"])
        interface.Set("hide", False)
        interface.Set("Text/size", _pt(float(item["text_size_pt"])))
        interface.Set("Text/color", item["text_color"])
        interface.Set("Text/hide", item["text_hide"])
        interface.Set("Background/color", item["background_color"])
        interface.Set(
            "Background/transparency",
            item["background_transparency"],
        )
        interface.Set("Background/hide", item["background_hide"])
        interface.Set("Border/color", item["border_color"])
        interface.Set("Border/width", _pt(float(item["border_width_pt"])))
        interface.Set("Border/style", item["border_style"])
        interface.Set(
            "Border/transparency",
            item["border_transparency"],
        )
        interface.Set("Border/hide", item["border_hide"])
        interface.To("..")
    for item in _categorical_component_legend_rect_contracts(spec):
        interface.Add("rect", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("positioning", item["positioning"])
        interface.Set("xPos", item["xPos"])
        interface.Set("yPos", item["yPos"])
        interface.Set("width", item["width"])
        interface.Set("height", item["height"])
        interface.Set("clip", item["clip"])
        interface.Set("Fill/color", item["fill_color"])
        interface.Set("Fill/hide", item["fill_hide"])
        interface.Set("Fill/transparency", item["fill_transparency"])
        interface.Set("Border/hide", item["border_hide"])
        interface.To("..")


def _add_veusz_curve_factor_legend(
    interface: Any,
    spec: dict[str, Any],
) -> None:
    # Labels are inserted before swatches and data plotters because Veusz
    # paints graph children in reverse tree order.
    for item in _curve_factor_legend_label_contracts(spec):
        interface.Add("label", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("positioning", item["positioning"])
        interface.Set("xAxis", item["x_axis"])
        interface.Set("yAxis", item["y_axis"])
        interface.Set("xPos", [float(item["x"])])
        interface.Set("yPos", [float(item["y"])])
        interface.Set("label", _veusz_literal_text(item["label"]))
        interface.Set("alignHorz", item["align"])
        interface.Set("alignVert", item["valign"])
        interface.Set("angle", float(item["angle_degrees"]))
        interface.Set("margin", _pt(float(item["margin_pt"])))
        interface.Set("clip", item["clip"])
        interface.Set("hide", False)
        interface.Set("Text/size", _pt(float(item["text_size_pt"])))
        interface.Set("Text/color", item["text_color"])
        interface.Set("Text/hide", item["text_hide"])
        interface.Set("Background/color", item["background_color"])
        interface.Set(
            "Background/transparency",
            item["background_transparency"],
        )
        interface.Set("Background/hide", item["background_hide"])
        interface.Set("Border/color", item["border_color"])
        interface.Set("Border/width", _pt(float(item["border_width_pt"])))
        interface.Set("Border/style", item["border_style"])
        interface.Set(
            "Border/transparency",
            item["border_transparency"],
        )
        interface.Set("Border/hide", item["border_hide"])
        interface.To("..")
    for item in _curve_factor_legend_condition_rect_contracts(spec):
        interface.Add("rect", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("positioning", item["positioning"])
        interface.Set("xPos", item["xPos"])
        interface.Set("yPos", item["yPos"])
        interface.Set("width", item["width"])
        interface.Set("height", item["height"])
        interface.Set("clip", item["clip"])
        interface.Set("Fill/color", item["fill_color"])
        interface.Set("Fill/hide", item["fill_hide"])
        interface.Set("Fill/transparency", item["fill_transparency"])
        interface.Set("Border/hide", item["border_hide"])
        interface.To("..")
    for item in _curve_factor_legend_line_contracts(spec):
        interface.Add("line", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("positioning", item["positioning"])
        interface.Set("xAxis", item["x_axis"])
        interface.Set("yAxis", item["y_axis"])
        interface.Set("mode", item["mode"])
        interface.Set("xPos", item["xPos"])
        interface.Set("yPos", item["yPos"])
        interface.Set("xPos2", item["xPos2"])
        interface.Set("yPos2", item["yPos2"])
        interface.Set("clip", item["clip"])
        interface.Set("hide", item["hide"])
        interface.Set("Line/color", item["line_color"])
        interface.Set("Line/width", _pt(float(item["line_width_pt"])))
        interface.Set("Line/style", item["line_style"])
        interface.Set("Line/transparency", item["line_transparency"])
        interface.Set("Line/hide", item["line_hide"])
        interface.Set("arrowleft", item["arrow_left"])
        interface.Set("arrowright", item["arrow_right"])
        interface.Set("Fill/hide", item["fill_hide"])
        interface.To("..")


def _add_veusz_direct_labels(interface: Any, spec: dict[str, Any]) -> None:
    for item in spec["direct_labels"]:
        interface.Add("label", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("positioning", item["positioning"])
        interface.Set("xAxis", item["x_axis"])
        interface.Set("yAxis", item["y_axis"])
        interface.Set("xPos", [float(item["x"])])
        interface.Set("yPos", [float(item["y"])])
        interface.Set("label", _veusz_literal_text(item["label"]))
        interface.Set("alignHorz", item["align"])
        interface.Set("alignVert", item["valign"])
        interface.Set("angle", float(item["angle_degrees"]))
        interface.Set("margin", _pt(float(item["margin_pt"])))
        interface.Set("clip", item["clip"])
        interface.Set("hide", False)
        interface.Set("Text/size", _pt(float(item["text_size_pt"])))
        interface.Set("Text/color", item["text_color"])
        interface.Set("Text/hide", item["text_hide"])
        interface.Set("Background/color", item["background_color"])
        interface.Set(
            "Background/transparency",
            item["background_transparency"],
        )
        interface.Set("Background/hide", item["background_hide"])
        interface.Set("Border/color", item["border_color"])
        interface.Set(
            "Border/width",
            _pt(float(item["border_width_pt"])),
        )
        interface.Set("Border/style", item["border_style"])
        interface.Set(
            "Border/transparency",
            item["border_transparency"],
        )
        interface.Set("Border/hide", item["border_hide"])
        interface.To("..")


def _add_veusz_impact_point_line_error_bars(
    interface: Any,
    categorical: dict[str, Any] | None,
) -> None:
    if (
        not isinstance(categorical, dict)
        or categorical.get("presentation_kind") != "point_line_raw_overlay"
    ):
        return
    visual_style = (
        categorical.get("visual_style")
        if isinstance(categorical.get("visual_style"), dict)
        else {}
    )
    cap_half_width = (
        float(
            visual_style.get(
                "error_cap_reference_width_fraction",
                CATEGORICAL_BAR_WIDTH_FRACTION,
            )
        )
        * float(
            visual_style.get(
                "error_cap_to_bar_ratio",
                CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
            )
        )
        / 2.0
    )
    error_width = float(visual_style.get("error_line_width_pt", UNIFIED_LINE_WIDTH_PT))
    for error_index, error_bar in enumerate(
        categorical.get("error_bars", []),
        start=1,
    ):
        if not isinstance(error_bar, dict):
            continue
        position = float(error_bar["position"])
        low = float(error_bar["low"])
        high = float(error_bar["high"])
        color = str(error_bar["color"])
        for line_index, (x_pos, y_pos, x_pos_2, y_pos_2) in enumerate(
            (
                (position, low, position, high),
                (
                    position - cap_half_width,
                    high,
                    position + cap_half_width,
                    high,
                ),
                (
                    position - cap_half_width,
                    low,
                    position + cap_half_width,
                    low,
                ),
            ),
            start=1,
        ):
            line_name = f"impact_point_line_error_{error_index}_{line_index}"
            interface.Add("line", name=line_name, autoadd=False)
            interface.To(line_name)
            interface.Set("positioning", "axes")
            interface.Set("xAxis", "x")
            interface.Set("yAxis", "y")
            interface.Set("mode", "point-to-point")
            interface.Set("xPos", [x_pos])
            interface.Set("yPos", [y_pos])
            interface.Set("xPos2", [x_pos_2])
            interface.Set("yPos2", [y_pos_2])
            interface.Set("clip", True)
            interface.Set("hide", False)
            interface.Set("Line/color", color)
            interface.Set("Line/width", _pt(error_width))
            interface.Set("Line/style", "solid")
            interface.Set("Line/transparency", 0)
            interface.Set("Line/hide", False)
            interface.Set("arrowleft", "none")
            interface.Set("arrowright", "none")
            interface.Set("Fill/hide", True)
            interface.To("..")
