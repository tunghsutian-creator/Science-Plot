"""Build label, rectangle, line, and grouped-fill legend geometry."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_GROUPED_BAR_WIDTH_FRACTION,
    UNIFIED_FOREGROUND_COLOR,
)
from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
)


def _categorical_component_legend_label_contracts(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    legend = spec.get("legend")
    if (
        not isinstance(legend, dict)
        or legend.get("show") is not True
        or legend.get("presentation_kind") != "segmented_component"
    ):
        return []
    contracts: list[dict[str, Any]] = []
    for index, row in enumerate(legend.get("rows", []), start=1):
        if not isinstance(row, dict):
            continue
        contracts.append(
            {
                "name": f"component_legend_label_{index}",
                "label": str(row.get("label") or ""),
                "positioning": "relative",
                "x_axis": "x",
                "y_axis": "y",
                "x": float(legend["label_x_fraction"]),
                "y": float(row["y_fraction"]),
                "align": "left",
                "valign": "centre",
                "angle_degrees": 0.0,
                "margin_pt": 0.0,
                "clip": True,
                "text_size_pt": float(legend["label_text_size_pt"]),
                "text_color": str(legend["label_text_color"]),
                "text_hide": False,
                "background_color": "white",
                "background_transparency": 0,
                "background_hide": True,
                "border_color": UNIFIED_FOREGROUND_COLOR,
                "border_width_pt": float(spec["style"]["axis_linewidth_pt"]),
                "border_style": "solid",
                "border_transparency": 0,
                "border_hide": True,
            }
        )
    return contracts


def _categorical_component_legend_rect_contracts(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    legend = spec.get("legend")
    if (
        not isinstance(legend, dict)
        or legend.get("show") is not True
        or legend.get("presentation_kind") != "segmented_component"
    ):
        return []
    total_width = float(legend["swatch_width_fraction"])
    left = float(legend["swatch_left_fraction"])
    height = float(legend["swatch_height_fraction"])
    contracts: list[dict[str, Any]] = []
    for row_index, row in enumerate(legend.get("rows", []), start=1):
        if not isinstance(row, dict):
            continue
        colors = [str(value) for value in row.get("colors", [])]
        if not colors:
            continue
        segment_width = total_width / float(len(colors))
        for sample_index, color in enumerate(colors, start=1):
            contracts.append(
                {
                    "name": (f"component_legend_swatch_{row_index}_{sample_index}"),
                    "positioning": "relative",
                    "xPos": [left + (sample_index - 0.5) * segment_width],
                    "yPos": [float(row["y_fraction"])],
                    "width": [segment_width],
                    "height": [height],
                    "clip": True,
                    "fill_color": color,
                    "fill_hide": False,
                    "fill_transparency": 0,
                    "border_hide": True,
                }
            )
    return contracts


def _curve_factor_legend_label_contracts(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    legend = spec.get("legend")
    if (
        not isinstance(legend, dict)
        or legend.get("show") is not True
        or legend.get("presentation_kind") != "factorized_curve"
    ):
        return []
    contracts: list[dict[str, Any]] = []

    def append_label(
        *,
        name: str,
        label: str,
        x: float,
        y: float,
        align: str = "left",
    ) -> None:
        contracts.append(
            {
                "name": name,
                "label": label,
                "positioning": "relative",
                "x_axis": "x",
                "y_axis": "y",
                "x": x,
                "y": y,
                "align": align,
                "valign": "centre",
                "angle_degrees": 0.0,
                "margin_pt": 0.0,
                "clip": True,
                "text_size_pt": float(legend["label_text_size_pt"]),
                "text_color": str(legend["label_text_color"]),
                "text_hide": False,
                "background_color": "white",
                "background_transparency": 0,
                "background_hide": True,
                "border_color": UNIFIED_FOREGROUND_COLOR,
                "border_width_pt": float(spec["style"]["axis_linewidth_pt"]),
                "border_style": "solid",
                "border_transparency": 0,
                "border_hide": True,
            }
        )

    for group in legend.get("groups", []):
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id") or "").strip()
        title = str(group.get("title") or "").strip()
        if title:
            append_label(
                name=f"curve_factor_legend_{group_id}_title",
                label=title,
                x=float(group["title_x_fraction"]),
                y=float(group["title_y_fraction"]),
                align=str(group.get("title_align") or "left"),
            )
        for entry_index, entry in enumerate(group.get("entries", []), start=1):
            if not isinstance(entry, dict):
                continue
            append_label(
                name=(f"curve_factor_legend_{group_id}_label_{entry_index}"),
                label=str(entry.get("label") or ""),
                x=float(entry["label_x_fraction"]),
                y=float(entry["y_fraction"]),
                align=str(entry.get("label_align") or "left"),
            )
    return contracts


def _curve_factor_legend_condition_rect_contracts(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the closed segmented tone swatches for condition rows."""

    legend = spec.get("legend")
    if (
        not isinstance(legend, dict)
        or legend.get("show") is not True
        or legend.get("presentation_kind") != "factorized_curve"
    ):
        return []
    contracts: list[dict[str, Any]] = []
    for group in legend.get("groups", []):
        if not isinstance(group, dict) or group.get("id") != "condition":
            continue
        for row_index, entry in enumerate(group.get("entries", []), start=1):
            if not isinstance(entry, dict):
                continue
            colors = [str(value) for value in entry.get("colors", [])]
            if not colors:
                continue
            swatch_width = float(entry["swatch_width_fraction"])
            segment_width = swatch_width / float(len(colors))
            left = float(entry["swatch_left_fraction"])
            for color_index, color in enumerate(colors, start=1):
                contracts.append(
                    {
                        "name": (
                            "curve_factor_legend_condition_segment_"
                            f"{row_index}_{color_index}"
                        ),
                        "positioning": "relative",
                        "xPos": [left + (color_index - 0.5) * segment_width],
                        "yPos": [float(entry["y_fraction"])],
                        "width": [segment_width],
                        "height": [float(entry["swatch_height_fraction"])],
                        "clip": True,
                        "fill_color": color,
                        "fill_hide": False,
                        "fill_transparency": 0,
                        "border_hide": True,
                    }
                )
    return contracts


