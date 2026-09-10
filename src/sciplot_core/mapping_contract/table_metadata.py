"""Closed wire contract for source-bound scientific metadata declarations."""

from typing import Any

from jsonschema import Draft202012Validator


def metadata_confirmations_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": "\\S"}
    index = {"type": "integer", "minimum": 0}

    def evidence(kind: str, fields: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": False,
                "properties": {"kind": {"const": kind}, **fields},
                "required": ["kind", *fields]}

    return {"type": "array", "maxItems": 256, "items": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "sheet": {"type": ["string", "null"]}, "column_index": index,
            "field": {"enum": ["quantity", "unit", "sample"]}, "value": text,
            "evidence": {"oneOf": [
                evidence("source_cell", {"sheet": {"type": ["string", "null"]},
                    "row_index": index, "column_index": index, "text": text}),
                evidence("external_reference", {"uri": text, "locator": text, "excerpt": text}),
                evidence("user_statement", {"asserted_by": text, "statement": text}),
            ]},
        }, "required": ["source_sha256", "sheet", "column_index", "field", "value", "evidence"],
    }}


def validate_metadata_confirmations(value: Any) -> None:
    errors = list(Draft202012Validator(metadata_confirmations_schema()).iter_errors(value))
    if errors:
        error = errors[0]
        raise ValueError(f"Invalid metadata confirmation at {list(error.absolute_path)}: {error.message}")
