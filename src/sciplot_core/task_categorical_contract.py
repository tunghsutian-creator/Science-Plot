"""Closed ordinary categorical choices, independent of experimental identities."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from sciplot_core.mapping_contract.categorical import categorical_binding_schema, validate_categorical_binding
from sciplot_core.task_errors import TaskControlError


def categorical_request_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}
    return {"type": "object", "additionalProperties": False,
            "properties": {"version": {"type": "integer", "const": 1},
                           "action": {"const": "create"}, "source": text, "out": text,
                           "categorical": categorical_binding_schema(),
                           "missing_values": {"enum": ["exclude"]},
                           "task_dir": {**text, "deprecated": True}},
            "required": ["version", "action", "source", "categorical"]}


def categorical_response_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "properties": {"expected_question_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                           "categorical": categorical_binding_schema(),
                           "missing_values": {"enum": ["exclude"]}},
            "required": ["expected_question_id", "categorical"]}


def validate_categorical_request(value: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_categorical_binding(value.get("categorical"))
    except ValueError as exc:
        raise TaskControlError("invalid_categorical_request", str(exc)) from exc
    errors = list(Draft202012Validator(categorical_request_schema()).iter_errors(value))
    if errors:
        raise TaskControlError("invalid_categorical_request", errors[0].message)
    return dict(json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))
