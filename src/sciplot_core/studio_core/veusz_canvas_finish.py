"""Finalize categorical axes and the opaque Veusz export canvas."""

from __future__ import annotations

from typing import Any


def add_veusz_categorical_axis_provider(
    interface: Any,
    categorical: dict[str, Any] | None,
) -> None:
    """Provide native label-mode tick lookup without visible data marks."""

    if categorical is None:
        return
    interface.Add("xy", name="category_axis_label_provider", autoadd=False)
    interface.To("category_axis_label_provider")
    interface.Set("xData", "category_axis_x")
    interface.Set("yData", "category_axis_y")
    interface.Set("labels", "category_axis_labels")
    interface.Set("marker", "none")
    interface.Set("PlotLine/hide", True)
    label_provider_style_hidden = categorical.get("presentation_kind") not in {
        "bar_error",
        "stacked_components",
    }
    interface.Set("MarkerFill/hide", label_provider_style_hidden)
    interface.Set("MarkerLine/hide", label_provider_style_hidden)
    interface.Set("ErrorBarLine/hide", True)
    interface.Set("Label/hide", True)
    interface.To("..")


def finish_veusz_export_canvas(interface: Any) -> None:
    """Leave the graph and add a page-level opaque white background."""

    interface.To("..")
    interface.Add("rect", name="page_export_background", autoadd=False)
    interface.To("page_export_background")
    interface.Set("positioning", "relative")
    interface.Set("xPos", [0.5])
    interface.Set("yPos", [0.5])
    interface.Set("width", [1.0])
    interface.Set("height", [1.0])
    interface.Set("clip", True)
    interface.Set("Fill/color", "white")
    interface.Set("Fill/hide", False)
    interface.Set("Fill/transparency", 0)
    interface.Set("Border/hide", True)
    interface.To("..")
    interface.To("..")
