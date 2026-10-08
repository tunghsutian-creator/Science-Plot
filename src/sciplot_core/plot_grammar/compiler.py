"""Resolve generic scientific grammar, styles and physical layout without a backend."""
from copy import deepcopy
import math
from typing import Any

from sciplot_core.plot_document.errors import fail
from sciplot_core.rendering_contract import contract_value, require_binding
from sciplot_core.plot_layout import resolve_axis_text, resolve_guides, solve_layout, structural_publication_qa

from .capabilities import require_capabilities
from .styles import MARK_TYPES
from .house_legends import resolve_house_legends
from .house import StyleResolver, axis_flow, resolved_layout_input
from .validation import validate_bound_data, validate_figure_spec


def _fraction(value: float, scale: dict[str, Any]) -> float:
    low, high = scale["domain"]
    if scale["transform"] == "log":
        if value <= 0:
            fail("figure_annotation_domain", "A logarithmic data annotation requires positive coordinates.", "/annotations", "log_domain")
        fraction = (math.log(value) - math.log(low)) / (math.log(high) - math.log(low))
    else:
        fraction = (value - low) / (high - low)
    return 1 - fraction if scale["direction"] == "descending" else fraction


def _annotations(spec: dict[str, Any], layout: dict[str, Any], scopes: list[dict[str, Any]], resolver: StyleResolver) -> list[dict[str, Any]]:
    scales = {scale["id"]: scale for scale in spec["scales"]}
    views = {view["id"]: view for view in spec["views"]}
    panels = {panel["view_id"]: panel for panel in layout["panels"]}
    annotations: list[dict[str, Any]] = deepcopy(spec["annotations"])
    for annotation in annotations:
        local_scopes = scopes + ([views[annotation["view_id"]]["style"]] if "view_id" in annotation else [])
        annotation["style"] = resolver.resolve(annotation["id"], "annotation", local_scopes, annotation["style"])
        x, y = annotation["x"], annotation["y"]
        if annotation["space"] == "figure":
            position = [x * layout["width_mm"], y * layout["height_mm"]]
        else:
            left, top, width, height = panels[annotation["view_id"]]["plot_mm"]
            if annotation["space"] == "data":
                x = _fraction(x, scales[annotation["x_scale"]])
                y = 1 - _fraction(y, scales[annotation["y_scale"]])
            position = [left + x * width, top + y * height]
        annotation["position_mm"] = position
    return annotations


def _guides(spec: dict[str, Any], views: list[dict[str, Any]], scopes: list[dict[str, Any]], resolver: StyleResolver) -> list[dict[str, Any]]:
    layers = {layer["id"]: (view["id"], layer) for view in views for layer in view["layers"]}
    view_lookup = {view["id"]: view for view in spec["views"]}
    guides = []
    for guide in spec["guides"]:
        scope = guide.get("view_id")
        candidates = [name for name, (view_id, layer) in layers.items()
                      if layer["legend"]["visible"] and (scope is None or view_id == scope)]
        selected = guide["layer_ids"] or candidates
        order = guide["order"] or selected
        result = {key: deepcopy(value) for key, value in guide.items() if key not in {"layer_ids", "order", "labels", "style"}}
        local_scopes = scopes + ([view_lookup[scope]["style"]] if scope is not None else [])
        result["style"] = resolver.resolve(guide["id"], "legend", local_scopes, guide["style"])
        result["entries"] = [{"layer_id": name, "label": guide["labels"].get(name, layers[name][1]["legend"]["label"]),
                              "marks": deepcopy(layers[name][1]["marks"])} for name in order]
        if result["visible"] and not result["entries"]:
            fail("figure_empty_legend", "Visible legends require at least one eligible semantic layer.", "/guides", "legend_membership")
        guides.append(result)
    return guides


