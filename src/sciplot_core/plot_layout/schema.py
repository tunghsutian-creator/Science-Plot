"""Physical layout contracts without renderer coordinates or object paths."""

from typing import Any

from sciplot_core.plot_document.schema import IDENTIFIER, closed

NONNEGATIVE = {"type": "number", "minimum": 0}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
RECT = {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}}
PAIR = {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number"}}


def layout_schema() -> dict[str, Any]:
    return closed({
        "width_mm": POSITIVE,
        "height_mm": {"oneOf": [POSITIVE, {"const": "auto"}]},
        "gap_x_mm": NONNEGATIVE, "gap_y_mm": NONNEGATIVE,
        "outer_margins_mm": closed({side: NONNEGATIVE for side in ("left", "right", "top", "bottom")}),
        "panel_min_height_mm": POSITIVE, "panel_label_height_mm": NONNEGATIVE,
    })


def resolved_layout_schema() -> dict[str, Any]:
    panel = closed({
        "view_id": IDENTIFIER, "row": {"type": "integer", "minimum": 0},
        "column": {"type": "integer", "minimum": 0}, "cell_mm": RECT, "plot_mm": RECT,
        "panel_label_mm": {"oneOf": [PAIR, {"type": "null"}]},
        "suppressed_axis_ids": {"type": "array", "items": IDENTIFIER, "uniqueItems": True},
    })
    return closed({
        "width_mm": POSITIVE, "height_mm": POSITIVE,
        "panels": {"type": "array", "minItems": 1, "items": panel},
        "figure_guide_bounds_mm": {"oneOf": [RECT, {"type": "null"}]},
    })
