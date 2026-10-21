"""Reserve the existing fixed summary legend above complete original bar/SD marks."""
from __future__ import annotations

import math
from typing import Any

from sciplot_core.mapping_contract.categorical import validate_categorical_context
from sciplot_core.policy.frame_export import DEFAULT_LEGEND_CURVE_CLEARANCE_MM
from sciplot_core.studio_render.categorical_legend import categorical_legend_axis
from sciplot_core.studio_render.categorical_plot_spec import _categorical_plot_contract
from sciplot_core.studio_render.component_legend import component_legend_spec
from sciplot_core.studio_render.legend_placement import _legend_footprint, _point_rectangle_distance_mm
from sciplot_core.studio_render.models import StudioSeries
from sciplot_core.studio_render.style_contract import _veusz_style_contract


def ordinary_grouped_summary(request: dict[str, Any], *, template_id: str) -> bool:
    binding = request.get("categorical_binding")
    return (isinstance(binding, dict) and template_id == "bar"
        and binding.get("mode") in {"mean_sample_sd", "mean_sample_sd_n"}
        and binding.get("condition_column") is not None)


def segmented_legend_placement(series: list[StudioSeries], options: dict[str, Any], *,
                               request: dict[str, Any], template_id: str,
                               source_bindings: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_categorical_context(request)
    categorical = _categorical_plot_contract(series, template_id=template_id, render_options=options, source_bindings=source_bindings)
    if not isinstance(categorical, dict) or categorical.get("presentation_kind") != "grouped_bar_error":
        raise ValueError("Ordinary segmented legend clearance requires the existing grouped mean/SD bar contract.")
    legend = component_legend_spec(categorical, style=_veusz_style_contract(options))
    if legend is None or not legend["rows"]:
        raise ValueError("The original summary legend has no complete fixed row geometry.")
    axis = categorical_legend_axis(series, options, request=request, template_id=template_id, source_bindings=source_bindings)
    if axis.y_min is None or axis.y_max is None or axis.y_max <= axis.y_min:
        raise ValueError("The final summary axis has no finite positive span.")
    footprint = _legend_footprint(series, options)
    width, height = float(footprint["graph_width_mm"]), float(footprint["graph_height_mm"])
    half_height = max(float(footprint["font_height_mm"]) / height,
                      float(legend["swatch_height_fraction"])) / 2
    bottom = min(float(row["y_fraction"]) for row in legend["rows"]) - half_height
    highest = max(float(group["bar_mean"]) + float(group["bar_error"]) for group in categorical["groups"])
    top = (highest - axis.y_min) / (axis.y_max - axis.y_min)
    # A full-width band conservatively covers the existing row text and swatches;
    # complete bars run continuously from zero to their mean, with SD above it.
    radius = max(float(categorical["visual_style"][key])
        for key in ("bar_line_width_pt", "error_line_width_pt")) * math.sqrt(2) * 25.4 / 144
    distance = max(0.0, _point_rectangle_distance_mm((.5, min(top, 1.0)),
        (0.0, 1.0, bottom, 1.0), graph_width_mm=width, graph_height_mm=height) - radius)
    required = float(options.get("legend_curve_clearance_mm") or DEFAULT_LEGEND_CURVE_CLEARANCE_MM)
    metric = {"rectangle_fraction": [0.0, 1.0, bottom, 1.0],
        "minimum_curve_clearance_mm": distance, "overlap_samples": int(distance <= 0),
        "near_samples": int(distance < required), "clearance_deficit_mm": max(required - distance, 0),
        "proximity_load": max((required - distance) / required, 0)}
    return {"position": "upper_left", "method": "existing_segmented_legend_top_band_final_axes_v1",
        "overlap_depth_mm": max((top - bottom) * height + radius, 0.0),
        "required_curve_clearance_mm": required, "minimum_curve_clearance_mm": distance,
        "clearance_status": "safe" if distance >= required else "best_available_needs_reserve",
        "measurement_axes": {"x": [axis.x_min, axis.x_max], "y": [axis.y_min, axis.y_max]},
        "footprint": {**footprint, "box_width_mm": width, "box_height_mm": (1-bottom) * height},
        "candidates": {"upper_left": metric, "upper_right": metric}}
