"""Closed layout/intent wire schemas; frozen source bindings stay source-owned."""

from typing import Any

from sciplot_core.plot_document.schema import IDENTIFIER, closed

POSITIVE = {"type": "number", "exclusiveMinimum": 0}
NONNEGATIVE = {"type": "number", "minimum": 0}
INDEX = {"type": "integer", "minimum": 0, "maximum": 15}
COUNT = {"type": "integer", "minimum": 1, "maximum": 16}
LABEL = {"type": ["string", "null"], "maxLength": 16}
CROP = {"oneOf": [{"type": "null"}, {"type": "array", "minItems": 4, "maxItems": 4,
    "items": {"type": "number", "minimum": 0, "maximum": 1}}]}


def source_schema() -> dict[str, Any]:
    path = {"type": "string", "minLength": 1, "maxLength": 4096}
    binding = {"type": "object", "minProperties": 1}
    return {"oneOf": [closed({"kind": {"const": kind}, **fields, "binding": binding})
        for kind, fields in (("project", {"project": path, "figure_id": IDENTIFIER}),
                             ("managed", {"project": path, "plot_id": IDENTIFIER}),
                             ("image", {"path": path}))]}


def panel_schema() -> dict[str, Any]:
    return closed({"id": IDENTIFIER, "source": source_schema(), "row": INDEX, "column": INDEX,
        "row_span": COUNT, "column_span": COUNT, "label": LABEL, "crop": CROP})


def document_schema() -> dict[str, Any]:
    return closed({"kind": {"const": "sciplot_panel_assembly"}, "version": {"const": 1},
        "revision": {"type": "integer", "minimum": 0},
        "layout": closed({"rows": COUNT, "columns": COUNT, "width_mm": POSITIVE, "height_mm": POSITIVE,
            "gap_x_mm": NONNEGATIVE, "gap_y_mm": NONNEGATIVE}),
        "panels": {"type": "array", "maxItems": 256, "items": panel_schema()}})


def operations_schema() -> dict[str, Any]:
    branches: dict[str, dict[str, Any]] = {
        "add_panel": {"panel": panel_schema()}, "remove_panel": {"id": IDENTIFIER},
        "move_panel": {"id": IDENTIFIER, "row": INDEX, "column": INDEX, "swap": {"type": "boolean"}},
        "set_span": {"id": IDENTIFIER, "row_span": COUNT, "column_span": COUNT},
        "set_grid": {"rows": COUNT, "columns": COUNT},
        "set_spacing": {"gap_x_mm": NONNEGATIVE, "gap_y_mm": NONNEGATIVE},
        "set_page": {"width_mm": POSITIVE, "height_mm": POSITIVE},
        "set_label": {"id": IDENTIFIER, "label": LABEL}, "set_crop": {"id": IDENTIFIER, "crop": CROP},
        "replace_panel": {"id": IDENTIFIER, "source": source_schema()},
    }
    return {"type": "array", "minItems": 1, "maxItems": 1024, "items": {"oneOf": [
        closed({"op": {"const": name}, **fields}, ["op", *[key for key in fields if key != "swap"]])
        for name, fields in branches.items()]}}
