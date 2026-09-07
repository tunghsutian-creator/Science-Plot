"""Closed public operations for reviewed native annotations and styles."""

from __future__ import annotations

from typing import Any


class AnnotationOperationError(ValueError):
    def __init__(self, reason_code: str, message: str, *, field: str = "") -> None:
        super().__init__(message)
        self.reason_code, self.field = reason_code, field


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


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
