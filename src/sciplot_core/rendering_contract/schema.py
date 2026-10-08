"""Closed rendering-style snapshot and content binding schemas."""
from typing import Any


def binding_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": ["contract_id", "content_hash"], "properties": {
                "contract_id": {"type": "string", "pattern": "^sciplot-[a-z0-9-]+-v[1-9][0-9]*$"},
                "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}}


def rendering_contract_schema() -> dict[str, Any]:
    record = {"type": "object", "additionalProperties": False,
              "required": ["status", "value", "source_file", "source_symbol", "notes"], "properties": {
                  "status": {"enum": ["specified", "unspecified", "adapter_baseline"]},
                  "value": {}, "source_file": {"type": "string"}, "source_symbol": {"type": "string"},
                  "notes": {"type": "string"}},
              "allOf": [{"if": {"properties": {"status": {"const": "unspecified"}}},
                         "then": {"properties": {"value": {"const": "unspecified"}}},
                         "else": {"properties": {"source_file": {"minLength": 1}, "source_symbol": {"minLength": 1}}}}]}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
            "required": ["kind", "schema_version", "contract_id", "authority", "properties", "content_hash"],
            "properties": {"kind": {"const": "sciplot_rendering_style_contract"}, "schema_version": {"const": 1},
                           **binding_schema()["properties"],
                           "authority": {"enum": ["legacy_source_extraction", "new_composition_policy"]},
                           "properties": {"type": "object", "minProperties": 1, "additionalProperties": record}}}
