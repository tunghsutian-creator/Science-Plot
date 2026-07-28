"""Build label and inside-legend layout contracts."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    PERFORMANCE_REFERENCE_PANEL_WIDTH_MM,
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LEGEND_FONT_SIZE_PT,
)

from sciplot_core.performance_veusz.style import (
    _LEGEND_PAIRED_SLOT_OFFSET_MM,
)


def _label_contract(
    *,
    name: str,
    label: str,
    parent: str,
    positioning: str,
    x: float,
    y: float,
    align: str = "left",
    valign: str = "centre",
    text_size_pt: float = UNIFIED_LEGEND_FONT_SIZE_PT,
    text_color: str = UNIFIED_FOREGROUND_COLOR,
    clip: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "parent": parent,
        "positioning": positioning,
        "x_axis": "x",
        "y_axis": "y",
        "x": float(x),
        "y": float(y),
        "align": align,
        "valign": valign,
        "angle_degrees": 0.0,
        "margin_pt": 0.0,
        "clip": clip,
        "text_size_pt": float(text_size_pt),
        "text_color": text_color,
        "text_hide": False,
        "background_color": "white",
        "background_transparency": 0,
        "background_hide": True,
        "border_color": UNIFIED_FOREGROUND_COLOR,
        "border_width_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "border_style": "solid",
        "border_transparency": 0,
        "border_hide": True,
    }


def _legend_layout(
    payload: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[int, float],
]:
    headings: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    legend_items = [item for item in payload["legend_items"] if isinstance(item, dict)]
    indexed_items = list(enumerate(legend_items, start=1))
    page_width = float(payload["layout"]["page_size_mm"][0])
    plot_panel_width = float(payload["layout"]["plot_panel_size_mm"][0])
    heading_inset_mm = 4.5
    column_count = max(
        int(payload["layout"].get("legend_column_count") or 1),
        1,
    )
    bottoms: dict[int, float] = {}
    for column in range(1, column_count + 1):
        column_items = [
            (index, item)
            for index, item in indexed_items
            if int(item.get("legend_column") or 1) == column
        ]
        if not column_items:
            continue
        grouped_items: list[tuple[str, list[tuple[int, dict[str, Any]]]]] = []
        for index, item in column_items:
            group = str(item.get("legend_group") or "").strip()
            if not grouped_items or grouped_items[-1][0] != group:
                grouped_items.append((group, []))
            grouped_items[-1][1].append((index, item))
        group_count = len(grouped_items)
        group_gap = 0.018
        group_layouts: list[tuple[str, list[tuple[int, dict[str, Any]]], int]] = []
        for group, group_items in grouped_items:
            capacities = {
                max(
                    1,
                    min(
                        int(item.get("legend_items_per_row") or 1),
                        2,
                    ),
                )
                for _, item in group_items
            }
            if len(capacities) != 1:
                raise ValueError(
                    f"Legend group {group!r} has conflicting LegendItemsPerRow values."
                )
            items_per_row = capacities.pop()
            group_layouts.append((group, group_items, items_per_row))
        item_row_count = sum(
            math.ceil(len(group_items) / items_per_row)
            for _, group_items, items_per_row in group_layouts
        )
        slot_count = max(item_row_count + group_count, 1)
        available = 0.88 - 0.10 - group_gap * max(group_count - 1, 0)
        row_step = min(0.078, available / float(slot_count))
        column_offset_mm = PERFORMANCE_REFERENCE_PANEL_WIDTH_MM * float(column - 1)
        heading_x = (
            plot_panel_width + heading_inset_mm + column_offset_mm
        ) / page_width
        marker_x = (
            plot_panel_width + heading_inset_mm + 0.8 + column_offset_mm
        ) / page_width
        text_x = (
            plot_panel_width + heading_inset_mm + 4.0 + column_offset_mm
        ) / page_width
        current_y = 0.88
        paired_slot_offset = _LEGEND_PAIRED_SLOT_OFFSET_MM / page_width
        for group_index, (
            group,
            group_items,
            items_per_row,
        ) in enumerate(group_layouts):
            if group_index:
                current_y -= group_gap
            headings.append(
                {
                    "column": column,
                    "group": group,
                    "x": heading_x,
                    "y": current_y,
                }
            )
            current_y -= row_step
            for row_start in range(0, len(group_items), items_per_row):
                row_items = group_items[row_start : row_start + items_per_row]
                for subcolumn, (index, item) in enumerate(row_items):
                    offset = paired_slot_offset * float(subcolumn)
                    rows.append(
                        {
                            "index": index,
                            "column": column,
                            "subcolumn": subcolumn + 1,
                            "item": item,
                            "marker_x": marker_x + offset,
                            "text_x": text_x + offset,
                            "y": current_y,
                            "row_step": row_step,
                        }
                    )
                current_y -= row_step
        bottoms[column] = current_y
    return headings, rows, bottoms
