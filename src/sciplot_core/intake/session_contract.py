"""One closed local confirmation request over existing intake contracts."""

from typing import Any

from .config import _COLUMN_ROLES, _COLUMN_TYPES, _REPLICATE_MODES
from sciplot_core.policy import SUPPORTED_EXPORT_FORMATS
from sciplot_core.policy.render_options import RENDER_OPTION_KEYS
from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.confirmation_contract import confirmation_capabilities


def session_request_schema(rule_id: str | None = None) -> dict[str, Any]:
    choices = confirmation_capabilities(get_rule(rule_id)) if rule_id else None
    text = {"type": "string", "minLength": 1, "pattern": r"\S"}
    digest = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    file = {"type": "object", "additionalProperties": False,
            "properties": {"name": text, "source_path": text,
                           "size_bytes": {"type": "integer", "minimum": 0}, "sha256": digest},
            "required": ["name", "source_path", "size_bytes", "sha256"]}
    column = {"type": "object", "additionalProperties": False,
              "properties": {"index": {"type": "integer", "minimum": 0}, "name": text,
                             "inferred_type": {"enum": sorted(_COLUMN_TYPES)},
                             "confirmed_type": {"enum": choices["column_types"] if choices else sorted(_COLUMN_TYPES)},
                             "role": {"enum": choices["column_roles"] if choices else sorted(_COLUMN_ROLES)}},
              "required": ["index", "name", "confirmed_type", "role"]}
    confirmation: dict[str, Any] = {"type": "object", "additionalProperties": False,
                    "properties": {"sample": text, "file_name": text, "source_path": text,
                                   "sheet": {"type": ["string", "null"]},
                                   "sheet_selected": {"type": "boolean"}, "source_sha256": digest,
                                   "columns": {"type": "array", "items": column}},
                    "required": ["sample", "file_name", "source_sha256", "columns"],
                    "if": {"properties": {"sheet_selected": {"const": True}}, "required": ["sheet_selected"]},
                    "then": {"properties": {"sheet": text}, "required": ["sheet"]},
                    "allOf": [{"if": {"properties": {"sheet": {"type": "string"}}, "required": ["sheet"]},
                               "then": {"properties": {"sheet_selected": {"const": True}}, "required": ["sheet_selected"]}}]}
    if choices and not choices["worksheet"]:
        confirmation["properties"]["sheet"] = {"type": "null"}
        confirmation["properties"]["sheet_selected"] = {"const": False}
    return {"type": "object", "additionalProperties": False,
            "properties": {
                "project_name": text, "data_type_id": text, "experiment_type_id": text,
                "output_root": text, "plot_output": text,
                "groups": {"type": "array", "minItems": 1, "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"sample": text, "files": {"type": "array", "minItems": 1, "items": file}},
                    "required": ["sample", "files"]}},
                "group_order_is_explicit": {"type": "boolean"},
                "replicate_mode": {"enum": sorted(_REPLICATE_MODES)},
                "exports": {"type": "array", "minItems": 1, "uniqueItems": True,
                            "items": {"enum": sorted(SUPPORTED_EXPORT_FORMATS)}},
                "render_options": {"type": "object", "propertyNames": {"enum": sorted(RENDER_OPTION_KEYS)}},
                "column_confirmations": {"type": "array", "items": confirmation}},
            "required": ["project_name", "data_type_id", "experiment_type_id", "output_root", "groups",
                         "group_order_is_explicit"]}


def session_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "properties": {"kind": {"const": "sciplot_local_intake_session"}, "version": {"const": 1, "type": "integer"},
                           "request": session_request_schema(), "context": {"type": "object"},
                           "capabilities": {"type": "object"}},
            "required": ["kind", "version", "request"]}
