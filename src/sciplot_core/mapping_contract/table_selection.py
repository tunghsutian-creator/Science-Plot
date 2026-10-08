"""Pure original-table region schema shared by binding and task transports."""

from typing import Any


def table_selection_schema() -> dict[str, Any]:
    row = {"type": "integer", "minimum": 0}
    return {"type": "object", "additionalProperties": False,
            "description": "Original worksheet and this pair's own data rows (end exclusive). Omission on a pair inherits the current table selection.",
            "properties": {"sheet": {"type": ["string", "null"]},
                "header_rows": {"type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True, "items": row},
                "data_start_row": row, "data_end_row": row,
                "unit_row": {"type": ["integer", "null"], "minimum": 0},
                "sample_row": {"type": ["integer", "null"], "minimum": 0},
                "expand_merged_metadata": {"type": "boolean", "description": "Explicitly associate merged XLSX metadata with its original anchor; measurement cells are never expanded."}},
            "required": ["sheet", "header_rows", "data_start_row", "data_end_row"]}
