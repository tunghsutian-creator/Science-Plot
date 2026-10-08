"""Deterministic physical grid allocation with decoration-aware plot alignment."""

from __future__ import annotations

import math
from typing import Any

from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.validation import validate_wire

from .decorations import decoration_budget, guide_size, suppression
from .schema import layout_schema, resolved_layout_schema


def _allocate(total: float, weights: list[float]) -> list[float]:
    if total <= 0 or not weights or any(weight <= 0 for weight in weights):
        fail("figure_layout_no_space", "Layout constraints leave no positive panel area.", "/layout", "positive_dimensions")
    return [total * weight / sum(weights) for weight in weights]


def _validate_grid(layout: dict[str, Any], views: list[dict[str, Any]]) -> None:
    validate_wire({key: layout[key] for key in layout_schema()["properties"]}, layout_schema(), code="figure_layout_invalid")
    rows, columns = layout["rows"], layout["columns"]
    if type(rows) is not int or type(columns) is not int or rows < 1 or columns < 1:
        fail("figure_layout_grid", "Grid dimensions must be positive integers.", "/composition", "positive_grid")
    if len(layout["row_weights"]) != rows or len(layout["column_weights"]) != columns:
        fail("figure_layout_weights", "Each grid row and column needs one positive weight.", "/composition", "weight_count")
    if any(type(weight) not in {int, float} or not math.isfinite(weight) or weight <= 0
           for weight in [*layout["row_weights"], *layout["column_weights"]]):
        fail("figure_layout_weights", "Grid weights must be finite positive numbers.", "/composition", "positive_weights")
    occupied = set()
    ids = []
    for cell in layout["cells"]:
        position = (cell["row"], cell["column"])
        if cell.get("row_span", 1) != 1 or cell.get("column_span", 1) != 1:
            fail("figure_layout_span_unsupported", "Spanning panels are not supported by this layout version.", "/composition/cells", "capability")
        if position in occupied or not 0 <= position[0] < rows or not 0 <= position[1] < columns:
            fail("figure_layout_cell", "Each view requires a unique in-grid cell.", "/composition/cells", "cell_membership")
        occupied.add(position)
        ids.append(cell["view_id"])
    if sorted(ids) != sorted(view["id"] for view in views) or len(set(ids)) != len(ids):
        fail("figure_layout_view_membership", "Every view must occur in exactly one cell.", "/composition/cells", "view_membership")
    if len(occupied) != rows * columns:
        fail("figure_layout_empty_cell", "This grid version requires all cells to contain a view.", "/composition/cells", "full_grid")


def _figure_guide(guides: list[dict[str, Any]]) -> dict[str, Any] | None:
    visible = [guide for guide in guides if guide["visible"] and guide.get("view_id") is None]
    if len(visible) > 1:
        fail("figure_layout_guide_capability", "This layout version supports one figure-level legend.", "/guides", "capability")
    return visible[0] if visible else None


