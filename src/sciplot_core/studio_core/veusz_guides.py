"""Add validated reference guides to a Veusz document."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_core.veusz_units import (
    _pt,
)

from sciplot_core.studio_core.guide_contracts import (
    _reference_guide_rect_contracts,
    _reference_guide_line_contracts,
)


def _add_veusz_reference_guides(interface: Any, spec: dict[str, Any]) -> None:
    for contract in _reference_guide_rect_contracts(spec):
        interface.Add("rect", name=contract["name"], autoadd=False)
        interface.To(contract["name"])
        interface.Set("positioning", contract["positioning"])
        interface.Set("xPos", contract["xPos"])
        interface.Set("yPos", contract["yPos"])
        interface.Set("width", contract["width"])
        interface.Set("height", contract["height"])
        interface.Set("clip", True)
        interface.Set("Fill/color", contract["fill_color"])
        interface.Set("Fill/transparency", contract["fill_transparency"])
        interface.Set("Fill/hide", contract["fill_hide"])
        interface.Set("Border/hide", contract["border_hide"])
        interface.To("..")
    for contract in _reference_guide_line_contracts(spec):
        interface.Add("line", name=contract["name"], autoadd=False)
        interface.To(contract["name"])
        interface.Set("positioning", contract["positioning"])
        interface.Set("xAxis", contract["x_axis"])
        interface.Set("yAxis", contract["y_axis"])
        interface.Set("mode", contract["mode"])
        interface.Set("xPos", contract["xPos"])
        interface.Set("yPos", contract["yPos"])
        interface.Set("xPos2", contract["xPos2"])
        interface.Set("yPos2", contract["yPos2"])
        interface.Set("clip", contract["clip"])
        interface.Set("hide", contract["hide"])
        interface.Set("Line/color", contract["line_color"])
        interface.Set("Line/width", _pt(contract["line_width_pt"]))
        interface.Set("Line/style", contract["line_style"])
        interface.Set(
            "Line/transparency",
            contract["line_transparency"],
        )
        interface.Set("Line/hide", contract["line_hide"])
        interface.Set("arrowleft", contract["arrow_left"])
        interface.Set("arrowright", contract["arrow_right"])
        interface.Set("Fill/hide", contract["fill_hide"])
        interface.To("..")
