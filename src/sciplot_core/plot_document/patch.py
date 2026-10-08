"""Atomic semantic patches with engine-computed risk and exact stable targets."""

from copy import deepcopy
from typing import Any
from sciplot_core.style_values import normalize_physical_size

from .errors import fail
from .model import seal_document, validate_document
from .properties import effective_risk, maximum_risk, validate_value
from .schema import patch_schema
from .validation import validate_wire


def validate_patch(patch: Any) -> dict[str, Any]:
    validate_wire(patch, patch_schema(), code="document_invalid_patch")
    assert isinstance(patch, dict)
    return deepcopy(patch)


def apply_patch(document: Any, patch: Any) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Validate every target before returning changed state. Revision belongs to storage."""
    result = validate_document(document)
    patch = validate_patch(patch)
    if patch["plot_id"] != result["plot_id"]:
        fail("document_identity_conflict", "The patch belongs to a different plot.", "/plot_id", "identity",
             expected=result["plot_id"])
    if patch["base_revision"] != result["revision"]:
        fail("document_revision_conflict", "Read the current revision before changing this document.",
             "/base_revision", "revision", expected=result["revision"])
    objects = result["presentation"]["objects"]
    touched: set[tuple[str, str]] = set()
    diff: list[dict[str, Any]] = []
    risk = "presentation"
    for index, change in enumerate(patch["changes"]):
        path = f"/changes/{index}"
        prop, value = change["property"], change["value"]
        if prop.startswith(("mapping.", "mappings.", "data.", "transform.", "transforms.", "scientific.")) or prop in {"axis.scale", "axis.unit", "x", "y"}:
            fail("document_scientific_edit_unsupported", "This patch executor cannot change scientific bindings.",
                 path + "/property", "scientific_executor_required")
        for identifier in change["target"]:
            if identifier not in objects:
                fail("document_unknown_target", "Select an exact semantic object ID.", path + "/target",
                     "object_id", allowed=list(objects)[:100])
            obj = objects[identifier]
            if prop not in obj["capabilities"]:
                fail("document_unsupported_property", "This object does not advertise that property.",
                     path + "/property", "capability", target=identifier, allowed=sorted(obj["capabilities"]))
            if (identifier, prop) in touched:
                fail("document_duplicate_change", "Set each target/property once per atomic patch.",
                     path, "unique_target_property", target=identifier, property=prop)
            touched.add((identifier, prop))
            validate_value(prop, value, obj["capabilities"][prop], path + "/value")
            if obj["capabilities"][prop]["type"] == "physical_size" and value is not None:
                value = normalize_physical_size(value)
            before = obj["properties"][prop]
            if type(before) is type(value) and before == value:
                continue
            item_risk = effective_risk(obj, prop, value)
            if item_risk == "scientific":
                fail("document_scientific_edit_unsupported", "This property encodes scientific meaning.",
                     path + "/property", "scientific_executor_required", target=identifier)
            risk = maximum_risk(risk, item_risk)
            diff.append({"target": identifier, "property": prop, "before": deepcopy(before),
                         "after": deepcopy(value), "risk": item_risk})
            obj["properties"][prop] = deepcopy(value)
    return seal_document(result), diff, risk
