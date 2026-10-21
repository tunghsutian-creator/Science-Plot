"""A bounded, deterministic text-edit facade over the existing FigureSpec patch.

The request contains the exact replacement text. It never interprets prose, guesses
units, changes data bindings, or owns a second transaction lifecycle.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.patch import validate_patch
from sciplot_core.plot_document.schema import IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_ir.figure_document import figure_spec, is_figure

from .errors import EngineError
from .figure_updates import current_edit_value, patch_capabilities

EDIT_KINDS = {"axis.label": "axis", "annotation.text": "annotation"}


def intent_schema() -> dict[str, Any]:
    """Closed request used identically by the service, RPC, CLI, and MCP."""
    return closed({
        "mode": {"enum": ["plan", "apply"]},
        "plot_id": IDENTIFIER,
        "base_revision": {"type": "integer", "minimum": 0},
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
        "property": {"enum": list(EDIT_KINDS)},
        "target_id": IDENTIFIER,
        "target_label": {"type": "string", "minLength": 1, "maxLength": 4096},
        "value": {"type": "string", "maxLength": 4096},
    }, ["mode", "plot_id", "base_revision", "idempotency_key", "property", "value"])


def validate_intent(request: Any) -> dict[str, Any]:
    validate_wire(request, intent_schema(), code="plot_intent_invalid")
    assert isinstance(request, dict)
    if ("target_id" in request) == ("target_label" in request):
        raise EngineError("plot_intent_target_required", "Choose exactly one stable target ID or exact target label.",
                          action="choose_target", allowed=["target_id", "target_label"])
    return deepcopy(request)


def compile_intent(document: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve against one frozen revision and validate through the existing editor."""
    if document.get("plot_type") != "ManagedPlot" or not is_figure(document):
        raise EngineError("plot_intent_v2_required", "This edit requires a managed FigureSpec v2 plot.",
                          action="plot.describe")
    if request["plot_id"] != document["plot_id"]:
        raise EngineError("document_identity_conflict", "The edit belongs to a different plot.",
                          action="plot.describe", description={"scope": "summary"},
                          current_plot_id=document["plot_id"])
    if request["base_revision"] != document["revision"]:
        raise EngineError("document_revision_conflict", "Read the current revision before changing this plot.",
                          action="plot.describe", description={"scope": "summary"},
                          current_revision=document["revision"])
    prop = request["property"]
    kind = EDIT_KINDS[prop]
    objects = document["presentation"]["objects"]
    spec = figure_spec(document)
    contracts = patch_capabilities(spec)
    candidates = [identifier for identifier, obj in objects.items()
                  if obj["kind"] == kind and prop in contracts.get(identifier, {})]
    if "target_id" in request:
        target = request["target_id"]
        if target not in candidates:
            raise EngineError("plot_intent_unknown_target", "Choose an exact stable ID for the requested edit type.",
                              action="choose_target", candidates=_candidates(spec, objects, candidates, kind))
    else:
        matches = [identifier for identifier in candidates if objects[identifier]["label"] == request["target_label"]]
        if len(matches) != 1:
            raise EngineError("plot_intent_ambiguous_target" if matches else "plot_intent_unknown_target",
                              "The target label does not identify exactly one editable object.",
                              action="choose_target", candidates=_candidates(spec, objects, matches or candidates, kind))
        target = matches[0]
    patch = {"plot_id": request["plot_id"], "base_revision": request["base_revision"],
             "idempotency_key": request["idempotency_key"], "intent_class": "presentation",
             "changes": [{"op": "set", "target": [target], "property": prop, "value": request["value"]}]}
    patch = validate_patch(patch)
    descriptor = contracts[target][prop]
    validate_wire(request["value"], descriptor["value_schema"], code="plot_intent_invalid_value")
    if descriptor["risk"] != "presentation":
        raise EngineError("plot_intent_scientific_change", "This text edit cannot change scientific state.")
    before = current_edit_value(spec, target, prop)
    target_context: dict[str, Any] = {}
    if kind == "axis":
        view, axis = next((view, axis) for view in spec["views"] for axis in view["axes"] if axis["id"] == target)
        scale = next(scale for scale in spec["scales"] if scale["id"] == axis["scale_id"])
        target_context = {"view_id": view["id"], "side": axis["side"], "scale_id": scale["id"],
                          **{field: scale[field] for field in
                          ("dimension", "quantity", "unit", "domain")}}
    else:
        annotation = next(item for item in spec["annotations"] if item["id"] == target)
        target_context = {field: annotation[field] for field in ("space", "view_id", "x_scale", "y_scale", "x", "y")
                          if field in annotation}
    plan = {"kind": "sciplot_plot_intent_plan", "version": 1,
            "status": "no_change" if before == request["value"] else "ready", "plot_id": document["plot_id"],
            "base_revision": document["revision"], "target": {"id": target, "kind": kind,
                                                            "label": objects[target]["label"]},
            "property": prop, "before": before, "after": request["value"],
            "effective_risk": descriptor["risk"], "target_context": target_context, "patch_request": patch}
    return patch, plan


def _candidates(spec: dict[str, Any], objects: dict[str, Any], ids: list[str],
                kind: str) -> list[dict[str, Any]]:
    """Return enough fixed context to make duplicate display labels actionable."""
    result = []
    scales = {item["id"]: item for item in spec["scales"]}
    for identifier in ids[:100]:
        context: dict[str, Any] = {}
        if kind == "axis":
            for view in spec["views"]:
                axis = next((item for item in view["axes"] if item["id"] == identifier), None)
                if axis is not None:
                    scale = scales[axis["scale_id"]]
                    context = {"view_id": view["id"], "side": axis["side"], "scale_id": scale["id"],
                               "quantity": scale["quantity"], "unit": scale["unit"]}
                    break
        else:
            annotation = next(item for item in spec["annotations"] if item["id"] == identifier)
            context = {field: annotation[field] for field in
                       ("space", "view_id", "x_scale", "y_scale", "x", "y") if field in annotation}
        result.append({"id": identifier, "kind": kind, "label": objects[identifier]["label"],
                       "context": context})
    return result
