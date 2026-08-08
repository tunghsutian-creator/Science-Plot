"""Build reference-guide and categorical line geometry contracts."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_BAR_LINE_WIDTH_PT,
    CATEGORICAL_BAR_WIDTH_FRACTION,
    CATEGORICAL_BOX_FILL_FRACTION,
    CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LINE_WIDTH_PT,
    categorical_keyline_color,
)


def _axis_midpoint(axis_spec: dict[str, Any]) -> float:
    minimum = float(axis_spec["min"])
    maximum = float(axis_spec["max"])
    if (
        str(axis_spec.get("scale") or "linear") == "log"
        and minimum > 0.0
        and maximum > 0.0
    ):
        return math.sqrt(minimum * maximum)
    return 0.5 * (minimum + maximum)


def _axis_interval_geometry(
    axis_spec: dict[str, Any],
    *,
    start: float,
    end: float,
) -> tuple[float, float] | None:
    """Return data-space midpoint and occupied fraction for one axis interval."""

    minimum = float(axis_spec["min"])
    maximum = float(axis_spec["max"])
    clipped_start = max(start, minimum)
    clipped_end = min(end, maximum)
    if clipped_end <= clipped_start:
        return None
    if str(axis_spec.get("scale") or "linear") == "log":
        if minimum <= 0.0 or maximum <= minimum or clipped_start <= 0.0:
            raise ValueError(
                "Logarithmic reference-guide geometry requires positive, "
                "strictly increasing axis bounds."
            )
        midpoint = math.sqrt(clipped_start * clipped_end)
        occupied_fraction = math.log(clipped_end / clipped_start) / math.log(
            maximum / minimum
        )
    else:
        if maximum <= minimum:
            raise ValueError(
                "Reference-guide geometry requires strictly increasing axis bounds."
            )
        midpoint = 0.5 * (clipped_start + clipped_end)
        occupied_fraction = (clipped_end - clipped_start) / (maximum - minimum)
    return midpoint, occupied_fraction


def _reference_guide_rect_contracts(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Derive the closed, non-occluding graph-local band inventory."""

    guides = spec.get("reference_guides")
    if not isinstance(guides, list):
        return []
    axes = spec["axes"]
    x_axis = axes["x"]
    y_axis = axes["y"]
    if any(x_axis.get(key) is None for key in ("min", "max")) or any(
        y_axis.get(key) is None for key in ("min", "max")
    ):
        return []
    contracts: list[dict[str, Any]] = []
    for index, guide in enumerate(guides, start=1):
        if not isinstance(guide, dict) or str(guide.get("kind") or "band") != "band":
            continue
        axis = str(guide.get("axis") or "x")
        start = float(guide["start"])
        end = float(guide["end"])
        if axis == "x":
            geometry = _axis_interval_geometry(
                x_axis,
                start=start,
                end=end,
            )
            if geometry is None:
                continue
            center_x, width_fraction = geometry
            center_y = _axis_midpoint(y_axis)
            height_fraction = 1.0
        else:
            geometry = _axis_interval_geometry(
                y_axis,
                start=start,
                end=end,
            )
            if geometry is None:
                continue
            center_y, height_fraction = geometry
            center_x = _axis_midpoint(x_axis)
            width_fraction = 1.0
        width_fraction = min(max(width_fraction, 0.0), 1.0)
        height_fraction = min(max(height_fraction, 0.0), 1.0)
        transparency = int(guide["transparency"])
        occupied_axis_fraction = width_fraction if axis == "x" else height_fraction
        if occupied_axis_fraction > 0.8:
            raise ValueError(
                "Reference-guide bands cannot cover more than 80% of their "
                "scientific axis."
            )
        contracts.append(
            {
                "name": f"reference_guide_{index}",
                "positioning": "axes",
                "xPos": [center_x],
                "yPos": [center_y],
                "width": [width_fraction],
                "height": [height_fraction],
                "clip": True,
                "fill_color": str(guide.get("color") or "#6B7280"),
                "fill_hide": False,
                "fill_transparency": transparency,
                "border_hide": True,
            }
        )
    return contracts


