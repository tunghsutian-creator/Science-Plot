"""Append capability consumes the common exact original-coordinate evidence."""

from typing import Any

from .errors import EngineError
from .original_coordinate import coordinate_origins


def coordinate_origin(document: dict[str, Any], dataset: str, column: str,
                      unit: str, *, quantity: str | None = None,
                      column_facts: dict[str, dict[str, Any]] | None = None,
                      explicit_quantity_binding: bool = False) -> tuple[dict[str, Any], int, int, int]:
    """Keep the existing finite append contract and duplicate-measurement identity."""
    try:
        origins = coordinate_origins(document, dataset, column, unit, quantity=quantity, column_facts=column_facts,
                                     explicit_quantity_binding=explicit_quantity_binding)
    except EngineError as error:
        if error.reason_code != "managed_unit_lineage_unsupported":
            raise
        origins = []
    if len(origins) != 1 or set(origins[0][5]) - {"select", "row_slice", "rename", "convert_unit"}:
        raise EngineError("managed_append_view_unsupported", "The target coordinate must retain an exact original column and row selection through supported unit relations.")
    source, index, start, end, _, _ = origins[0]
    return source, index, start, end
