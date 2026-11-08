"""One closed local confirmation request over existing intake contracts."""

from typing import Any

import json
from pathlib import Path
from typing import cast
from jsonschema import Draft202012Validator, ValidationError
from sciplot_core.contract import load_plot_contract
from sciplot_core.foundation.path_names import slug
from sciplot_core.request_contract import normalize_exports, normalize_render_options
from sciplot_core.semantic_sources.confirmation_contract import require_supported_confirmations
from .catalog import intake_catalog_payload

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


class IntakeSessionError(ValueError):
    reason_code = "intake_session_invalid"


def checked_session_request(value: Any) -> dict[str, Any]:
    if (isinstance(value, dict) and value.get("kind") == "sciplot_intake_session"
            and type(value.get("version")) is int and value["version"] == 1):
        fields = set(session_request_schema()["properties"])
        context = {"kind", "version", "created_at", "session_id", "session_path", "input_path",
                   "data_type_label", "experiment_label", "rule_id", "confidence", "reason", "warnings",
                   "semantic", "pending_rule_review"}
        if set(value) - fields - context:
            raise IntakeSessionError("The legacy intake session contains unknown fields.")
        request = {key: item for key, item in value.items() if key in fields and item is not None}
        request.setdefault("group_order_is_explicit", True)
        value = {"kind": "sciplot_local_intake_session", "version": 1, "request": request}
    try:
        json.dumps(value, allow_nan=False)
        Draft202012Validator(session_schema()).validate(value)
    except (ValidationError, ValueError, TypeError) as exc:
        if isinstance(exc, ValidationError):
            field = "/" + "/".join(map(str, exc.absolute_path))
            raise IntakeSessionError(f"Invalid intake session {field}: {exc.message}") from None
        raise IntakeSessionError("The intake session must contain finite JSON values.") from exc
    request = cast(dict[str, Any], value["request"])
    seen = set()
    for group in request["groups"]:
        key = slug(group["sample"]).casefold()
        if key in seen:
            raise IntakeSessionError("Sample groups must have distinct names and project-local folder identities.")
        seen.add(key)
    normalize_exports(request.get("exports"))
    return request


def _new_plot_output(request: dict[str, Any]) -> None:
    output = request.get("plot_output")
    if output:
        path = Path(output).expanduser()
        if path.is_absolute():
            if path.exists() or path.is_symlink():
                raise IntakeSessionError("plot_output must name a new output, never an existing file, directory or symlink.")
        elif not path.parts or ".." in path.parts or path.parts[0] in {"raw", "source", "studio"}:
            raise IntakeSessionError("Relative plot_output must stay in the new project's output area.")


def admit_session_payload(value: Any, *, template: str | None = None) -> dict[str, Any]:
    """Admit an external envelope once; only its request selects execution."""
    request = checked_session_request(value)
    selected = None
    for data_type in intake_catalog_payload(include_pending=True)["data_types"]:
        if data_type["id"] == request["data_type_id"]:
            selected = next((item for item in data_type["experiments"]
                             if item["id"] == request["experiment_type_id"]), None)
            break
    rule_id = selected.get("rule_id") if selected is not None else None
    if not isinstance(rule_id, str) or not rule_id:
        raise IntakeSessionError("Choose a currently ready data_type_id/experiment_type_id from the local intake catalog.")
    rule = get_rule(rule_id)
    pending = rule.fixture_status != "ready"
    selected_template = str(template or "").strip() or None
    if pending and selected_template is None:
        raise IntakeSessionError("Choose a currently ready rule; a non-ready review requires an explicit rule plus template.")
    require_supported_confirmations(rule, request.get("column_confirmations"))
    normalize_render_options(request.get("render_options"), template=selected_template or rule.template)
    _new_plot_output(request)
    payload = {**request, "rule_id": rule_id,
               "reason": "Explicit local intake selection, not recognition confidence."}
    if pending:
        payload["pending_rule_review"] = True
    return payload


def local_session_envelope(observed: dict[str, Any]) -> dict[str, Any]:
    fields = ("project_name", "data_type_id", "experiment_type_id", "output_root", "groups", "group_order_is_explicit")
    request = {key: observed[key] for key in fields}
    envelope = {"kind": "sciplot_local_intake_session", "version": 1, "request": request,
                "context": {key: value for key, value in observed.items() if key not in fields},
                "capabilities": {
                    "request_schema": session_request_schema(observed["rule_id"]), "catalog": intake_catalog_payload(),
                    "scientific_choices": (confirmation_capabilities(get_rule(observed["rule_id"]))
                                           if observed.get("rule_id") else {"requires_ready_rule_selection": True}),
                    "template_editable_options": {name: list(spec.editable_options)
                                                  for name, spec in load_plot_contract().templates.items()},
                    "replicate_modes": sorted(_REPLICATE_MODES),
                    "source_binding": "Each original source_path/size_bytes/sha256 is verified by the existing session reader.",
                    "authority": "Edit request choices only; context/capabilities are non-authoritative and never enter execution.",
                    "creation": "A new directory is atomically reserved using the existing name/suffix behavior. A repeated create is another creation, not a native retry.",
                    "table_preview": "intake table SESSION.json --group N --file N [--sheet EXACT_NAME] --json uses zero-based request indices and never substitutes another worksheet.",
                    "next_step": "Confirm sample/file grouping and order, rule navigation, columns, dimensions and exports in request; then intake create SESSION.json --json."}}
    return envelope
