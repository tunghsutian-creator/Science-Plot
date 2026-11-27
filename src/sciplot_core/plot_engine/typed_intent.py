"""A bounded, deterministic edit facade over the existing FigureSpec patch.

The request contains the exact replacement value. It never interprets prose, guesses
units, changes data bindings, or owns a second transaction lifecycle.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.requests import PatchRequest, admit_patch
from sciplot_core.plot_document.schema import IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_grammar.house import StyleResolver
from sciplot_core.plot_grammar.styles import COLOR
from sciplot_core.plot_ir.figure_document import figure_spec, is_figure

from .errors import EngineError
from .figure_updates import current_edit_value, patch_capabilities

LINE_COLOR = "style.line.color"
DISPLAY_LABEL = "series.display_label"
EDIT_KINDS = {"axis.label": "axis", "axis.ticks": "axis", "annotation.text": "annotation",
              LINE_COLOR: "layer", DISPLAY_LABEL: "layer"}


def line_color_targets(document: dict[str, Any], spec: dict[str, Any]) -> dict[
        str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Find ordinary XY measurement curves with one unambiguous line mark."""
    if document["scientific"]["provenance"]["managed"].get("rule_id") != "ordinary_xy":
        return {}
    targets = {}
    for view in spec["views"]:
        for layer in view["layers"]:
            marks = layer["marks"]
            lines = [mark for mark in marks if mark["type"] == "line"]
            if (layer["role"] == "measurement" and len(lines) == 1
                    and all(mark["type"] in {"line", "point"} for mark in marks)):
                targets[layer["id"]] = (view, layer, lines[0])
    return targets


def display_label_targets(spec: dict[str, Any]) -> list[str]:
    return [layer["id"] for view in spec["views"] for layer in view["layers"]
            if layer["role"] == "measurement"]


def intent_schema() -> dict[str, Any]:
    """Closed request used identically by the service, RPC, CLI, and MCP."""
    request = closed({
        "mode": {"enum": ["plan", "apply"]},
        "plot_id": IDENTIFIER,
        "base_revision": {"type": "integer", "minimum": 0},
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
        "property": {"enum": list(EDIT_KINDS)},
        "target_id": IDENTIFIER,
        "target_label": {"type": "string", "minLength": 1, "maxLength": 4096},
        "value": {},
    }, ["mode", "plot_id", "base_revision", "idempotency_key", "property", "value"])
    request.update({
        "if": {"properties": {"property": {"const": "axis.ticks"}}},
        "then": {"properties": {"value": {"oneOf": [
            {"type": "array", "items": {"type": "number"}, "uniqueItems": True},
            closed({"mode": {"const": "automatic"}}, ["mode"]),
        ]}}},
        "else": {"properties": {"value": {"type": "string", "maxLength": 4096}}},
    })
    return request


def validate_intent(request: Any) -> dict[str, Any]:
    validate_wire(request, intent_schema(), code="plot_intent_invalid")
    assert isinstance(request, dict)
    if ("target_id" in request) == ("target_label" in request):
        raise EngineError("plot_intent_target_required", "Choose exactly one stable target ID or exact target label.",
                          action="choose_target", allowed=["target_id", "target_label"])
    if request["property"] == DISPLAY_LABEL and "target_id" not in request:
        raise EngineError("plot_intent_target_required", "Choose the stable measurement layer ID shown in the current figure.",
                          action="choose_target", allowed=["target_id"])
    return deepcopy(request)


