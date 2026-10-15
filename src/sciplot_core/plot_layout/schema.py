"""Physical layout contracts without renderer coordinates or object paths."""

from typing import Any

from sciplot_core.plot_document.schema import IDENTIFIER, closed

NONNEGATIVE = {"type": "number", "minimum": 0}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
RECT = {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}}
PAIR = {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number"}}


def grid_schema() -> dict[str, Any]:
    """Additive grid capabilities; omission retains the original full unit grid."""
    integer = {"type": "integer", "minimum": 1, "maximum": 16}
    cell = closed({"view_id": IDENTIFIER, "row": {"type": "integer", "minimum": 0},
        "column": {"type": "integer", "minimum": 0}, "row_span": integer, "column_span": integer})
    fields = {"rows": integer, "columns": integer,
        "cells": {"type": "array", "items": cell},
        "row_weights": {"type": "array", "items": POSITIVE},
        "column_weights": {"type": "array", "items": POSITIVE},
        "capabilities": {"type": "array", "uniqueItems": True, "items": {"enum": ["sparse", "spans"]}}}
    return closed(fields, [key for key in fields if key != "capabilities"])


def layout_schema() -> dict[str, Any]:
    return closed({
        "width_mm": POSITIVE,
        "height_mm": {"oneOf": [POSITIVE, {"const": "auto"}]},
        "gap_x_mm": NONNEGATIVE, "gap_y_mm": NONNEGATIVE,
        "outer_margins_mm": closed({side: NONNEGATIVE for side in ("left", "right", "top", "bottom")}),
        "panel_min_height_mm": POSITIVE, "panel_label_height_mm": NONNEGATIVE,
    })


def resolved_layout_schema(*, allow_empty: bool = False) -> dict[str, Any]:
    panel = closed({
        "view_id": IDENTIFIER, "row": {"type": "integer", "minimum": 0},
        "column": {"type": "integer", "minimum": 0}, "cell_mm": RECT, "plot_mm": RECT,
        "panel_label_mm": {"oneOf": [PAIR, {"type": "null"}]},
        "suppressed_axis_ids": {"type": "array", "items": IDENTIFIER, "uniqueItems": True},
    })
    return closed({
        "width_mm": POSITIVE, "height_mm": POSITIVE,
        "panels": {"type": "array", "minItems": 0 if allow_empty else 1, "items": panel},
        "figure_guide_bounds_mm": {"oneOf": [RECT, {"type": "null"}]},
    })
