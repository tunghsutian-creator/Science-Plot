"""Closed native display identity and delta validation, without native execution."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.workflow.native_suite_objects import descriptor


def _check_identity(context: dict[str, Any], request: dict[str, Any]) -> None:
    if request["plot_id"] != context["plot_id"]:
        raise EngineError("document_identity_conflict", "The request belongs to a different native figure.")
    if request["base_revision"] != context["revision"]:
        raise EngineError("document_revision_conflict", "Read the current object revision before changing it.",
                          action="plot.describe", current_revision=context["revision"])


def _changes(context: dict[str, Any], request: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    if request["intent_class"] != "presentation":
        raise EngineError("native_object_intent_unsupported", "This native adapter accepts presentation deltas only.")
    targets, seen, diff, native = context["state"]["targets"], set(), [], []
    for change in request["changes"]:
        prop, value = change["property"], change["value"]
        for identifier in change["target"]:
            item = targets.get(identifier)
            if item is None:
                raise EngineError("document_unknown_target", "Choose an existing advertised target.")
            if prop not in item["properties"]:
                raise EngineError("document_unsupported_property", "This object does not advertise that property.")
            if (identifier, prop) in seen:
                raise EngineError("document_duplicate_change", "Set each target/property once per transaction.")
            seen.add((identifier, prop))
            validate_wire(value, descriptor(prop)["value_schema"], code="figure_edit_invalid_value")
            before = item["properties"][prop]
            if before == value:
                continue
            diff.append({"target": identifier, "property": prop, "before": deepcopy(before),
                         "after": deepcopy(value), "risk": "presentation"})
            native.append({"target": identifier, "property": prop, "value": deepcopy(value),
                           "before_native": deepcopy(item["native_fields"])})
    return diff, native
