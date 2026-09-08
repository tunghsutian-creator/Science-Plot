"""Closed public operations for reviewed native annotations and styles."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from sciplot_core.studio_core.document_edit_policy import SAMPLE_STYLE_FIELDS

class AnnotationOperationError(ValueError):
    def __init__(self, reason_code: str, message: str, *, field: str = "") -> None:
        super().__init__(message)
        self.reason_code, self.field = reason_code, field


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


@lru_cache(maxsize=1)
def _operation_validators() -> dict[str, Draft202012Validator]:
    variants = annotation_operation_capabilities()["operations_schema"]["items"]["oneOf"]
    return {schema["properties"]["op"]["const"]: Draft202012Validator(schema)
            for schema in variants}


def validate_operation_batch(operations: Any) -> None:
    """Check the public wire shape before project I/O or pending-preview replacement.

    This does not validate native settings, units, bindings or scientific meaning;
    those still require the existing project/native owners and current evidence.
    """
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise AnnotationOperationError("invalid_operations", "Provide 1–100 explicit operations.")
    try:
        json.dumps(operations, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AnnotationOperationError("invalid_operations", "Operations must contain finite JSON values.") from exc
    validators = _operation_validators()
    for index, operation in enumerate(operations):
        location = f"operations/{index}"
        if not isinstance(operation, dict):
            raise AnnotationOperationError("invalid_operation", f"{location} must be an object.", field=location)
        kind = operation.get("op")
        if not isinstance(kind, str) or kind not in validators:
            raise AnnotationOperationError("unsupported_operation", f"{location}/op is unsupported; use the advertised operations.", field=location + "/op")
        error = next(validators[kind].iter_errors(operation), None)
        if error is not None:
            field = "/".join([location, *map(str, error.absolute_path)])
            raise AnnotationOperationError("invalid_operation", f"{field}: {error.message[:500]}", field=field)


def annotation_operation_capabilities() -> dict[str, Any]:
    string = {"type": "string"}
    number = {"type": "number"}
    identifier = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,47}$"}
    position = {"oneOf": [
        object_schema({"mode": {"const": "axes"}, "x": number, "y": number,
                       "x_unit": string, "y_unit": string}, ["mode", "x", "y", "x_unit", "y_unit"]),
        object_schema({"mode": {"const": "relative"},
                       "x": {"type": "number", "minimum": 0, "maximum": 1},
                       "y": {"type": "number", "minimum": 0, "maximum": 1}}, ["mode", "x", "y"]),
    ]}
    digest = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    peak_fields = {
        "kind": {"const": "sciplot_observed_peak"}, "version": {"const": 1},
        "object_path": string, "sample": string, "series_signature": digest,
        "window": object_schema({"min": number, "max": number, "unit": string}, ["min", "max", "unit"]),
        "polarity": {"enum": ["maximum", "minimum"]},
        "method": {"const": "strict_discrete_interior_extremum_v1"},
        "point_index": {"type": "integer", "minimum": 1},
        "x": number, "y": number, "x_unit": string, "y_unit": string,
        "candidate_id": digest,
    }
    peak_evidence = object_schema(peak_fields, list(peak_fields))
    bound_peak = {**peak_fields, "document_sha256": digest, "figure_id": string}
    common = {"id": identifier, "parent_path": {"const": "/page1/graph1"}}
    operations: list[dict[str, Any]] = []
    def add(name: str, properties: dict[str, Any], required: list[str]) -> None:
        operations.append(object_schema(
            {"op": {"const": name}, **properties}, ["op", *required]))
    add("set_style", {"object_path": string, "setting_path": string,
                      "expected_value": {}, "value": {}},
        ["object_path", "setting_path", "expected_value", "value"])
    add("add_reference_line", {**common, "axis": {"enum": ["x", "y"]},
                               "value": number, "unit": string},
        ["id", "parent_path", "axis", "value", "unit"])
    add("add_annotation", {**common, "text": {"type": "string", "minLength": 1,
                                               "maxLength": 500},
                           "position": position,
                           "arrow_to": position},
        ["id", "parent_path", "text", "position"])
    add("add_peak_label", {"id": identifier, "candidate": object_schema(bound_peak, list(bound_peak)),
                           "text": string, "position": position},
        ["id", "candidate"])
    record_annotation = {**operations[2], "properties": {**operations[2]["properties"], "peak_anchor": peak_evidence}}
    record_schema = {"oneOf": [operations[1], record_annotation]}
    add("remove_annotation", {"id": identifier, "expected_annotation": record_schema},
        ["id", "expected_annotation"])
    add("update_annotation", {"id": identifier, "expected_annotation": record_schema,
                               "replacement": {"oneOf": operations[1:4]}},
        ["id", "expected_annotation", "replacement"])
    add("set_sample_style", {
        "samples": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                    "description": "Exact unique labels from the selected figure's sample_styles inventory."},
        "style": {**object_schema({name: string for name in SAMPLE_STYLE_FIELDS}, []),
                  "minProperties": 1},
    }, ["samples", "style"])
    add("apply_sample_style_preset", {
        "preset": {"type": "string", "minLength": 1}, "expected_preset_sha256": digest,
        "samples": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                    "description": "Optional exact target subset. Default requires preset coverage for every ordinary target sample; no position matching."},
    }, ["preset", "expected_preset_sha256"])
    return {
        "kind": "sciplot_annotation_operations", "version": 1,
        "operations_schema": {"type": "array", "minItems": 1, "maxItems": 100,
                              "items": {"oneOf": operations}},
        "coordinate_modes": {
            "axes": "Exact displayed axis units; no conversion or expressions.",
            "relative": "Fractions from 0 to 1 of the graph rectangle.",
        },
        "identity": "Saved document SHA and inspected paths; annotation IDs are unique per figure.",
        "scope": "Cartesian ordinary curves; native graph x/y axes only.",
        "peak_method": "Unsmoothed strict discrete interior extrema in an explicit x window; no assignments.",
        "source_revision": "Remove managed annotations before changing source data; anchors never silently rebind.",
        "discovery": "inspect_annotation_state returns current annotations, exact units and graph bounds.",
    }
