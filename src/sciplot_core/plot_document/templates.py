"""Explicit template, data-binding and theme composition without scientific inference."""

from copy import deepcopy
from typing import Any

from sciplot_core.mapping_contract.table_metadata import metadata_confirmations_schema
from sciplot_core.mapping_contract.table_selection import table_selection_schema

from .errors import fail
from .model import seal_document, validate_document
from .patch import apply_patch
from .schema import DIGEST, IDENTIFIER, closed, document_schema
from .validation import validate_wire


def template_schema() -> dict[str, Any]:
    return closed({"kind": {"const": "sciplot_template"}, "schema_version": {"const": 1},
                   "template_id": IDENTIFIER, "presentation": document_schema()["properties"]["presentation"],
                   "series_slots": {"type": "array", "uniqueItems": True, "items": IDENTIFIER}})


def binding_schema() -> dict[str, Any]:
    coordinate = closed({"source_id": IDENTIFIER, "column": {"type": "string", "minLength": 1},
                         "column_index": {"type": "integer", "minimum": 0}}, ["source_id", "column"])
    slot = closed({"series_id": IDENTIFIER, "sample": {"type": "string", "minLength": 1},
                   "x": coordinate, "y": coordinate, "x_unit": {"type": "string"}, "y_unit": {"type": "string"}})
    source = closed({"source_id": IDENTIFIER, "sha256": DIGEST, "path": {"type": "string", "minLength": 1},
                     "table_selection": table_selection_schema(), "metadata_confirmations": metadata_confirmations_schema()},
                    ["source_id", "sha256", "path"])
    return closed({"kind": {"const": "sciplot_binding"}, "schema_version": {"const": 1},
                   "template_id": IDENTIFIER, "data_sources": {"type": "array", "items": source},
                   "slots": {"type": "object", "propertyNames": IDENTIFIER, "additionalProperties": slot},
                   "transforms": {"type": "array", "items": {"type": "object"}},
                   "guards": {"type": "object"}, "provenance": {"type": "object"}})


def theme_schema() -> dict[str, Any]:
    rule = closed({"target": {"type": "array", "minItems": 1, "uniqueItems": True, "items": IDENTIFIER},
                   "property": {"type": "string", "minLength": 1}, "value": {}})
    return closed({"kind": {"const": "sciplot_theme"}, "schema_version": {"const": 1},
                   "theme_id": IDENTIFIER, "rules": {"type": "array", "maxItems": 100, "items": rule}})


def _empty_document(presentation: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "sciplot_document", "schema_version": 1, "plot_id": "template-check", "revision": 0,
            "scientific": {"data_sources": [], "transforms": [], "mappings": {}, "guards": {}, "provenance": {}},
            "presentation": presentation, "coverage": {"mode": "managed", "limitations": []}}


def validate_template(template: Any) -> dict[str, Any]:
    validate_wire(template, template_schema(), code="document_invalid_template")
    assert isinstance(template, dict)
    validate_document(_empty_document(template["presentation"]))
    objects = template["presentation"]["objects"]
    series = {identifier for identifier, obj in objects.items() if obj["kind"] == "series"}
    if set(template["series_slots"]) != series:
        fail("document_template_slots", "Every template series must have exactly one explicit binding slot.",
             "/series_slots", "series_binding_equality", expected=sorted(series))
    return deepcopy(template)


def validate_binding(binding: Any) -> dict[str, Any]:
    validate_wire(binding, binding_schema(), code="document_invalid_binding")
    assert isinstance(binding, dict)
    sources = [source["source_id"] for source in binding["data_sources"]]
    outputs = [node["output"] for node in binding["transforms"] if isinstance(node.get("output"), str)]
    ids = [slot["series_id"] for slot in binding["slots"].values()]
    if len(sources) != len(set(sources)) or len(ids) != len(set(ids)):
        fail("document_binding_duplicate", "Source IDs and bound series IDs must be unique.", "/slots", "unique_ids")
    for name, slot in binding["slots"].items():
        for axis in ("x", "y"):
            if slot[axis]["source_id"] not in sources + outputs:
                fail("document_binding_source", "A coordinate must reference an explicitly bound source.",
                     f"/slots/{name}/{axis}/source_id", "source_reference", allowed=sources + outputs)
    return deepcopy(binding)


def validate_theme(theme: Any) -> dict[str, Any]:
    validate_wire(theme, theme_schema(), code="document_invalid_theme")
    assert isinstance(theme, dict)
    return deepcopy(theme)


def instantiate_template(template: Any, binding: Any, *, plot_id: str,
                         theme: Any = None) -> dict[str, Any]:
    """Instantiate explicitly supplied bindings. Native creation is a separate service."""
    template, binding = validate_template(template), validate_binding(binding)
    if template["template_id"] != binding["template_id"] or set(template["series_slots"]) != set(binding["slots"]):
        fail("document_binding_mismatch", "Supply exactly this template's named binding slots.",
             "/slots", "template_binding", expected=template["series_slots"])
    result = _empty_document(template["presentation"])
    result["plot_id"] = plot_id
    objects = result["presentation"]["objects"]
    bound_objects: dict[str, Any] = {}
    for identifier, obj in objects.items():
        slot = binding["slots"].get(identifier)
        new_id = slot["series_id"] if slot else identifier
        if new_id in bound_objects:
            fail("document_binding_duplicate", "A bound series ID collides with another semantic object.", "/slots", "unique_ids")
        bound_objects[new_id] = deepcopy(obj)
        if slot:
            bound_objects[new_id]["label"] = slot["sample"]
    result["presentation"]["objects"] = bound_objects
    result["scientific"] = {key: deepcopy(binding[key]) for key in ("data_sources", "transforms", "guards", "provenance")}
    result["scientific"]["mappings"] = {slot["series_id"]: deepcopy(slot) for slot in binding["slots"].values()}
    result = seal_document(result)
    if theme is not None:
        checked_theme = validate_theme(theme)
        if checked_theme["rules"]:
            result, _, risk = apply_patch(result, {"plot_id": plot_id, "base_revision": 0,
                "idempotency_key": "template-theme", "intent_class": "presentation",
                "changes": [{"op": "set", **rule} for rule in checked_theme["rules"]]})
            if risk != "presentation":
                fail("document_theme_review_required", "A reusable theme cannot silently apply a review or scientific change.",
                     "/rules", "presentation_only")
        result["presentation"]["theme"] = checked_theme
    return seal_document(result)
