"""Small semantic creation intents; scientific documents retain their existing authority."""
from typing import Any

from sciplot_core.plot_document.schema import closed


def intent_schema() -> dict[str, Any]:
    coordinate = closed({"quantity": {"type": "string", "minLength": 1, "maxLength": 128},
                         "unit": {"type": "string", "maxLength": 64},
                         "source_unit": {"type": "string", "minLength": 1, "maxLength": 64,
                                         "description": "Explicit user declaration only for an absent original unit; unit remains the requested output unit."},
                         "direction": {"enum": ["ascending", "descending"],
                                       "description": "Existing display-scale direction; original row order and coordinate values stay unchanged."},
                         "scale": {"enum": ["linear", "log"], "description": "Explicit axis transform; log requires every original mapped observation to be positive."},
                         "minimum": {"type": "number"}, "maximum": {"type": "number"},
                         "header": {"type": "string", "minLength": 1},
                         "headers": {"type": "array", "minItems": 1, "maxItems": 256, "uniqueItems": True,
                                     "items": {"type": "string", "minLength": 1},
                                     "description": "Exact original headers across sample blocks; each block must resolve exactly one column."},
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
    secondary = {**coordinate, "properties": {**{key: value for key, value in coordinate["properties"].items()
                                                 if key not in {"headers", "source_unit"}}, "quantity": {"const": "temperature"}}}
    from sciplot_core.task_semantic_curve_bindings import curve_binding_schema
    from sciplot_core.plot_grammar.schema import quantity_members_schema

    response = {**coordinate, "properties": {**coordinate["properties"], "quantity_members": quantity_members_schema()}}
    return closed({"x": coordinate, "y": response, "secondary_y": secondary,
                   "curve_bindings": {"type": "array", "minItems": 1, "maxItems": 256, "uniqueItems": True,
                                      "items": curve_binding_schema(), "description": "Exact original column pairs for every selected block and declared Y quantity; no shared X grid is inferred."},
                   "rule_id": {"type": "string", "minLength": 1},
                   "source_context": {"type": "string", "minLength": 1, "maxLength": 2000,
                                      "description": "User-stated acquisition context, archived verbatim in source-bound provenance; it does not select an experiment or calculation."},
                   "selection": selection,
                   "labels": {"type": "array", "minItems": 1, "maxItems": 32,
                              "description": "One display label per retained source-bound curve, in original attachment/block order; raw sample identity is preserved.",
                              "items": {"type": "string", "minLength": 1, "maxLength": 160}},
                   "stages": closed({"mode": {"enum": ["source_order", "concatenate"]},
                                     "boundary": {"enum": ["preserve_endpoint", "next_sample"]},
                                     "order": {"enum": ["source_order", "temperature_continuity"]}}, ["mode"]),
                   "display": closed({"marker_every": {"type": "integer", "minimum": 1, "maximum": 100000},
                                      "interpolation": interpolation}, []),
                   "temperature_header": {"type": "string", "minLength": 1},
                   "temperature_source": {"type": "integer", "minimum": 0, "maximum": 31}}, ["x", "y"])


def semantic_request_schema() -> dict[str, Any]:
    from sciplot_core.task_scientific_presentation import presentation_requirement_properties

    return closed({"version": {"type": "integer", "const": 1}, "action": {"const": "create"},
                   "sources": {"type": "array", "minItems": 1, "maxItems": 32, "uniqueItems": True,
                               "items": {"type": "string", "minLength": 1}},
                   "intent": intent_schema(), **presentation_requirement_properties(), "out": {"type": "string", "minLength": 1},
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
    from sciplot_core.task_semantic_temperature import temperature_selector

    temperature_selector(value)
    return dict(deepcopy(value))
