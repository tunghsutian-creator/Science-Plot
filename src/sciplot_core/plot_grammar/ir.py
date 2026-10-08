"""PlotIR v2: closed, resolved physical drawing state with a deterministic seal."""
from copy import deepcopy
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.schema import DIGEST, IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_layout import resolved_layout_schema, structural_publication_qa
from sciplot_core.plot_transforms.datasets import dataset_schema

from sciplot_core.rendering_contract import require_binding, resolved_style_defaults

from .schema import rendering_binding_schema, annotation_schema, axis_schema, guide_schema, layer_schema, scale_schema
from .styles import COLOR, style_schema
from .validation import validate_bound_data, validate_axis_presentation


def ir_schema_v2() -> dict[str, Any]:
    view = closed({"id": IDENTIFIER, "panel_label": {"type": ["string", "null"], "maxLength": 16},
        "panel_label_style": style_schema("annotation", resolved=True),
        "axes": {"type": "array", "items": axis_schema(resolved=True)},
        "layers": {"type": "array", "minItems": 1, "items": layer_schema(resolved=True)}})
    qa = closed({"kind": {"const": "sciplot_figure_layout_qa"}, "schema_version": {"const": 1},
        "status": {"enum": ["passed", "failed"]}, "hard": {"type": "array", "items": {"type": "object"}},
        "soft": {"type": "array", "items": {"type": "object"}}, "checks": {"type": "array", "items": {"type": "string"}},
        "native_text_checked": {"const": False}, "journal_compliance_established": {"const": False}})
    fields = {"kind": {"const": "sciplot_plot_ir"}, "schema_version": {"const": 2},
        "scientific_hash": DIGEST, "presentation_hash": DIGEST,
        "figure": closed({"id": IDENTIFIER, "background_color": COLOR}),
        "datasets": {"type": "object", "propertyNames": IDENTIFIER, "additionalProperties": dataset_schema()},
        "scales": {"type": "array", "minItems": 2, "items": scale_schema()},
        "views": {"type": "array", "minItems": 1, "items": view}, "layout": resolved_layout_schema(),
        "guides": {"type": "array", "items": guide_schema(resolved=True)},
        "annotations": {"type": "array", "items": annotation_schema(resolved=True)}, "layout_qa": qa, "ir_hash": DIGEST,
        "rendering_contract": rendering_binding_schema("sciplot-house-style-v1"),
        "composition_policy": rendering_binding_schema("sciplot-figure-composition-v1"),
        "style_provenance": {"type": "object"}}
    return closed(fields, [key for key in fields if key not in {"ir_hash", "rendering_contract", "composition_policy", "style_provenance"}])


def _invalid(message: str, path: str, **details: Any) -> None:
    fail("figure_ir_reference", message, path, "resolved_reference", **details)