def solve_layout(layout: dict[str, Any], views: list[dict[str, Any]], axes: list[dict[str, Any]],
                 guides: list[dict[str, Any]] | None = None,
                 annotations: list[dict[str, Any]] | None = None,
                 panel_margins_mm: dict[str, float] | None = None) -> dict[str, Any]:
    """Resolve millimetres, top-left origin; no native coordinates are accepted."""
    del annotations  # Annotation scientific anchors are resolved by the semantic compiler.
    _validate_grid(layout, views)
    rows, columns = layout["rows"], layout["columns"]
    hidden = suppression(layout, axes)
    by_id = {view["id"]: view for view in views}
    budgets = {cell["view_id"]: decoration_budget(
        [axis for axis in axes if axis["view_id"] == cell["view_id"]], hidden,
        panel_label_height_mm=float(layout["panel_label_height_mm"]),
        has_label=bool(by_id[cell["view_id"]].get("panel_label"))) for cell in layout["cells"]}
    if panel_margins_mm is not None:
        # House geometry is fixed. Native text QA rejects overflow; no auto-resize.
        budgets = {view_id: {**panel_margins_mm, "min_width": 1.0, "min_height": 1.0}
                   for view_id in budgets}
    # Shared grid edges use the largest decoration in that row/column.
    horizontal = [{side: max(budgets[cell["view_id"]][side] for cell in layout["cells"] if cell["column"] == column)
                   for side in ("left", "right")} for column in range(columns)]
    vertical = [{side: max(budgets[cell["view_id"]][side] for cell in layout["cells"] if cell["row"] == row)
                 for side in ("top", "bottom")} for row in range(rows)]
    margin = {key: float(value) for key, value in layout["outer_margins_mm"].items()}
    guide = _figure_guide(guides or [])
    guide_width, guide_height = guide_size(guide) if guide else (0.0, 0.0)
    guide_side = str(guide["location"]) if guide else ""
    if guide and guide_side not in {"top", "bottom", "left", "right"}:
        fail("figure_layout_guide_location", "Figure legends need a figure-edge location.", "/guides", "guide_scope")
    if guide:
        margin[guide_side] += (guide_height if guide_side in {"top", "bottom"} else guide_width) + 2.0
    width = float(layout["width_mm"])
    x_gap, y_gap = float(layout["gap_x_mm"]), float(layout["gap_y_mm"])
    widths = _allocate(width - margin["left"] - margin["right"] - (columns - 1) * x_gap,
                       layout["column_weights"])
    minimum_heights = [max(float(layout["panel_min_height_mm"]),
        max(budgets[cell["view_id"]]["min_height"] + vertical[row]["top"] + vertical[row]["bottom"]
            for cell in layout["cells"] if cell["row"] == row)) for row in range(rows)]
    if layout["height_mm"] == "auto":
        # Grow the grid without violating row ratios or minimum decoration sizes.
        unit = max(minimum_heights[row] / layout["row_weights"][row] for row in range(rows))
        heights = [unit * weight for weight in layout["row_weights"]]
        height = sum(heights) + margin["top"] + margin["bottom"] + (rows - 1) * y_gap
    else:
        height = float(layout["height_mm"])
        heights = _allocate(height - margin["top"] - margin["bottom"] - (rows - 1) * y_gap, layout["row_weights"])
    panels = []
    for cell in layout["cells"]:
        row, column, view_id = cell["row"], cell["column"], cell["view_id"]
        x = margin["left"] + sum(widths[:column]) + column * x_gap
        y = margin["top"] + sum(heights[:row]) + row * y_gap
        left, right = horizontal[column]["left"], horizontal[column]["right"]
        top, bottom = vertical[row]["top"], vertical[row]["bottom"]
        plot = [x + left, y + top, widths[column] - left - right, heights[row] - top - bottom]
        if plot[2] < budgets[view_id]["min_width"] or plot[3] < budgets[view_id]["min_height"]:
            fail("figure_layout_no_space", "Figure dimensions cannot contain resolved axis decorations and positive plot areas.",
                 "/layout", "decoration_space", view_id=view_id,
                 available_plot_mm=plot[2:], minimum_plot_mm=[budgets[view_id]["min_width"], budgets[view_id]["min_height"]])
        label_height = top if panel_margins_mm is not None else float(layout["panel_label_height_mm"])
        label = [x + 1.0, y + label_height * 0.5] if by_id[view_id].get("panel_label") else None
        panels.append({"view_id": view_id, "row": row, "column": column,
            "cell_mm": [x, y, widths[column], heights[row]], "plot_mm": plot, "panel_label_mm": label,
            "suppressed_axis_ids": sorted(axis["id"] for axis in axes if axis["view_id"] == view_id and axis["id"] in hidden)})
    guide_bounds = None
    if guide:
        original = layout["outer_margins_mm"]
        guide_bounds = {
            "top": [(width - guide_width) / 2, original["top"], guide_width, guide_height],
            "bottom": [(width - guide_width) / 2, height - original["bottom"] - guide_height, guide_width, guide_height],
            "left": [original["left"], (height - guide_height) / 2, guide_width, guide_height],
            "right": [width - original["right"] - guide_width, (height - guide_height) / 2, guide_width, guide_height],
        }[guide_side]
        if guide_width > width - original["left"] - original["right"] or guide_height > height - original["top"] - original["bottom"]:
            fail("figure_layout_legend_no_space", "The figure legend exceeds its available physical bounds.", "/guides", "legend_space")
    result = {"width_mm": width, "height_mm": height, "panels": panels, "figure_guide_bounds_mm": guide_bounds}
    validate_wire(result, resolved_layout_schema(), code="figure_layout_invalid")
    return result
