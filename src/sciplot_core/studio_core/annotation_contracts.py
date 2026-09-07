"""Validate semantic annotations against the current scientific specification."""

from __future__ import annotations

import math
import re
from typing import Any

from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.studio_core.annotation_axes import axis_unit, require_scope

PARENT = "/page1/graph1"
PREFIX = "sciplot_annotation_"


def finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise AnnotationOperationError("invalid_coordinate", f"{name} must be a finite number.", field=name)
    return float(value)


def normalize_position(spec: dict[str, Any], value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not {"mode", "x", "y"} <= set(value) or set(value) - {
        "mode", "x", "y", "x_unit", "y_unit",
    }:
        raise AnnotationOperationError("invalid_coordinate", "Position needs mode, x, y and explicit units for axes mode.")
    mode = value["mode"]
    if mode not in {"axes", "relative"}:
        raise AnnotationOperationError("invalid_coordinate", "Position mode must be axes or relative.")
    result = {"mode": mode}
    for axis in ("x", "y"):
        numeric = finite_number(value[axis], axis)
        if mode == "relative":
            if not 0 <= numeric <= 1 or f"{axis}_unit" in value:
                raise AnnotationOperationError("invalid_coordinate", "Relative coordinates are unitless fractions from 0 to 1.")
        else:
            if value.get(f"{axis}_unit") != axis_unit(spec, axis):
                raise AnnotationOperationError("unit_mismatch", f"Use the exact inspected {axis}-axis unit.")
            bounds = sorted(float(spec["axes"][axis][k]) for k in ("min", "max"))
            if not bounds[0] <= numeric <= bounds[1] or (
                spec["axes"][axis].get("scale") == "log" and numeric <= 0
            ):
                raise AnnotationOperationError("coordinate_out_of_bounds", f"{axis} lies outside the current prepared graph range.")
            result[f"{axis}_unit"] = axis_unit(spec, axis)
        result[axis] = numeric
    return result


def _closed(operation: dict[str, Any], required: set[str], optional: set[str] | frozenset[str] = frozenset()) -> None:
    if not required <= set(operation) or set(operation) - required - optional:
        raise AnnotationOperationError("invalid_operation", "Operation has missing or unadvertised fields.")


def normalize_annotation(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    require_scope(spec)
    identifier = operation.get("id")
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", identifier):
        raise AnnotationOperationError("invalid_annotation_id", "Use an annotation ID of 1–48 ASCII letters, digits or underscores, starting with a letter.")
    kind = operation.get("op")
    base = {"op", "id", "parent_path"}
    if kind == "add_reference_line":
        _closed(operation, base | {"axis", "value", "unit"})
        axis = operation["axis"]
        if axis not in {"x", "y"} or operation["unit"] != axis_unit(spec, axis):
            raise AnnotationOperationError("unit_mismatch", "Use x or y and its exact inspected unit.")
        position = {"mode": "axes", "x_unit": axis_unit(spec, "x"),
                    "y_unit": axis_unit(spec, "y"),
                    **{a: spec["axes"][a]["min"] for a in ("x", "y")}}
        position[axis] = operation["value"]
        value = normalize_position(spec, position)[axis]
        normalized = {**operation, "value": value}
    elif kind == "add_annotation":
        _closed(operation, base | {"text", "position"}, {"arrow_to"})
        if not isinstance(operation["text"], str) or not 1 <= len(operation["text"].strip()) <= 500:
            raise AnnotationOperationError("invalid_annotation_text", "Provide 1–500 characters of literal text.")
        normalized = {**operation, "position": normalize_position(spec, operation["position"])}
        if "arrow_to" in operation:
            target = normalize_position(spec, operation["arrow_to"])
            if target["mode"] != normalized["position"]["mode"]:
                raise AnnotationOperationError("invalid_coordinate", "Text and arrow target must use the same coordinate mode.")
            normalized["arrow_to"] = target
    elif kind == "add_peak_label":
        from sciplot_core.studio_core.peak_evidence import validate_peak_candidate

        _closed(operation, {"op", "id", "candidate"}, {"text", "position"})
        peak = validate_peak_candidate(spec, operation["candidate"])
        target = {"mode": "axes", **{k: peak[k] for k in ("x", "y", "x_unit", "y_unit")}}
        position = operation.get("position", target)
        normalized = normalize_annotation(spec, {
            "op": "add_annotation", "id": identifier, "parent_path": PARENT,
            "text": operation.get("text", f"{peak['x']:g} {peak['x_unit']}".strip()),
            "position": position, **({"arrow_to": target} if position != target else {}),
        })
        normalized["peak_anchor"] = peak
    else:
        raise AnnotationOperationError("unsupported_operation", "Choose an advertised annotation operation.")
    if normalized["parent_path"] != PARENT:
        raise AnnotationOperationError("unsupported_annotation_scope", "Use the inspected /page1/graph1 parent.")
    return normalized


def annotation_records(spec: dict[str, Any]) -> list[dict[str, Any]]:
    payload = spec.get("native_annotations")
    if payload is None:
        return []
    if not isinstance(payload, dict) or set(payload) != {"version", "items"} or payload["version"] != 1:
        raise AnnotationOperationError("invalid_annotation_contract", "Unsupported native annotation contract.")
    records = payload["items"]
    if not isinstance(records, list) or len(records) > 100:
        raise AnnotationOperationError("invalid_annotation_contract", "At most 100 managed annotations are supported.")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise AnnotationOperationError("invalid_annotation_contract", "Annotation records must be objects.")
        ordinary = {k: v for k, v in record.items() if k != "peak_anchor"}
        if normalize_annotation(spec, ordinary) != ordinary or record["id"] in seen:
            raise AnnotationOperationError("invalid_annotation_contract", "Annotation identity or coordinates are invalid.")
        if "peak_anchor" in record:
            from sciplot_core.studio_core.peak_evidence import validate_peak_candidate

            peak = validate_peak_candidate(spec, record["peak_anchor"])
            target = record.get("arrow_to", record["position"])
            if target != {"mode": "axes", **{k: peak[k] for k in ("x", "y", "x_unit", "y_unit")}}:
                raise AnnotationOperationError("anchor_missing", "Peak label is detached from its observed point.")
        seen.add(record["id"])
    return records
