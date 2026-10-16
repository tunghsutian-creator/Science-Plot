"""Figure grammar edits use the existing revision transaction, never a second store."""

from collections.abc import Iterator
from copy import deepcopy
from typing import Any

from sciplot_core.plot_ir.figure_document import figure_spec, store_spec

from .errors import EngineError

PROPERTIES = {"theme", "layout", "scale.domain", "axis.ticks", "axis.label", "style",
              "legend.location", "annotation.text", "annotation.x", "annotation.y"}
_PROPERTY_NAMES = {
    "figure": ("theme", "layout"), "scale": ("scale.domain",),
    "view": ("style",), "axis": ("style", "axis.label", "axis.ticks"),
    "layer": ("style",), "mark": ("style",), "legend": ("style", "legend.location"),
    "annotation": ("style", "annotation.text", "annotation.x", "annotation.y"),
}


def _figure_targets(spec: dict[str, Any]) -> Iterator[tuple[str, str, str | None]]:
    """Visit semantic IDs in the same order as the full edit contract."""
    yield spec["id"], "figure", None
    for scale in spec["scales"]:
        yield scale["id"], "scale", None
    for view in spec["views"]:
        yield view["id"], "view", None
        for axis in view["axes"]:
            yield axis["id"], "axis", None
        for layer in view["layers"]:
            yield layer["id"], "layer", None
            for mark in layer["marks"]:
                yield mark["id"], "mark", mark["type"]
    for guide in spec["guides"]:
        yield guide["id"], "legend", None
    for annotation in spec["annotations"]:
        yield annotation["id"], "annotation", None


def figure_property_names(spec: dict[str, Any]) -> dict[str, list[str]]:
    """Advertise Figure edit properties without constructing their value schemas."""
    return {target: list(_PROPERTY_NAMES[kind]) for target, kind, _ in _figure_targets(spec)}


def _figure_edit_descriptor(spec: dict[str, Any], target: str, kind: str,
                            property_name: str, mark_type: str | None) -> dict[str, Any]:
    """The shared descriptor owner for full and selective Figure reads."""
    from sciplot_core.plot_grammar.schema import (
        axis_schema,
        figure_layout_schema,
        guide_schema,
        scale_schema,
    )
    from sciplot_core.plot_grammar.styles import scope_schema, style_schema
    from sciplot_core.plot_ir.figure_document import theme_schema

    risk = "scientific" if property_name == "scale.domain" else "presentation"
    if property_name == "theme":
        schema = theme_schema()
    elif property_name == "layout":
        schema = figure_layout_schema()
    elif property_name == "scale.domain":
        schema = scale_schema()["properties"]["domain"]
    elif property_name in {"axis.label", "axis.ticks"}:
        schema = axis_schema()["properties"][property_name.removeprefix("axis.")]
    elif property_name == "annotation.text":
        schema = {"type": "string", "minLength": 1, "maxLength": 500}
    elif property_name == "legend.location":
        guide = next(item for item in spec["guides"] if item["id"] == target)
        schema = deepcopy(guide_schema()["properties"]["location"])
        locations = ({"top-right", "top-left", "bottom-right", "bottom-left",
                      *({"inside-best"} if "rendering_contract" in spec else set())}
                     if guide["scope"] == "view" else {"top", "bottom", "left", "right"})
        schema["enum"] = [value for value in schema["enum"] if value in locations]
    elif property_name in {"annotation.x", "annotation.y"}:
        annotation = next(item for item in spec["annotations"] if item["id"] == target)
        schema = {"type": "number"}
        if annotation["space"] == "data":
            risk = "scientific"
        else:
            schema.update(minimum=0, maximum=1)
    elif kind == "view":
        schema = scope_schema()
    elif kind == "layer":
        schema = scope_schema(layer=True)
    else:
        schema = style_schema(mark_type if kind == "mark" and mark_type is not None else kind)
    return {"value_schema": schema, "risk": risk}


def figure_edit_descriptor(spec: dict[str, Any], target: str, property_name: str) -> dict[str, Any]:
    """Build one descriptor after the caller checks advertised target/property IDs."""
    for candidate, kind, mark_type in _figure_targets(spec):
        if candidate == target:
            if property_name not in _PROPERTY_NAMES[kind]:
                raise ValueError("The requested Figure property is not advertised for this target.")
            return _figure_edit_descriptor(spec, target, kind, property_name, mark_type)
    raise ValueError("The requested Figure target does not exist.")


