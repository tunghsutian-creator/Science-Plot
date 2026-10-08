"""Shared closed request schemas for semantic plot lifecycle operations."""

from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.schema import closed
from sciplot_core.plot_document.validation import validate_wire

_KEY = {"type": "string", "minLength": 1, "maxLength": 128}
_REVISION = {"type": "integer", "minimum": 0}
_PATH = {"type": "string", "minLength": 1, "pattern": "^/"}


def create_schema() -> dict[str, Any]:
    from sciplot_core.plot_document.templates import binding_schema, template_schema, theme_schema

    original = closed({"idempotency_key": deepcopy(_KEY), "source": deepcopy(_PATH),
                   "rule_id": {"type": "string", "minLength": 1},
                   "template": {"type": "string", "minLength": 1},
                   "profile": deepcopy(_PATH), "out": deepcopy(_PATH)},
                  ["idempotency_key", "source"])
    templated = closed({"idempotency_key": deepcopy(_KEY), "template_definition": template_schema(),
                        "data_binding": binding_schema(), "theme": theme_schema(),
                        "mode": {"enum": ["managed", "legacy"]},
                        "scientific_executors": {"type": "object", "additionalProperties": {"type": "object"}},
                        "rule_id": {"type": "string", "minLength": 1}, "out": deepcopy(_PATH)},
                       ["idempotency_key", "template_definition", "data_binding", "rule_id"])
    from sciplot_core.plot_ir.figure_document import template_schema as figure_template_schema, theme_schema as figure_theme_schema

    figure = deepcopy(templated)
    figure["properties"].update(template_definition=figure_template_schema(), theme=figure_theme_schema(), mode={"const": "managed"})
    return {"oneOf": [original, templated, figure]}


def rollback_schema() -> dict[str, Any]:
    return closed({"base_revision": deepcopy(_REVISION), "target_revision": deepcopy(_REVISION),
                   "idempotency_key": deepcopy(_KEY)})


def decide_schema() -> dict[str, Any]:
    from sciplot_core.task_contract import task_response_schema

    return {"oneOf": [closed({"decision_id": deepcopy(_KEY), "base_revision": deepcopy(_REVISION),
                              "accept": {"type": "boolean"}}),
                      closed({"decision_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                              "base_revision": deepcopy(_REVISION), "reimport": {"const": True}}),
                      closed({"response": task_response_schema()})]}


def validate_create(value: Any) -> dict[str, Any]:
    validate_wire(value, create_schema(), code="plot_invalid_create")
    assert isinstance(value, dict)
    return deepcopy(value)


def validate_rollback(value: Any) -> dict[str, Any]:
    validate_wire(value, rollback_schema(), code="plot_invalid_rollback")
    assert isinstance(value, dict)
    return deepcopy(value)


def validate_decide(value: Any) -> dict[str, Any]:
    validate_wire(value, decide_schema(), code="plot_invalid_decision")
    assert isinstance(value, dict)
    return deepcopy(value)