def _categorical_line_contracts(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Derive the closed native line inventory for categorical summaries."""

    categorical = spec.get("categorical")
    if not isinstance(categorical, dict):
        return []
    style = (
        categorical.get("visual_style")
        if isinstance(categorical.get("visual_style"), dict)
        else {}
    )
    groups = [
        group for group in categorical.get("groups", []) if isinstance(group, dict)
    ]
    contracts: list[dict[str, Any]] = []

    def append(
        *,
        name: str,
        x_pos: float,
        y_pos: float,
        x_pos_2: float,
        y_pos_2: float,
        color: str,
        width_pt: float,
    ) -> None:
        contracts.append(
            {
                "name": name,
                "positioning": "axes",
                "x_axis": "x",
                "y_axis": "y",
                "mode": "point-to-point",
                "xPos": [x_pos],
                "yPos": [y_pos],
                "xPos2": [x_pos_2],
                "yPos2": [y_pos_2],
                "clip": True,
                "hide": False,
                "line_color": color,
                "line_width_pt": width_pt,
                "line_style": "solid",
                "line_transparency": 0,
                "line_hide": False,
                "arrow_left": "none",
                "arrow_right": "none",
                "fill_hide": True,
            }
        )

    if categorical.get("native_veusz_boxplot") is True:
        fill_fraction = float(
            style.get("box_fill_fraction", CATEGORICAL_BOX_FILL_FRACTION)
        )
        box_groups = [
            group for group in groups if group.get("boxplot_eligible") is True
        ]
        for box_index, group in enumerate(box_groups, start=1):
            position = float(group["position"])
            left = position - fill_fraction / 2.0
            right = position + fill_fraction / 2.0
            statistics = group["descriptive_statistics"]
            median = float(statistics["median"])
            append(
                name=f"categorical_box_median_{box_index}",
                x_pos=left,
                y_pos=median,
                x_pos_2=right,
                y_pos_2=median,
                color=UNIFIED_FOREGROUND_COLOR,
                width_pt=UNIFIED_LINE_WIDTH_PT,
            )

    if categorical.get("presentation_kind") in {
        "bar_error",
        "grouped_bar_error",
    }:
        bar_width = float(
            style.get("bar_width_fraction", CATEGORICAL_BAR_WIDTH_FRACTION)
        )
        error_cap_half_width = (
            bar_width
            * float(
                style.get("error_cap_to_bar_ratio", CATEGORICAL_ERROR_CAP_TO_BAR_RATIO)
            )
            / 2.0
        )
        error_width = float(style.get("error_line_width_pt", UNIFIED_LINE_WIDTH_PT))
        bar_line_width = float(
            style.get("bar_line_width_pt", CATEGORICAL_BAR_LINE_WIDTH_PT)
        )
        for bar_index, group in enumerate(groups, start=1):
            position = float(group["position"])
            mean = float(group["bar_mean"])
            error = float(group["bar_error"])
            if not math.isfinite(error) or error <= 0.0:
                continue
            low = mean - error
            high = mean + error
            for line_index, (x_pos, y_pos, x_pos_2, y_pos_2) in enumerate(
                (
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
                ),
                start=1,
            ):
                append(
                    name=f"categorical_bar_error_{bar_index}_{line_index}",
                    x_pos=x_pos,
                    y_pos=y_pos,
                    x_pos_2=x_pos_2,
                    y_pos_2=y_pos_2,
                    color=UNIFIED_FOREGROUND_COLOR,
                    width_pt=error_width,
                )
            left = position - bar_width / 2.0
            right = position + bar_width / 2.0
            keyline_color = str(
                group.get("keyline_color")
                or categorical_keyline_color(group.get("color"))
            )
            for outline_index, (x_pos, y_pos, x_pos_2, y_pos_2) in enumerate(
                (
                    (left, 0.0, left, mean),
                    (right, 0.0, right, mean),
                    (left, mean, right, mean),
                ),
                start=1,
            ):
                append(
                    name=f"categorical_bar_outline_{bar_index}_{outline_index}",
                    x_pos=x_pos,
                    y_pos=y_pos,
                    x_pos_2=x_pos_2,
                    y_pos_2=y_pos_2,
                    color=keyline_color,
                    width_pt=bar_line_width,
                )
    elif categorical.get("presentation_kind") == "stacked_components":
        bar_width = float(
            style.get("bar_width_fraction", CATEGORICAL_BAR_WIDTH_FRACTION)
        )
        bar_line_width = float(
            style.get("bar_line_width_pt", CATEGORICAL_BAR_LINE_WIDTH_PT)
        )
        for group_index, group in enumerate(groups, start=1):
            position = float(group["position"])
            left = position - bar_width / 2.0
            right = position + bar_width / 2.0
            for component_index, component in enumerate(
                group.get("components", []),
                start=1,
            ):
                lower = float(component["stack_bottom"])
                upper = float(component["stack_top"])
                color = str(component["keyline_color"])
                for outline_index, (
                    x_pos,
                    y_pos,
                    x_pos_2,
                    y_pos_2,
                ) in enumerate(
                    (
                        (left, lower, left, upper),
                        (right, lower, right, upper),
                        (left, upper, right, upper),
                    ),
                    start=1,
                ):
                    append(
                        name=(
                            "categorical_stack_outline_"
                            f"{group_index}_{component_index}_{outline_index}"
                        ),
                        x_pos=x_pos,
                        y_pos=y_pos,
                        x_pos_2=x_pos_2,
                        y_pos_2=y_pos_2,
                        color=color,
                        width_pt=bar_line_width,
                    )
    return contracts


def _reference_guide_line_contracts(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Derive the closed native point-to-point reference-line inventory."""

    guides = spec.get("reference_guides")
    if not isinstance(guides, list):
        return []
    axes = spec["axes"]
    x_axis = axes["x"]
    y_axis = axes["y"]
    if any(x_axis.get(key) is None for key in ("min", "max")) or any(
        y_axis.get(key) is None for key in ("min", "max")
    ):
        return []
    x_min, x_max = float(x_axis["min"]), float(x_axis["max"])
    y_min, y_max = float(y_axis["min"]), float(y_axis["max"])
    contracts: list[dict[str, Any]] = []
    for index, guide in enumerate(guides, start=1):
        if not isinstance(guide, dict) or str(guide.get("kind") or "band") != "line":
            continue
        axis = str(guide.get("axis") or "x")
        value = float(guide["start"])
        if axis == "x":
            if not x_min <= value <= x_max:
                continue
            x_pos = [value]
            y_pos = [y_min]
            x_pos_2 = [value]
            y_pos_2 = [y_max]
        else:
            if not y_min <= value <= y_max:
                continue
            x_pos = [x_min]
            y_pos = [value]
            x_pos_2 = [x_max]
            y_pos_2 = [value]
        contracts.append(
            {
                "name": f"reference_guide_{index}",
                "positioning": "axes",
                "x_axis": "x",
                "y_axis": "y",
                "mode": "point-to-point",
                "xPos": x_pos,
                "yPos": y_pos,
                "xPos2": x_pos_2,
                "yPos2": y_pos_2,
                "clip": True,
                "hide": False,
                "line_color": str(guide.get("color") or "#6B7280"),
                "line_width_pt": float(guide["line_width_pt"]),
                "line_style": str(guide["line_style"]),
                "line_transparency": int(guide["transparency"]),
                "line_hide": False,
                "arrow_left": "none",
                "arrow_right": "none",
                "fill_hide": True,
            }
        )
    return contracts


reference_guide_rect_contracts = _reference_guide_rect_contracts
categorical_line_contracts = _categorical_line_contracts
reference_guide_line_contracts = _reference_guide_line_contracts
