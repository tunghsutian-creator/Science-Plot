"""Closed, versioned wire contracts for documents and semantic patches."""

from copy import deepcopy
from typing import Any


def closed(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": deepcopy(properties),
            "required": list(properties) if required is None else list(required),
            "additionalProperties": False}


IDENTIFIER = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"}
DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
RISKS = ["presentation", "review", "scientific"]
KINDS = ["series", "title", "axis", "legend", "annotation", "figure", "view", "layer", "mark", "scale"]


def document_schema() -> dict[str, Any]:
    capability = closed({
        "type": {"enum": ["physical_size", "color", "boolean", "string", "number", "number_pair", "enum"]},
        "risk": {"enum": RISKS}, "enum": {"type": "array", "minItems": 1, "uniqueItems": True},
        "nullable": {"type": "boolean"},
        "min_length": {"type": "integer", "minimum": 0, "maximum": 4096},
        "max_length": {"type": "integer", "minimum": 0, "maximum": 4096},
        "non_blank": {"type": "boolean"},
        "direction": {"enum": ["ascending", "descending"]},
        "coordinate_mode": {"enum": ["relative", "axes"]},
        "units": closed({"x": {"type": "string"}, "y": {"type": "string"}}),
    }, ["type", "risk"])
    obj = closed({
        "kind": {"enum": KINDS}, "label": {"type": "string", "maxLength": 4096},
        "properties": {"type": "object"},
        "capabilities": {"type": "object", "additionalProperties": capability},
        "scientific_role": {"type": "string", "minLength": 1, "maxLength": 128},
    }, ["kind", "label", "properties", "capabilities"])
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **closed({
        "kind": {"const": "sciplot_document"}, "schema_version": {"const": 1},
        "plot_id": IDENTIFIER, "revision": {"type": "integer", "minimum": 0},
        "plot_type": {"enum": ["LegacyPlot", "ManagedPlot"]},
        "scientific": closed({
            "data_sources": {"type": "array", "items": {"type": "object"}},
            "transforms": {"type": "array", "items": {"type": "object"}},
            "mappings": {"type": "object"}, "guards": {"type": "object"},
            "provenance": {"type": "object"},
        }),
        "presentation": closed({
            "objects": {"type": "object", "propertyNames": IDENTIFIER, "additionalProperties": obj},
            "layout": {"type": "object"}, "theme": {"type": "object"},
            "export_configuration": {"type": "object"},
        }),
        "coverage": closed({"mode": {"enum": ["managed", "legacy_shadow", "opaque"]},
                            "limitations": {"type": "array", "items": {"type": "string"}}}),
        "backend": {"type": "object"}, "scientific_hash": DIGEST, "presentation_hash": DIGEST,
    }, ["kind", "schema_version", "plot_id", "revision", "scientific", "presentation", "coverage"])}


def patch_schema() -> dict[str, Any]:
    change = closed({"op": {"const": "set"},
                     "target": {"type": "array", "minItems": 1, "maxItems": 1000,
                                "uniqueItems": True, "items": IDENTIFIER},
                     "property": {"type": "string", "minLength": 1, "maxLength": 128}, "value": {}})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **closed({
        "plot_id": IDENTIFIER, "base_revision": {"type": "integer", "minimum": 0},
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
        "intent_class": {"enum": RISKS},
        "changes": {"type": "array", "minItems": 1, "maxItems": 100, "items": change},
    })}
