"""Grid membership and explicit sparse/span capability validation."""

from typing import Any

from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.validation import validate_wire

from .schema import grid_schema


def validate_grid_cells(layout: dict[str, Any], view_ids: list[str]) -> None:
    schema = grid_schema()
    validate_wire({key: value for key, value in layout.items() if key in schema["properties"]},
                  schema, code="figure_layout_grid")
    rows, columns = layout["rows"], layout["columns"]
    if type(rows) is not int or type(columns) is not int:
        fail("figure_layout_grid", "Grid dimensions must be integers without coercion.", "/composition", "integer_grid")
    capabilities = layout.get("capabilities", [])
    occupied: set[tuple[int, int]] = set()
    ids = []
    for cell in layout["cells"]:
        row, column = cell["row"], cell["column"]
        row_span, column_span = cell["row_span"], cell["column_span"]
        if any(type(value) is not int for value in (row, column, row_span, column_span)):
            fail("figure_layout_cell", "Cell positions and spans must be integers without coercion.",
                 "/composition/cells", "integer_cell")
        if (row_span != 1 or column_span != 1) and "spans" not in capabilities:
            fail("figure_layout_span_unsupported", "Spanning panels require the explicit spans capability.",
                 "/composition/cells", "capability")
        if row + row_span > rows or column + column_span > columns:
            fail("figure_layout_cell", "Every panel span must stay inside the declared grid.",
                 "/composition/cells", "cell_membership")
        positions = {(r, c) for r in range(row, row + row_span) for c in range(column, column + column_span)}
        if occupied & positions:
            fail("figure_layout_cell", "Panel spans cannot overlap occupied grid cells.",
                 "/composition/cells", "cell_membership")
        occupied.update(positions)
        ids.append(cell["view_id"])
    if sorted(ids) != sorted(view_ids) or len(set(ids)) != len(ids):
        fail("figure_layout_view_membership", "Every view must occur in exactly one cell.",
             "/composition/cells", "view_membership")
    if len(occupied) != rows * columns and "sparse" not in capabilities:
        fail("figure_layout_empty_cell", "Empty cells require the explicit sparse capability.",
             "/composition/cells", "full_grid")
