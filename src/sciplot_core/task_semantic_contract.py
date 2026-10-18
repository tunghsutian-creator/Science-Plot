"""Small semantic creation intents; scientific documents retain their existing authority."""
from typing import Any

from sciplot_core.plot_document.schema import closed


def intent_schema() -> dict[str, Any]:
    coordinate = closed({"quantity": {"type": "string", "minLength": 1, "maxLength": 128},
                         "unit": {"type": "string", "maxLength": 64},
                         "minimum": {"type": "number"}, "maximum": {"type": "number"},
                         "header": {"type": "string", "minLength": 1},
                         "column_id": {"type": "string", "pattern": "^column:[0-9]+$"}}, ["quantity"])
    interpolation = closed({"method": {"const": "pchip"}, "subdivisions": {"type": "integer", "minimum": 2, "maximum": 32},
                            "purpose": {"const": "display"}, "boundary": {"const": "preserve_gaps"}})
    blocks = {"type": "array", "minItems": 1, "maxItems": 512, "uniqueItems": True,
              "items": closed({"source_id": {"type": "string", "pattern": "^source:[0-9]+$"},
                               "table_id": {"type": "string", "pattern": "^table:[0-9]+$"},
                               "block_id": {"type": "string", "pattern": "^block:[0-9]+$"}},
                              ["source_id", "table_id", "block_id"])}
    selection = closed({"test_names": {"type": "array", "minItems": 1, "maxItems": 32, "uniqueItems": True,
                                        "items": {"type": "string", "minLength": 1, "maxLength": 512}},
                        "blocks": blocks}, [])
    selection["minProperties"] = 1
    return closed({"x": coordinate, "y": coordinate, "secondary_y": {**coordinate, "properties": {**coordinate["properties"], "quantity": {"const": "temperature"}}},
                   "rule_id": {"type": "string", "minLength": 1},
                   "selection": selection,
                   "labels": {"type": "array", "minItems": 1, "maxItems": 32,
                              "items": {"type": "string", "minLength": 1, "maxLength": 160}},
                   "stages": closed({"mode": {"enum": ["source_order", "concatenate"]},
                                     "boundary": {"enum": ["preserve_endpoint", "next_sample"]},
                                     "order": {"enum": ["source_order", "temperature_continuity"]}}, ["mode"]),
                   "display": closed({"marker_every": {"type": "integer", "minimum": 1, "maximum": 100000},
                                      "interpolation": interpolation}, []),
                   "temperature_header": {"type": "string", "minLength": 1},
                   "temperature_source": {"type": "integer", "minimum": 0, "maximum": 31}}, ["x", "y"])


def semantic_request_schema() -> dict[str, Any]:
    return closed({"version": {"type": "integer", "const": 1}, "action": {"const": "create"},
                   "sources": {"type": "array", "minItems": 1, "maxItems": 32, "uniqueItems": True,
                               "items": {"type": "string", "minLength": 1}},
                   "intent": intent_schema(), "out": {"type": "string", "minLength": 1},
                   "task_dir": {"type": "string", "minLength": 1, "deprecated": True}},
                  ["version", "action", "sources", "intent"])


def semantic_response_schemas() -> list[dict[str, Any]]:
    choices = closed({"temperature_header": {"type": "string", "minLength": 1},
                      "temperature_source": {"type": "string", "minLength": 1},
                      "stage_order": {"enum": ["source_order", "temperature_continuity"]},
                      "time_boundary": {"enum": ["preserve_endpoint", "next_sample"]},
                      "stage_mode": {"const": "concatenate"},
                      "x_header": {"type": "string", "minLength": 1},
                      "y_header": {"type": "string", "minLength": 1},
                      "tables": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1}}}, [])
    return [closed({"expected_question_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                    "confirm_plan": {"type": "boolean", "const": True}, "choices": choices},
                   ["expected_question_id", "confirm_plan"]),
            closed({"expected_intent_revision": {"type": "integer", "minimum": 1},
                    "revise_intent": intent_schema()})]


def validate_intent(value: Any) -> dict[str, Any]:
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    from sciplot_core.task_errors import TaskControlError

    error = next(Draft202012Validator(intent_schema()).iter_errors(value), None)
    if error is not None:
        exc = TaskControlError("invalid_semantic_intent", "Use the advertised semantic creation intent; retain source facts and correct only rejected fields.")
        exc.issues = [{"path": "/intent/" + "/".join(str(part) for part in error.absolute_path),
                       "constraint": error.validator, "message": error.message}]
        raise exc
    return dict(deepcopy(value))