def compile_intent(document: dict[str, Any], request: dict[str, Any]) -> tuple[PatchRequest, dict[str, Any]]:
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
    if prop == LINE_COLOR:
        color_targets = line_color_targets(document, spec)
        candidates = list(color_targets)
        contexts = {target: {"view_id": view["id"], "mark_id": mark["id"]}
                    for target, (view, _, mark) in color_targets.items()}
    else:
        contracts = patch_capabilities(spec)
        candidates = [identifier for identifier, obj in objects.items()
                      if obj["kind"] == kind and prop in contracts.get(identifier, {})]
        if prop == DISPLAY_LABEL:
            allowed = set(display_label_targets(spec))
            candidates = [identifier for identifier in candidates if identifier in allowed]
        contexts = {target: {} for target in candidates}
    if "target_id" in request:
        target = request["target_id"]
        if target not in candidates:
            raise EngineError("plot_intent_unknown_target", "Choose an exact stable ID for the requested edit type.",
                              action="choose_target", candidates=_candidates(spec, objects, candidates, kind, contexts))
    else:
        matches = [identifier for identifier in candidates if objects[identifier]["label"] == request["target_label"]]
        if len(matches) != 1:
            raise EngineError("plot_intent_ambiguous_target" if matches else "plot_intent_unknown_target",
                              "The target label does not identify exactly one editable object.",
                              action="choose_target", candidates=_candidates(spec, objects, matches or candidates, kind, contexts))
        target = matches[0]
    after = request["value"]
    target_context: dict[str, Any] = {}
    patch_target, patch_property, patch_value = target, prop, after
    if prop == LINE_COLOR:
        view, layer, mark = color_targets[target]
        validate_wire(after, COLOR, code="plot_intent_invalid_value")
        after = after.lower()
        scopes = [spec["theme"]["project"], spec["theme"]["figure"], view["style"], layer["style"]]
        before = StyleResolver(spec).resolve(mark["id"], "line", scopes, mark["style"],
                                             index=view["layers"].index(layer))["line_color"]
        patch_target, patch_property = mark["id"], "style"
        patch_value = mark["style"] if before == after else {**mark["style"], "line_color": after}
        risk = "presentation"
        target_context = contexts[target]
    else:
        descriptor = contracts[target][prop]
        validate_wire(after, descriptor["value_schema"], code="plot_intent_invalid_value")
        # A single explicit display string keyed by stable measurement ID does
        # not change which sample or numerical values the line represents.
        risk = "presentation" if prop == DISPLAY_LABEL else descriptor["risk"]
        if risk != "presentation":
            raise EngineError("plot_intent_scientific_change", "This edit cannot change scientific state.")
        before = current_edit_value(spec, target, prop)
    patch = admit_patch({"plot_id": request["plot_id"], "base_revision": request["base_revision"],
             "idempotency_key": request["idempotency_key"], "intent_class": "presentation",
             "changes": [{"op": "set", "target": [patch_target], "property": patch_property, "value": patch_value}]})
    if kind == "axis":
        view, axis = next((view, axis) for view in spec["views"] for axis in view["axes"] if axis["id"] == target)
        scale = next(scale for scale in spec["scales"] if scale["id"] == axis["scale_id"])
        target_context = {"view_id": view["id"], "side": axis["side"], "scale_id": scale["id"],
                          **{field: scale[field] for field in
                          ("dimension", "quantity", "unit", "domain")}}
    elif kind == "annotation":
        annotation = next(item for item in spec["annotations"] if item["id"] == target)
        target_context = {field: annotation[field] for field in ("space", "view_id", "x_scale", "y_scale", "x", "y")
                          if field in annotation}
    plan = {"kind": "sciplot_plot_intent_plan", "version": 1,
            "status": "no_change" if before == after else "ready", "plot_id": document["plot_id"],
            "base_revision": document["revision"], "target": {"id": target, "kind": kind,
                                                            "label": objects[target]["label"]},
            "property": prop, "before": before, "after": after,
            "effective_risk": risk, "target_context": target_context, "patch_request": patch.to_payload()}
    return patch, plan


def _candidates(spec: dict[str, Any], objects: dict[str, Any], ids: list[str],
                kind: str, contexts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
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
        elif kind == "annotation":
            annotation = next(item for item in spec["annotations"] if item["id"] == identifier)
            context = {field: annotation[field] for field in
                       ("space", "view_id", "x_scale", "y_scale", "x", "y") if field in annotation}
        else:
            context = contexts[identifier]
        result.append({"id": identifier, "kind": kind, "label": objects[identifier]["label"],
                       "context": context})
    return result
