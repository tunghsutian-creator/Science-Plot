"""Render categorical mean/error bars from the shared bar contract."""

from __future__ import annotations

from typing import Any

from sciplot_core.policy import (
    CATEGORICAL_BAR_FILL_TRANSPARENCY,
    CATEGORICAL_BAR_LINE_WIDTH_PT,
    CATEGORICAL_BAR_WIDTH_FRACTION,
    CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
    DEFAULT_PALETTE_COLORS,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LINE_WIDTH_PT,
    categorical_fill_color,
    categorical_keyline_color,
)

from sciplot_core.studio_core.legend_contracts import (
    _categorical_grouped_bar_fill_rect_contracts,
)
from sciplot_core.studio_core.veusz_primitives import _add_veusz_axis_line
from sciplot_core.studio_core.veusz_units import _pt


def add_veusz_error_bars(
    interface: Any,
    *,
    spec: dict[str, Any],
    categorical: dict[str, Any] | None,
) -> bool:
    """Render bar/error presentations and report whether one was handled."""

    if categorical is None or categorical.get("presentation_kind") not in {
        "bar_error",
        "grouped_bar_error",
    }:
        return False
    bar_style = (
        categorical.get("visual_style")
        if isinstance(categorical.get("visual_style"), dict)
        else {}
    )
    bar_width = float(
        bar_style.get("bar_width_fraction", CATEGORICAL_BAR_WIDTH_FRACTION)
    )
    bar_groups = [
        group for group in categorical.get("groups", []) if isinstance(group, dict)
    ]
    _add_error_lines(
        interface,
        bar_groups=bar_groups,
        bar_style=bar_style,
        bar_width=bar_width,
    )
    line_colors, fill_colors = _bar_colors(bar_groups)
    _add_bar_outlines(
        interface,
        bar_groups=bar_groups,
        bar_width=bar_width,
        bar_line_width=float(
            bar_style.get("bar_line_width_pt", CATEGORICAL_BAR_LINE_WIDTH_PT)
        ),
        line_colors=line_colors,
    )
    grouped_bar = categorical.get("presentation_kind") == "grouped_bar_error"
    _add_native_bars(
        interface,
        bar_groups=bar_groups,
        bar_style=bar_style,
        bar_width=bar_width,
        line_colors=line_colors,
        fill_colors=fill_colors,
        grouped_bar=grouped_bar,
    )
    if grouped_bar:
        _add_grouped_bar_fills(interface, spec)
    return True


def _add_error_lines(
    interface: Any,
    *,
    bar_groups: list[dict[str, Any]],
    bar_style: dict[str, Any],
    bar_width: float,
) -> None:
    error_cap_half_width = (
        bar_width
        * float(
            bar_style.get(
                "error_cap_to_bar_ratio",
                CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
            )
        )
        / 2.0
    )
    error_width = float(bar_style.get("error_line_width_pt", UNIFIED_LINE_WIDTH_PT))
    for bar_index, group in enumerate(bar_groups, start=1):
        position = float(group["position"])
        mean = float(group["bar_mean"])
        error = float(group["bar_error"])
        low = mean - error
        high = mean + error
        segments = (
            (position, low, position, high),
            (
                position - error_cap_half_width,
                high,
                position + error_cap_half_width,
                high,
            ),
            (
                position - error_cap_half_width,
                low,
                position + error_cap_half_width,
                low,
            ),
        )
        for line_index, (x_pos, y_pos, x_pos_2, y_pos_2) in enumerate(
            segments,
            start=1,
        ):
            interface.Add(
                "line",
                name=f"categorical_bar_error_{bar_index}_{line_index}",
                autoadd=False,
            )
            interface.To(f"categorical_bar_error_{bar_index}_{line_index}")
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
            interface.Set("Line/color", UNIFIED_FOREGROUND_COLOR)
            interface.Set("Line/width", _pt(error_width))
            interface.Set("Line/style", "solid")
            interface.Set("Line/transparency", 0)
            interface.Set("Line/hide", False)
            interface.Set("arrowleft", "none")
            interface.Set("arrowright", "none")
            interface.Set("Fill/hide", True)
            interface.To("..")