def _curve_factor_legend_line_contracts(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    legend = spec.get("legend")
    if (
        not isinstance(legend, dict)
        or legend.get("show") is not True
        or legend.get("presentation_kind") != "factorized_curve"
    ):
        return []
    contracts: list[dict[str, Any]] = []
    for group in legend.get("groups", []):
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id") or "").strip()
        for entry_index, entry in enumerate(group.get("entries", []), start=1):
            if (
                not isinstance(entry, dict)
                or entry.get("x_start_fraction") is None
                or entry.get("x_end_fraction") is None
            ):
                continue
            contracts.append(
                {
                    "name": (f"curve_factor_legend_{group_id}_swatch_{entry_index}"),
                    "positioning": "relative",
                    "x_axis": "x",
                    "y_axis": "y",
                    "mode": "point-to-point",
                    "xPos": [float(entry["x_start_fraction"])],
                    "yPos": [float(entry["y_fraction"])],
                    "xPos2": [float(entry["x_end_fraction"])],
                    "yPos2": [float(entry["y_fraction"])],
                    "clip": True,
                    "hide": False,
                    "line_color": str(entry["color"]),
                    "line_width_pt": float(entry["line_width_pt"]),
                    "line_style": str(entry["line_style"]),
                    "line_transparency": 0,
                    "line_hide": False,
                    "arrow_left": "none",
                    "arrow_right": "none",
                    "fill_hide": True,
                }
            )
    return contracts


def _categorical_grouped_bar_fill_rect_contracts(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    categorical = spec.get("categorical")
    if (
        not isinstance(categorical, dict)
        or categorical.get("presentation_kind") != "grouped_bar_error"
    ):
        return []
    visual_style = (
        categorical.get("visual_style")
        if isinstance(categorical.get("visual_style"), dict)
        else {}
    )
    bar_width = float(
        visual_style.get(
            "bar_width_fraction",
            CATEGORICAL_GROUPED_BAR_WIDTH_FRACTION,
        )
    )
    axes = spec.get("axes") if isinstance(spec.get("axes"), dict) else {}
    x_axis = axes.get("x") if isinstance(axes.get("x"), dict) else {}
    y_axis = axes.get("y") if isinstance(axes.get("y"), dict) else {}
    x_min = float(x_axis["min"])
    x_max = float(x_axis["max"])
    y_min = float(y_axis["min"])
    y_max = float(y_axis["max"])
    x_span = abs(x_max - x_min)
    y_span = abs(y_max - y_min)
    if (
        x_span <= 0.0
        or y_span <= 0.0
        or not math.isclose(
            y_min,
            0.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise StudioPreparationBlocked(
            "invalid_grouped_bar_fill_axis",
            "Grouped-bar fill rectangles require finite positive linear spans "
            "and a visible y=0 baseline.",
        )
    contracts: list[dict[str, Any]] = []
    for index, group in enumerate(categorical.get("groups", []), start=1):
        if not isinstance(group, dict):
            continue
        position = float(group["position"])
        mean = float(group["bar_mean"])
        contracts.append(
            {
                "name": f"categorical_bar_fill_{index}",
                "positioning": "axes",
                "xPos": [position],
                "yPos": [mean / 2.0],
                # Veusz rect xPos/yPos use axis coordinates in axes mode, but
                # width/height remain fractions of the graph rectangle.
                "width": [bar_width / x_span],
                "height": [mean / y_span],
                "clip": True,
                "fill_color": str(group["fill_color"]),
                "fill_hide": False,
                "fill_transparency": 0,
                "border_hide": True,
                "geometry": {
                    "left": position - bar_width / 2.0,
                    "right": position + bar_width / 2.0,
                    "bottom": 0.0,
                    "top": mean,
                },
            }
        )
    return contracts


categorical_component_legend_label_contracts = (
    _categorical_component_legend_label_contracts
)
categorical_component_legend_rect_contracts = (
    _categorical_component_legend_rect_contracts
)
curve_factor_legend_label_contracts = _curve_factor_legend_label_contracts
curve_factor_legend_condition_rect_contracts = (
    _curve_factor_legend_condition_rect_contracts
)
curve_factor_legend_line_contracts = _curve_factor_legend_line_contracts
categorical_grouped_bar_fill_rect_contracts = (
    _categorical_grouped_bar_fill_rect_contracts
)