def prepare_figure_update(document: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str, bool]:
    spec = figure_spec(document)
    index = {spec["id"]: (spec, "figure")}
    for scale in spec["scales"]:
        index[scale["id"]] = (scale, "scale")
    for view in spec["views"]:
        index[view["id"]] = (view, "view")
        for axis in view["axes"]:
            index[axis["id"]] = (axis, "axis")
        for layer in view["layers"]:
            index[layer["id"]] = (layer, "layer")
            for mark in layer["marks"]:
                index[mark["id"]] = (mark, "mark")
    for item in spec["guides"] + spec["annotations"]:
        index[item["id"]] = (item, "annotation" if "space" in item else "legend")
    diff: list[dict[str, Any]] = []
    touched: set[tuple[str, str]] = set()
    for change in request["changes"]:
        prop = change["property"]
        if prop not in PROPERTIES:
            raise EngineError("figure_mixed_update", "Keep Figure grammar edits separate from scientific executor/source updates.")
        allowed, field = {
            "theme": ({"figure"}, "theme"), "layout": ({"figure"}, "layout"),
            "scale.domain": ({"scale"}, "domain"), "axis.ticks": ({"axis"}, "ticks"),
            "axis.label": ({"axis"}, "label"), "style": ({"view", "layer", "mark", "axis", "legend", "annotation"}, "style"),
            "legend.location": ({"legend"}, "location"), "annotation.text": ({"annotation"}, "text"),
            "annotation.x": ({"annotation"}, "x"), "annotation.y": ({"annotation"}, "y"),
        }[prop]
        for target in change["target"]:
            if target not in index or index[target][1] not in allowed:
                raise EngineError("document_unknown_target", "This grammar property requires a matching stable semantic target.")
            if (target, prop) in touched:
                raise EngineError("document_duplicate_change", "Set each target/property once per transaction.")
            touched.add((target, prop))
            item = index[target][0]
            descriptor = figure_edit_descriptor(spec, target, prop)
            risk = descriptor["risk"]
            if risk == "scientific" and request["intent_class"] != "scientific":
                raise EngineError("figure_scientific_intent_required",
                                  "Scale domains and data-space annotation coordinates require explicit scientific intent.")
            if prop in {"legend.location", "annotation.x", "annotation.y"}:
                from sciplot_core.plot_document.validation import validate_wire

                validate_wire(change["value"], descriptor["value_schema"], code="figure_edit_invalid_value")
            before, after = deepcopy(item[field]), deepcopy(change["value"])
            if before != after:
                item[field] = after
                diff.append({"target": target, "property": prop, "before": before, "after": after, "risk": risk})
    updated = store_spec(document, spec)
    risk = "scientific" if updated["scientific_hash"] != document["scientific_hash"] else "presentation"
    # Domain/anchor changes recompile sealed coordinates; they do not execute transforms.
    return updated, diff, risk, False


def patch_capabilities(spec: dict[str, Any]) -> dict[str, Any]:
    """Publish exact value schemas and stable target IDs for generic grammar edits."""
    return {target: {name: _figure_edit_descriptor(spec, target, kind, name, mark_type) for name in _PROPERTY_NAMES[kind]}
            for target, kind, mark_type in _figure_targets(spec)}


def current_edit_value(spec: dict[str, Any], target: str, property_name: str) -> Any:
    """Read the exact represented value corresponding to a figure patch capability."""
    field = {"theme": "theme", "layout": "layout", "scale.domain": "domain",
             "axis.label": "label", "axis.ticks": "ticks", "style": "style",
             "legend.location": "location", "annotation.text": "text",
             "annotation.x": "x", "annotation.y": "y"}[property_name]
    objects = [spec, *spec["scales"]]
    for view in spec["views"]:
        objects.extend([view, *view["axes"]])
        for layer in view["layers"]:
            objects.extend([layer, *layer["marks"]])
    objects.extend(spec["guides"])
    objects.extend(spec["annotations"])
    return deepcopy(next(item for item in objects if item["id"] == target)[field])