def _bar_colors(
    bar_groups: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    line_colors = [
        str(
            group.get("keyline_color")
            or categorical_keyline_color(group.get("color"))
            or DEFAULT_PALETTE_COLORS[index % len(DEFAULT_PALETTE_COLORS)]
        )
        for index, group in enumerate(bar_groups)
    ]
    fill_colors = [
        str(group.get("fill_color") or categorical_fill_color(line_colors[index]))
        for index, group in enumerate(bar_groups)
    ]
    return line_colors, fill_colors


def _add_bar_outlines(
    interface: Any,
    *,
    bar_groups: list[dict[str, Any]],
    bar_width: float,
    bar_line_width: float,
    line_colors: list[str],
) -> None:
    for bar_index, group in enumerate(bar_groups, start=1):
        position = float(group["position"])
        mean = float(group["bar_mean"])
        left = position - bar_width / 2.0
        right = position + bar_width / 2.0
        for outline_index, segment in enumerate(
            (
                (left, 0.0, left, mean),
                (right, 0.0, right, mean),
                (left, mean, right, mean),
            ),
            start=1,
        ):
            _add_veusz_axis_line(
                interface,
                name=f"categorical_bar_outline_{bar_index}_{outline_index}",
                x_pos=segment[0],
                y_pos=segment[1],
                x_pos_2=segment[2],
                y_pos_2=segment[3],
                color=line_colors[bar_index - 1],
                width_pt=bar_line_width,
            )


def _add_native_bars(
    interface: Any,
    *,
    bar_groups: list[dict[str, Any]],
    bar_style: dict[str, Any],
    bar_width: float,
    line_colors: list[str],
    fill_colors: list[str],
    grouped_bar: bool,
) -> None:
    inventories = (
        [
            (
                f"categorical_bar_{bar_index}",
                (f"category_bar_mean_{bar_index}",),
                [fill_colors[bar_index - 1]],
                [line_colors[bar_index - 1]],
            )
            for bar_index in range(1, len(bar_groups) + 1)
        ]
        if grouped_bar
        else [
            (
                "categorical_bar",
                tuple(
                    f"category_bar_mean_{bar_index}"
                    for bar_index in range(1, len(bar_groups) + 1)
                ),
                fill_colors,
                line_colors,
            )
        ]
    )
    line_width = float(
        bar_style.get("bar_line_width_pt", CATEGORICAL_BAR_LINE_WIDTH_PT)
    )
    for bar_name, lengths, fills, lines in inventories:
        interface.Add("bar", name=bar_name, autoadd=False)
        interface.To(bar_name)
        interface.Set("direction", "vertical")
        interface.Set("mode", "stacked")
        interface.Set("posn", "category_bar_positions")
        interface.Set("lengths", lengths)
        interface.Set("barfill", float(bar_style.get("native_barfill", bar_width)))
        interface.Set("groupfill", 0.75)
        interface.Set("errorstyle", "none")
        interface.Set("hide", grouped_bar)
        interface.Set(
            "BarFill/fills",
            [
                (
                    "solid",
                    color,
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
                for color in fills
            ],
        )
        interface.Set(
            "BarLine/lines",
            [("solid", _pt(line_width), color, True) for color in lines],
        )
        interface.To("..")


def _add_grouped_bar_fills(interface: Any, spec: dict[str, Any]) -> None:
    for fill in _categorical_grouped_bar_fill_rect_contracts(spec):
        interface.Add("rect", name=fill["name"], autoadd=False)
        interface.To(fill["name"])
        interface.Set("positioning", fill["positioning"])
        interface.Set("xAxis", "x")
        interface.Set("yAxis", "y")
        interface.Set("xPos", fill["xPos"])
        interface.Set("yPos", fill["yPos"])
        interface.Set("width", fill["width"])
        interface.Set("height", fill["height"])
        interface.Set("height", fill["height"])
        interface.Set("clip", fill["clip"])
        interface.Set("Fill/color", fill["fill_color"])
        interface.Set("Fill/hide", fill["fill_hide"])
        interface.Set("Fill/transparency", fill["fill_transparency"])
        interface.Set("Border/hide", fill["border_hide"])
        interface.To("..")
