"""Closed public operations for reviewed native annotations and styles."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from sciplot_core.studio_core.document_edit_policy import SAMPLE_STYLE_FIELDS
from sciplot_core.style_values import PHYSICAL_SIZE_UNITS, validate_physical_size

class AnnotationOperationError(ValueError):
    def __init__(self, reason_code: str, message: str, *, field: str = "",
                 issues: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.reason_code, self.field = reason_code, field
        self.issues = issues or []
        self.repair: dict[str, Any] | None = None


def _wire_issue(error: ValidationError, field: str) -> dict[str, Any]:
    issue: dict[str, Any] = {"path": "/" + field, "constraint": error.validator}
    if (error.validator == "additionalProperties" and isinstance(error.instance, dict)
            and isinstance(error.schema, Mapping)):
        allowed = error.schema.get("properties", {})
        issue.update(unsupported=sorted(set(error.instance) - set(allowed))[:16], allowed=sorted(allowed))
    elif (error.validator == "required" and isinstance(error.instance, dict)
          and isinstance(error.validator_value, list)):
        issue["missing"] = [key for key in error.validator_value if key not in error.instance]
    elif error.validator in {"type", "minItems", "maxItems", "minLength", "pattern", "const", "enum", "uniqueItems", "minProperties"}:
        issue["expected"] = error.validator_value
    return issue


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
        raise AnnotationOperationError("invalid_operations", "Provide 1–100 explicit operations.", field="operations",
            issues=[{"path": "/operations", "constraint": "array_size", "minimum": 1, "maximum": 100}])
    try:
        json.dumps(operations, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AnnotationOperationError("invalid_operations", "Operations must contain finite JSON values.", field="operations",
            issues=[{"path": "/operations", "constraint": "finite_json"}]) from exc
    validators = _operation_validators()
    for index, operation in enumerate(operations):
        location = f"operations/{index}"
        if not isinstance(operation, dict):
            raise AnnotationOperationError("invalid_operation", f"{location} must be an object.", field=location,
                issues=[{"path": "/" + location, "constraint": "type", "expected": "object"}])
        kind = operation.get("op")
        if not isinstance(kind, str) or kind not in validators:
            raise AnnotationOperationError("unsupported_operation", f"{location}/op is unsupported; use the advertised operations.", field=location + "/op",
                issues=[{"path": "/" + location + "/op", "constraint": "enum", "allowed": sorted(validators)}])
        error = next(validators[kind].iter_errors(operation), None)
        if error is not None:
            field = "/".join([location, *map(str, error.absolute_path)])
            raise AnnotationOperationError("invalid_operation", f"{field}: {error.message[:500]}", field=field,
                                           issues=[_wire_issue(error, field)])
        if kind == "set_sample_style" and "width" in operation["style"]:
            field = location + "/style/width"
            try:
                validate_physical_size(operation["style"]["width"])
            except ValueError as exc:
                raise AnnotationOperationError("invalid_sample_style", str(exc), field=field,
                    issues=[{"path": "/" + field, "constraint": "positive_physical_size",
                             "allowed_units": list(PHYSICAL_SIZE_UNITS), "example": "0.7pt"}]) from exc


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
        "style": {**object_schema({name: ({**string, "description":
                    "Positive physical line width with pt, mm, cm, in or inch; for example 0.7pt. No implicit unit."}
                    if name == "width" else string) for name in SAMPLE_STYLE_FIELDS}, []),
                  "minProperties": 1},
    }, ["samples", "style"])
    add("apply_sample_style_preset", {
        "preset": {"type": "string", "minLength": 1}, "expected_preset_sha256": digest,
        "samples": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                    "description": "Optional exact target subset. Default requires preset coverage for every ordinary target sample; no position matching."},
    }, ["preset", "expected_preset_sha256"])
    add("set_axis_range", {
        "axis": {"enum": ["x", "y"]}, "unit": string,
        "expected_min": number, "expected_max": number,
        "min": number, "max": number,
        "ticks": {"type": "array", "minItems": 2, "maxItems": 32,
                  "uniqueItems": True, "items": number},
        "allow_clipping": {"type": "boolean"},
    }, ["axis", "unit", "expected_min", "expected_max", "min", "max",
        "ticks", "allow_clipping"])
    add("set_axis_limits", {
        "axis": {"enum": ["x", "y"]}, "unit": string,
        "expected_min": number, "expected_max": number, "min": number, "max": number,
        "allow_clipping": {"const": False},
    }, ["axis", "unit", "expected_min", "expected_max", "min", "max", "allow_clipping"])
    add("set_legend_visibility", {"expected_visible": {"type": "boolean"},
                                   "visible": {"type": "boolean"}},
        ["expected_visible", "visible"])
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
        "source_revision": "Source-update previews retain compatible fixed annotations and require explicit choices for observed peak anchors, including moved, missing and ambiguous candidates.",
        "discovery": "inspect_annotation_state returns current annotations, exact units and graph bounds.",
    }
