"""Renderer-independent column snapshots and their exact scientific provenance."""

from copy import deepcopy
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.mapping_contract.table_selection import table_selection_schema
from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.schema import DIGEST, IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire


def dataset_schema() -> dict[str, Any]:
    column = closed({"label": {"type": "string"}, "unit": {"type": "string"},
                     "values": {"type": "array", "items": {"type": ["number", "null"]}}})
    source = closed({"source_id": IDENTIFIER, "sha256": DIGEST, "table_selection": table_selection_schema(),
                     "column_indices": {"type": "object", "propertyNames": IDENTIFIER,
                                        "additionalProperties": {"type": "integer", "minimum": 0}},
                     "rows": {"type": "array", "items": {"type": "integer", "minimum": 0}}})
    step = closed({"node_id": IDENTIFIER, "cache_key": DIGEST, "executor_hash": DIGEST,
                   "input_hashes": {"type": "array", "items": DIGEST}, "output_hash": DIGEST,
                   "parameters": {"type": "object"}, "details": {"type": "object"}})
    return closed({"id": IDENTIFIER, "columns": {"type": "object", "minProperties": 1,
                   "propertyNames": IDENTIFIER, "additionalProperties": column},
                   "provenance": closed({"sources": {"type": "array", "minItems": 1, "items": source},
                                         "transforms": {"type": "array", "items": step}})})


def validate_dataset(value: Any) -> dict[str, Any]:
    validate_wire(value, dataset_schema(), code="transform_dataset_invalid")
    assert isinstance(value, dict)
    counts = {len(column["values"]) for column in value["columns"].values()}
    if len(counts) != 1:
        fail("transform_ragged_dataset", "Columns in one table snapshot must retain the same original row region.",
             "/columns", "equal_row_count")
    for source in value["provenance"]["sources"]:
        rows = source["rows"]
        if rows != sorted(set(rows)):
            fail("transform_source_order", "Original row references must be unique and increasing.",
                 "/provenance/sources/rows", "original_row_order")
    return deepcopy(value)


def dataset_hash(value: dict[str, Any]) -> str:
    """Include provenance; identical values from different raw inputs are distinct."""
    return canonical_json_sha256(validate_dataset(value), allow_nan=False)


def numeric_hash(value: dict[str, Any]) -> str:
    return canonical_json_sha256(value["columns"], allow_nan=False)
