"""Render categorical stacked-component bars in Veusz."""

from __future__ import annotations

from typing import Any

from sciplot_core.policy import (
    CATEGORICAL_BAR_FILL_TRANSPARENCY,
    CATEGORICAL_BAR_LINE_WIDTH_PT,
    CATEGORICAL_BAR_WIDTH_FRACTION,
)

from sciplot_core.studio_core.veusz_primitives import _add_veusz_axis_line
from sciplot_core.studio_core.veusz_units import _pt


def add_veusz_stacked_bars(
    interface: Any,
    categorical: dict[str, Any] | None,
) -> None:
    """Render a stacked-components contract as one native bar plotter."""

    if (
        categorical is None
        or categorical.get("presentation_kind") != "stacked_components"
    ):
        return
    bar_style = (
        categorical.get("visual_style")
        if isinstance(categorical.get("visual_style"), dict)
        else {}
    )
    bar_width = float(
        bar_style.get("bar_width_fraction", CATEGORICAL_BAR_WIDTH_FRACTION)
    )
    bar_line_width = float(
        bar_style.get("bar_line_width_pt", CATEGORICAL_BAR_LINE_WIDTH_PT)
    )
    bar_groups = [
        group for group in categorical.get("groups", []) if isinstance(group, dict)
    ]
    flattened = _add_component_outlines(
        interface,
        bar_groups=bar_groups,
        bar_width=bar_width,
        bar_line_width=bar_line_width,
    )
    interface.Add("bar", name="categorical_bar", autoadd=False)
    interface.To("categorical_bar")
    interface.Set("direction", "vertical")
    interface.Set("mode", "stacked")
    interface.Set("posn", "category_bar_positions")
    interface.Set(
        "lengths",
        tuple(
            f"category_bar_component_{group_index}_{component_index}"
            for group_index, component_index, _component in flattened
        ),
    )
    interface.Set("keys", tuple("" for _item in flattened))
    interface.Set("barfill", bar_width)
    interface.Set("groupfill", 0.75)
    interface.Set("errorstyle", "none")
    interface.Set(
        "BarFill/fills",
        [
            (
                "solid",
                str(component["fill_color"]),
                False,
                int(
                    bar_style.get(
                        "bar_fill_transparency",
                        CATEGORICAL_BAR_FILL_TRANSPARENCY,
                    )
                ),
                "0.5pt",
                "solid",
                "5pt",
                "white",
                0,
                True,
            )
            for _group_index, _component_index, component in flattened
        ],
    )
    interface.Set(
        "BarLine/lines",
        [
            (
                "solid",
                _pt(bar_line_width),
                str(component["keyline_color"]),
                True,
            )
            for _group_index, _component_index, component in flattened
        ],
    )
    interface.To("..")


def _add_component_outlines(
    interface: Any,
    *,
    bar_groups: list[dict[str, Any]],
    bar_width: float,
    bar_line_width: float,
) -> list[tuple[int, int, dict[str, Any]]]:
    flattened: list[tuple[int, int, dict[str, Any]]] = []
    for group_index, group in enumerate(bar_groups, start=1):
        position = float(group["position"])
        left = position - bar_width / 2.0
        right = position + bar_width / 2.0
        components = [
            component
            for component in group.get("components", [])
            if isinstance(component, dict)
        ]
        for component_index, component in enumerate(components, start=1):
            flattened.append((group_index, component_index, component))
            lower = float(component["stack_bottom"])
            upper = float(component["stack_top"])
            for outline_index, segment in enumerate(
                (
                    (left, lower, left, upper),
                    (right, lower, right, upper),
                    (left, upper, right, upper),
                ),
                start=1,
            ):
                _add_veusz_axis_line(
                    interface,
                    name=(
                        "categorical_stack_outline_"
                        f"{group_index}_{component_index}_{outline_index}"
                    ),
                    x_pos=segment[0],
                    y_pos=segment[1],
                    x_pos_2=segment[2],
                    y_pos_2=segment[3],
                    color=str(component["keyline_color"]),
                    width_pt=bar_line_width,
                )
    return flattened