def _validate(value: Any, *, verify: bool) -> dict[str, Any]:
    validate_wire(value, ir_schema_v2(), code="figure_ir_invalid")
    assert isinstance(value, dict)
    result = deepcopy(value)
    for field in ("rendering_contract", "composition_policy"):
        if field in result:
            require_binding(result[field])
    if "rendering_contract" in result:
        def require_style(kind: str, style: dict[str, Any]) -> None:
            if not set(resolved_style_defaults(kind, binding=result["rendering_contract"])) <= set(style):
                _invalid("Bound IR requires every contract visual channel to be resolved.", "/style", kind=kind)
        for view in result["views"]:
            require_style("annotation", view["panel_label_style"])
            for axis in view["axes"]:
                require_style("axis", axis["style"])
                if axis.get("text_layout") != "axis-metric-flow":
                    _invalid("Bound axes must declare their metric flow.", "/views/axes")
            for layer in view["layers"]:
                for mark in layer["marks"]:
                    require_style(mark["type"], mark["style"])
        for guide in result["guides"]:
            require_style("legend", guide["style"])
        for annotation in result["annotations"]:
            require_style("annotation", annotation["style"])
    elif "composition_policy" in result:
        _invalid("Composition policy cannot be detached from its rendering contract.", "/composition_policy")
    scales = {scale["id"]: scale for scale in result["scales"]}
    views = {view["id"]: view for view in result["views"]}
    ids = [result["figure"]["id"], *scales]
    ids += [guide["id"] for guide in result["guides"]] + [annotation["id"] for annotation in result["annotations"]]
    layers = {}
    for scale in result["scales"]:
        low, high = scale["domain"]
        if low >= high or scale["transform"] == "log" and low <= 0:
            _invalid("Resolved scales require a valid increasing domain.", "/scales")
    for view in result["views"]:
        ids.append(view["id"])
        bound = set()
        for layer in view["layers"]:
            ids += [layer["id"], *(mark["id"] for mark in layer["marks"])]
            layers[layer["id"]] = (view["id"], layer)
            for dimension in ("x", "y"):
                scale = scales.get(layer[dimension + "_scale"])
                if scale is None or scale["dimension"] != dimension or scale["quantity"] != layer["mapping_semantics"][dimension]:
                    _invalid("Layers bind existing scales with matching dimensions and scientific quantities.", "/views/layers")
                bound.add(layer[dimension + "_scale"])
            bounds = any(mark["type"] in {"errorbar", "band"} for mark in layer["marks"])
            if set(layer["mappings"]) != ({"x", "y", "y_low", "y_high"} if bounds else {"x", "y"}):
                _invalid("Mark channel requirements must be represented exactly.", "/views/layers/mappings")
        for axis in view["axes"]:
            ids.append(axis["id"])
            if axis["view_id"] != view["id"] or axis["scale_id"] not in bound:
                _invalid("Every axis guides an existing scale in its containing view.", "/views/axes")
            scale = scales[axis["scale_id"]]
            if scale["dimension"] != ("x" if axis["side"] in {"top", "bottom"} else "y"):
                _invalid("Axis guide direction must equal its bound scale dimension.", "/views/axes")
            if axis.get("text_layout") != "axis-metric-flow" and (len(axis["ticks"]) != len(axis.get("tick_labels", []))
                    or len(axis["ticks"]) != len(axis.get("tick_positions_mm", []))):
                _invalid("Every resolved tick requires one exact text and physical anchor.", "/views/axes")
            if axis.get("text_layout") == "axis-metric-flow":
                required_style = {"major_tick_width_pt", "minor_tick_width_pt", "minor_tick_length_pt", "label_padding_pt",
                    "tick_label_padding_pt", "minor_tick_count", "tick_color", "grid_visible", "minor_grid_visible", "minor_ticks_visible"}
                if "rendering_contract" not in result or not required_style <= set(axis["style"]) or not {"minor_ticks", "tick_notation"} <= set(axis):
                    _invalid("Metric flow requires complete resolved typography and a pinned contract.", "/views/axes")
                if axis["style"].get("tick_notation", axis["tick_notation"]) != axis["tick_notation"]:
                    _invalid("Tick notation must agree with its resolved explicit style.", "/views/axes")
                if {"tick_positions_mm", "label_position_mm", "label_angle", "tick_alignment"} & set(axis):
                    _invalid("Metric flow cannot retain ignored physical text anchors.", "/views/axes")
                if (axis["tick_notation"] == "labels") != ("tick_labels" in axis):
                    _invalid("Explicit label mode requires labels; numeric mode cannot ignore supplied labels.", "/views/axes")
                validate_axis_presentation(axis, scale, bound=True)
            if any(not scale["domain"][0] <= tick <= scale["domain"][1] for tick in axis["ticks"]):
                _invalid("Resolved ticks must lie inside their scale domain.", "/views/axes")
    if len(ids) != len(set(ids)) or len(scales) != len(result["scales"]):
        _invalid("All resolved semantic object identities must be unique.", "/")
    panels = result["layout"]["panels"]
    if {panel["view_id"] for panel in panels} != set(views) or len(panels) != len(views):
        _invalid("Every view requires exactly one resolved physical panel.", "/layout/panels")
    for guide in result["guides"]:
        if guide.get("text_layout") == "legend-metric-flow":
            if "rendering_contract" not in result or not {"key_length_mm", "margin_size", "frame_visible"} <= set(guide["style"]):
                _invalid("Legend flow requires complete resolved style and a pinned contract.", "/guides")
            if "rect_mm" in guide or any({"symbol_mm", "label_mm"} & set(entry) for entry in guide["entries"]):
                _invalid("Legend flow cannot retain ignored physical text anchors.", "/guides")
        elif "rect_mm" not in guide or any(not {"symbol_mm", "label_mm"} <= set(entry) for entry in guide["entries"]):
            _invalid("Physical legends require explicit entry geometry.", "/guides")
        local = guide["scope"] == "view"
        if ("view_id" in guide) != local or local and guide["view_id"] not in views:
            _invalid("Resolved legend scope requires exactly its declared view owner.", "/guides")
        for entry in guide["entries"]:
            owner = layers.get(entry["layer_id"])
            if owner is None or local and owner[0] != guide["view_id"] or entry["marks"] != owner[1]["marks"]:
                _invalid("Legend symbols must derive from their actual semantic layer marks.", "/guides/entries")
    for annotation in result["annotations"]:
        if annotation["space"] != "figure" and annotation["view_id"] not in views:
            _invalid("Resolved annotations require their existing view frame.", "/annotations")
        if annotation["space"] == "data":
            for dimension in ("x", "y"):
                if annotation[dimension + "_scale"] not in {layer[dimension + "_scale"] for layer in views[annotation["view_id"]]["layers"]}:
                    _invalid("Data annotations require explicit scales belonging to their view.", "/annotations")
    validate_bound_data(result, result["datasets"])
    qa = structural_publication_qa(result["layout"], annotations=result["annotations"])
    if qa["hard"] or result["layout_qa"]["hard"] or result["layout_qa"]["status"] != "passed":
        _invalid("Invalid resolved geometry cannot be sent to a backend.", "/layout", issues=qa["hard"])
    expected = canonical_json_sha256({key: item for key, item in result.items() if key != "ir_hash"}, allow_nan=False)
    if verify and result.get("ir_hash", expected) != expected:
        fail("plot_ir_hash_mismatch", "Resolved IR bytes do not match their seal.", "/ir_hash", "content_hash")
    result["ir_hash"] = expected
    return result


def validate_ir_v2(value: Any) -> dict[str, Any]:
    return _validate(value, verify=True)


def seal_ir_v2(value: Any) -> dict[str, Any]:
    return _validate(value, verify=False)
