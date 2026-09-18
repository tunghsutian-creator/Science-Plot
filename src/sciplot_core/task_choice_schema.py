"""Wire schemas for source-bound table, column and annotation revision choices."""

from typing import Any
from sciplot_core.mapping_contract.table_metadata import metadata_confirmations_schema


def metadata_response_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "properties": {
                "expected_question_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "metadata_confirmations": metadata_confirmations_schema()},
            "required": ["expected_question_id", "metadata_confirmations"]}


def table_region_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "properties": {
                "expected_question_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "sheet": {"type": ["string", "null"]},
                **{key: {"type": "integer", "minimum": 0} for key in
                   ("row_start", "row_end", "column_start", "column_end")}},
            "required": ["expected_question_id", "sheet", "row_start", "row_end", "column_start", "column_end"]}


def column_mapping_schema() -> dict[str, Any]:
    pair = {"type": "object", "additionalProperties": False,
            "properties": {
                **{key: {"type": "integer", "minimum": 0} for key in ("x_column", "y_column")},
                "label": {"type": "string", "minLength": 1, "maxLength": 160, "pattern": "\\S",
                          "description": "Explicit display label; original sample and column evidence remain bound to the source."},
                "table_selection": table_selection_schema(),
                "metadata_confirmations": metadata_confirmations_schema()},
            "required": ["x_column", "y_column"]}
    return {"oneOf": [pair, {"type": "object", "additionalProperties": False,
                             "properties": {"pairs": {"type": "array", "minItems": 1, "maxItems": 32, "items": pair}},
                             "required": ["pairs"]}]}


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


def table_response_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "properties": {
                "expected_question_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "table_selection": table_selection_schema()},
            "required": ["expected_question_id", "table_selection"]}


def initial_mapping_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "description": "Explicit choices already reviewed by the caller, bound to the original file bytes. Uses the same table, metadata and pair validation as interactive answers; never accepts a visual edit preview.",
            "properties": {
                "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "table_selection": table_selection_schema(),
                "metadata_confirmations": metadata_confirmations_schema(),
                "column_mapping": column_mapping_schema()},
            "required": ["source_sha256", "table_selection", "column_mapping"]}


def mapping_candidate_response_schema() -> dict[str, Any]:
    digest = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    return {"type": "object", "additionalProperties": False,
            "description": "Select a reviewed source-bound mapping candidate; optionally select/order its pair indices. No metadata transcription required.",
            "properties": {"expected_question_id": digest, "mapping_candidate_id": digest,
                           "pair_indices": {"type": "array", "minItems": 1, "maxItems": 32,
                                            "uniqueItems": True, "items": {"type": "integer", "minimum": 0}}},
            "required": ["expected_question_id", "mapping_candidate_id"]}


def mapping_response_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "description": "Correct this task in one reply: original region, metadata, XY pairs and labels. No rewritten arrays or new project required.",
            "properties": {
                "expected_question_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "rule_id": {"type": "string", "minLength": 1},
                "template": {"type": "string", "minLength": 1},
                "mapping": initial_mapping_schema()},
            "required": ["expected_question_id", "mapping"]}


def annotation_response_schema() -> dict[str, Any]:
    common = {"figure_id": {"type": "string", "minLength": 1}, "id": {"type": "string", "minLength": 1}}
    variants = []
    for action, extra in (
        ("keep", {}), ("remove", {}),
        ("rebind", {"candidate_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "text": {"type": "string", "minLength": 1, "maxLength": 500}}),
        ("replace", {"replacement": {"type": "object", "description": "An advertised add_annotation or add_reference_line with the same annotation id."}}),
    ):
        variants.append({"type": "object", "additionalProperties": False,
            "properties": {**common, "action": {"const": action}, **extra,
                **({"position": {"type": "object", "description": "Optional explicit label position using the ordinary annotation coordinate contract."}} if action == "rebind" else {})},
            "required": [*common, "action", *extra]})
    return {"type": "object", "additionalProperties": False,
        "properties": {"expected_revision_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "annotation_choices": {"type": "array", "maxItems": 100, "items": {"oneOf": variants}}},
        "required": ["expected_revision_id", "annotation_choices"]}
