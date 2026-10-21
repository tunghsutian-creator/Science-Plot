"""Current-view endpoint rules own bounds; numeric domains/ticks are projections.

This boundary reads only already resolved datasets. It never loads sources,
executes transforms, persists a document, or changes historical unmarked specs.
"""
from typing import Any

from sciplot_core.plot_document.errors import fail

from .mark_geometry import extent_values, layer_geometry, window_intersects
from .domain_values import numeric_axis
from .validation import validate_bound_data, validate_figure_spec

DOMAIN_SEMANTICS = "current_view_v1"


def is_current_view(spec: dict[str, Any]) -> bool:
    return spec.get("domain_semantics") == DOMAIN_SEMANTICS


def _geometries(spec: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    scales = {scale["id"]: scale for scale in spec["scales"]}
    result = {}
    for view in spec["views"]:
        for layer in view["layers"]:
            geometry = layer_geometry(layer, datasets)
            for dimension in ("x", "y"):
                scale = scales[layer[dimension + "_scale"]]
                if scale["transform"] == "log" and any(value <= 0 for value in extent_values(geometry, dimension)):
                    fail("figure_log_geometry_domain", "Every drawable data-space coordinate must be positive on a log scale, including hidden bars and baselines.",
                         "/views/layers/marks", "log_geometry", layer_id=layer["id"], scale_id=scale["id"])
            result[layer["id"]] = geometry
    return result


def resolve_current_view(value: Any, datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Accept pending old numeric projections, return a complete sealable spec.

    Only this writer derives numeric current-view domains and automatic ticks.
    Fixed tick conflicts reject the whole candidate; no user tick is discarded.
    """
    spec = validate_figure_spec(value, pending_domains=True)
    if not is_current_view(spec):
        return spec
    validate_bound_data(spec, datasets)
    geometries = _geometries(spec, datasets)
    ticks_by_scale = {}
    for scale in spec["scales"]:
        dimension = scale["dimension"]
        values = [value for view in spec["views"] for layer in view["layers"]
                  if layer.get("visible", True) and layer[dimension + "_scale"] == scale["id"]
                  for value in extent_values(geometries[layer["id"]], dimension)]
        rule = scale["domain_rule"]
        automatic = any(rule[endpoint]["mode"] == "auto" for endpoint in ("minimum", "maximum"))
        if automatic and not values:
            fail("figure_empty_auto_extent", "An automatic endpoint requires visible drawable extent independent of domain-spanning rules.",
                 "/scales/domain_rule", "visible_extent", scale_id=scale["id"])
        endpoints = {name: rule[name].get("value") for name in ("minimum", "maximum")}
        try:
            domain, ticks = numeric_axis(values or [endpoints["minimum"], endpoints["maximum"]],
                quantity=scale["quantity"], transform=scale["transform"], dimension=dimension, **endpoints)
        except (ValueError, OverflowError) as exc:
            fail("figure_current_view_domain", str(exc), "/scales/domain_rule", "resolved_endpoints", scale_id=scale["id"])
        scale["domain"] = domain
        ticks_by_scale[scale["id"]] = ticks
    for view in spec["views"]:
        for axis in view["axes"]:
            if axis["ticks_mode"] == "automatic":
                axis["ticks"] = list(ticks_by_scale[axis["scale_id"]])
            else:
                scale = next(scale for scale in spec["scales"] if scale["id"] == axis["scale_id"])
                outside = [tick for tick in axis["ticks"] if not scale["domain"][0] <= tick <= scale["domain"][1]]
                if outside:
                    fail("figure_fixed_ticks_domain_conflict", "Current bounds would exclude fixed ticks. Revise the tick list or explicitly restore automatic ticks in this same change.",
                         "/views/axes/ticks", "preserve_fixed_ticks", axis_id=axis["id"], ticks=outside)
    return validate_figure_spec(spec)


def validate_current_view_projection(spec: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> None:
    if is_current_view(spec) and resolve_current_view(spec, datasets) != spec:
        fail("figure_stale_domain_projection", "Resolve the current endpoint rules and automatic ticks before sealing or compiling this document.",
             "/scales/domain", "current_projection")


def current_view_qa(spec: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Viewport checks follow actual marks; all-layer scientific checks run first."""
    geometry = _geometries(spec, datasets)
    scales = {scale["id"]: scale for scale in spec["scales"]}
    warnings = []
    for view in spec["views"]:
        for layer in view["layers"]:
            if not layer.get("visible", True):
                continue
            inside = [window_intersects(item, scales[layer["x_scale"]], scales[layer["y_scale"]])
                      for item in geometry[layer["id"]]]
            if not any(inside):
                fail("figure_empty_visible_layer", "Every visible layer must have drawable geometry intersecting its current window.",
                     "/views/layers", "visible_data", layer_id=layer["id"])
            if not all(inside):
                warnings.append({"code": "geometry_outside_current_domain", "semantic_id": layer["id"],
                                 "primitive_count": inside.count(False)})
    return warnings
