"""Figure grammar edits use the existing revision transaction, never a second store."""

from copy import deepcopy
from typing import Any

from sciplot_core.plot_ir.figure_document import figure_spec, store_spec

from .errors import EngineError

PROPERTIES = {"theme", "layout", "scale.domain", "axis.ticks", "axis.label", "style", "annotation.text"}


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
            "annotation.text": ({"annotation"}, "text"),
        }[prop]
        risk = "scientific" if prop == "scale.domain" else "presentation"
        if risk == "scientific" and request["intent_class"] != "scientific":
            raise EngineError("figure_scientific_intent_required", "Scale domain changes require explicit scientific intent.")
        for target in change["target"]:
            if target not in index or index[target][1] not in allowed:
                raise EngineError("document_unknown_target", "This grammar property requires a matching stable semantic target.")
            if (target, prop) in touched:
                raise EngineError("document_duplicate_change", "Set each target/property once per transaction.")
            touched.add((target, prop))
            item = index[target][0]
            before, after = deepcopy(item[field]), deepcopy(change["value"])
            if before != after:
                item[field] = after
                diff.append({"target": target, "property": prop, "before": before, "after": after, "risk": risk})
    updated = store_spec(document, spec)
    risk = "scientific" if updated["scientific_hash"] != document["scientific_hash"] else "presentation"
    # Domain changes recompile sealed coordinates; they do not execute transforms.
    return updated, diff, risk, False


def patch_capabilities(spec: dict[str, Any]) -> dict[str, Any]:
    """Publish exact value schemas and stable target IDs for generic grammar edits."""
    from sciplot_core.plot_grammar.schema import figure_layout_schema, scale_schema, axis_schema
    from sciplot_core.plot_grammar.styles import scope_schema, style_schema
    from sciplot_core.plot_ir.figure_document import theme_schema

    def descriptor(schema: dict[str, Any], risk: str = "presentation") -> dict[str, Any]:
        return {"value_schema": schema, "risk": risk}

    result = {spec["id"]: {"theme": descriptor(theme_schema()), "layout": descriptor(figure_layout_schema())}}
    for scale in spec["scales"]:
        result[scale["id"]] = {"scale.domain": descriptor(scale_schema()["properties"]["domain"], "scientific")}
    for view in spec["views"]:
        result[view["id"]] = {"style": descriptor(scope_schema())}
        for axis in view["axes"]:
            result[axis["id"]] = {"style": descriptor(style_schema("axis")),
                **{"axis." + key: descriptor(axis_schema()["properties"][key]) for key in ("label", "ticks")}}
        for layer in view["layers"]:
            result[layer["id"]] = {"style": descriptor(scope_schema(layer=True))}
            for mark in layer["marks"]:
                result[mark["id"]] = {"style": descriptor(style_schema(mark["type"]))}
    for guide in spec["guides"]:
        result[guide["id"]] = {"style": descriptor(style_schema("legend"))}
    for annotation in spec["annotations"]:
        result[annotation["id"]] = {"style": descriptor(style_schema("annotation")),
            "annotation.text": descriptor({"type": "string", "minLength": 1, "maxLength": 500})}
    return result