def _data_qa(spec: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    scales = {scale["id"]: scale for scale in spec["scales"]}
    warnings = []
    for view in spec["views"]:
        for layer in view["layers"]:
            columns = datasets[layer["dataset_id"]]["columns"]
            xs, ys = (columns[layer["mappings"][axis]]["values"] for axis in ("x", "y"))
            x_domain, y_domain = (scales[layer[axis + "_scale"]]["domain"] for axis in ("x", "y"))
            pairs = [(x, y) for x, y in zip(xs, ys, strict=True) if x is not None and y is not None]
            visible = [(x, y) for x, y in pairs if x_domain[0] <= x <= x_domain[1] and y_domain[0] <= y <= y_domain[1]]
            if not visible:
                fail("figure_empty_visible_layer", "Every layer must have at least one visible paired measurement.",
                    "/views/layers", "visible_data", layer_id=layer["id"])
            if len(visible) < len(pairs):
                warnings.append({"code": "data_outside_explicit_domain", "semantic_id": layer["id"],
                                 "point_count": len(pairs) - len(visible)})
            for mark in layer["marks"]:
                if mark["type"] == "bar" and not y_domain[0] <= mark["baseline"] <= y_domain[1]:
                    fail("figure_bar_baseline_domain", "A bar baseline must lie within its explicit y scale domain.", "/views/layers/marks", "baseline_domain")
    return warnings


def compile_figure(spec: Any, datasets: dict[str, dict[str, Any]], *, scientific_hash: str,
                   presentation_hash: str, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve supplied datasets and verify pinned rendering resources/algorithms.

    No user-source/native file reads, scientific algorithm execution, native
    object paths, clocks or implicit backend style defaults enter this boundary.
    """
    from .ir import seal_ir_v2

    spec = validate_figure_spec(spec)
    require_capabilities(spec, capabilities if capabilities is not None else {
        "marks": list(MARK_TYPES), "scale_transforms": ["linear", "log"], "multi_view": True, "multiple_scales": True})
    validate_bound_data(spec, datasets)
    data_warnings = _data_qa(spec, datasets)
    resolver = StyleResolver(spec)
    scales = {item["id"]: item for item in spec["scales"]}
    scopes = [spec["theme"]["project"], spec["theme"]["figure"]]
    views = []
    flat_axes = []
    for view in spec["views"]:
        view_scopes = scopes + [view["style"]]
        result: dict[str, Any] = {"id": view["id"], "panel_label": view["panel_label"],
            "panel_label_style": resolver.resolve(view["id"] + ":panel-label", "annotation", view_scopes, {"align_h": "left", "align_v": "center"}),
            "axes": [], "layers": []}
        if resolver.binding is not None:
            trace = resolver.trace[view["id"] + ":panel-label"]
            contract = require_binding(resolver.binding)
            for field, property_key in (("font_weight", "panel_label.weight"),
                                        ("font_size_pt", "panel_label.font_size_pt")):
                if trace[field]["source"] == "RenderingStyleContract":
                    entry = deepcopy(contract["properties"][property_key])
                    result["panel_label_style"][field] = entry["value"]
                    trace[field] = {**entry, "source": "RenderingStyleContract", "contract_property": property_key,
                                    "contract_id": contract["contract_id"], "content_hash": contract["content_hash"]}
            for key in ("align_h", "align_v"):
                trace[key]["source"] = "composition policy"
        for axis in view["axes"]:
            resolved = deepcopy(axis)
            resolved.update(view_id=view["id"], style=resolver.resolve(axis["id"], "axis", view_scopes, axis["style"]),
                            tick_labels=deepcopy(axis.get("tick_labels", [format(value, ".6g") for value in axis["ticks"]])))
            if resolver.binding is not None:
                axis_flow(resolved, scales[axis["scale_id"]], resolver, explicit_labels="tick_labels" in axis)
            result["axes"].append(resolved)
            flat_axes.append(resolved)
        layer_order = view["layers"] if resolver.binding is not None else sorted(view["layers"], key=lambda item: item["z_order"])
        for series_index, layer in enumerate(layer_order):
            resolved = {key: deepcopy(value) for key, value in layer.items() if key != "style"}
            for mark in resolved["marks"]:
                mark["style"] = resolver.resolve(mark["id"], mark["type"], view_scopes + [layer["style"]], mark["style"], index=series_index)
            result["layers"].append(resolved)
        views.append(result)
    guides = _guides(spec, views, scopes, resolver)
    layout_input, panel_margins = resolved_layout_input(spec)
    layout = solve_layout({**spec["composition"], **layout_input}, spec["views"], flat_axes, guides, panel_margins_mm=panel_margins)
    if resolver.binding is not None:
        resolve_house_legends(spec, guides, datasets, layout)
    axes = {axis["id"]: axis for axis in resolve_axis_text(layout, flat_axes, spec["scales"])}
    for view in views:
        view["axes"] = [axes[axis["id"]] for axis in view["axes"]]
    guides = resolve_guides(layout, guides)
    if resolver.binding is not None:
        for view in views:
            for axis in view["axes"]:
                for key in ("tick_positions_mm", "label_position_mm", "label_angle", "tick_alignment"):
                    axis.pop(key)
                if axis["tick_notation"] != "labels":
                    axis.pop("tick_labels")
        for guide in guides:
            if guide.get("text_layout") == "legend-metric-flow":
                guide.pop("rect_mm")
                for entry in guide["entries"]:
                    entry.pop("symbol_mm")
                    entry.pop("label_mm")
    annotations = _annotations(spec, layout, scopes, resolver)
    qa = structural_publication_qa(layout, annotations=annotations)
    qa["soft"].extend(data_warnings)
    if qa["hard"]:
        fail("figure_publication_qa_failed", "Resolved figure geometry violates deterministic publication checks.",
             "/layout", "publication_qa", issues=qa["hard"])
    background = "#ffffff"
    if resolver.binding is not None:
        native_background = contract_value("canvas.background", resolver.binding)
        background = {"white": "#ffffff"}.get(native_background, native_background)
        resolver.trace["figure:background"] = {"value": spec["theme"].get("background_color", background),
            "source": "figure override" if "background_color" in spec["theme"] else "RenderingStyleContract",
            "contract_property": "canvas.background", "source_value": native_background}
        resolver.trace["figure:layout"] = {key: {"value": value, "source": "figure override" if key in spec["layout"]
            else "composition policy" if "composition_policy" in spec else "RenderingStyleContract"}
            for key, value in layout_input.items()}
        resolver.trace["figure:panel_margins_mm"] = {"value": panel_margins, "source": "RenderingStyleContract"}
    return seal_ir_v2({"kind": "sciplot_plot_ir", "schema_version": 2, "scientific_hash": scientific_hash,
        "presentation_hash": presentation_hash, "figure": {"id": spec["id"], "background_color": spec["theme"].get("background_color", background).lower()},
        "datasets": deepcopy(datasets), "scales": deepcopy(spec["scales"]), "views": views,
        "layout": layout, "guides": guides, "annotations": annotations, "layout_qa": qa,
        **({"rendering_contract": resolver.binding, "style_provenance": resolver.trace,
            **({"composition_policy": spec["composition_policy"]} if "composition_policy" in spec else {})}
           if resolver.binding is not None else {})})
