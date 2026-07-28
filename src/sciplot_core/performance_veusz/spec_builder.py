"""Assemble the renderer-neutral performance Veusz specification."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.performance_comparison import (
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PERFORMANCE_SCATTER_TEMPLATE_ID,
)
from sciplot_core.policy import (
    FIXED_PUBLICATION_FRAME_POLICY,
)

from sciplot_core.performance_veusz.style import (
    _RADAR_AXIS_LIMIT,
    _style_payload,
    _axis_payload,
    _expanded_axis_bounds,
    _performance_render_options,
    _inside_legend_contract,
)

from sciplot_core.performance_veusz.geometry import (
    performance_series_records,
    _performance_polygons,
    _performance_lines,
)

from sciplot_core.performance_veusz.labels import (
    _performance_labels,
)


def build_performance_veusz_spec(
    *,
    payload: dict[str, Any],
    request: dict[str, Any],
    transform_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the exact-current native Veusz spec for one comparison figure."""

    template = str(payload["template"])
    layout = payload["layout"]
    margins = layout["graph_margins_mm"]
    style = _style_payload(margins)
    if template == PERFORMANCE_SCATTER_TEMPLATE_ID:
        x_minimum, x_maximum = _expanded_axis_bounds(
            payload,
            request,
            axis="x",
        )
        y_minimum, y_maximum = _expanded_axis_bounds(
            payload,
            request,
            axis="y",
        )
        axes = {
            "x": _axis_payload(
                label=str(payload["x_label"]),
                minimum=x_minimum,
                maximum=x_maximum,
                hidden=False,
            ),
            "y": _axis_payload(
                label=str(payload["y_label"]),
                minimum=y_minimum,
                maximum=y_maximum,
                hidden=False,
            ),
        }
    elif template == PERFORMANCE_RADAR_TEMPLATE_ID:
        axes = {
            "x": _axis_payload(
                label="",
                minimum=-_RADAR_AXIS_LIMIT,
                maximum=_RADAR_AXIS_LIMIT,
                hidden=True,
            ),
            "y": _axis_payload(
                label="",
                minimum=-_RADAR_AXIS_LIMIT,
                maximum=_RADAR_AXIS_LIMIT,
                hidden=True,
            ),
        }
    else:
        raise ValueError(f"Unsupported performance template: {template}")
    render_options = {
        **_performance_render_options(payload, request),
        "size": "x".join(f"{float(value):g}" for value in layout["page_size_mm"]),
    }
    performance = {
        **json_safe(payload),
        "polygons": _performance_polygons(payload),
        "lines": _performance_lines(payload),
        "labels": _performance_labels(payload),
        "radar_coordinate_model": (
            {
                "kind": "cartesian_physical_circle",
                "x_compensation": (
                    float(layout["plot_region_mm"][1])
                    / float(layout["plot_region_mm"][0])
                ),
                "axis_limit": _RADAR_AXIS_LIMIT,
                "declared_normalized_radius": [0.0, 1.0],
            }
            if template == PERFORMANCE_RADAR_TEMPLATE_ID
            else None
        ),
    }
    return {
        "kind": "sciplot_veusz_plot_spec",
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "template": template,
        "source_request": json_safe(request),
        "render_options": json_safe(render_options),
        "size_mm": [float(value) for value in layout["page_size_mm"]],
        "frame_alignment": {
            "status": "locked",
            "margin_mode": FIXED_PUBLICATION_FRAME_POLICY.margin_mode,
            "outside_legend_allowed": False,
            "layout_kind": layout["kind"],
            "plot_panel_size_mm": layout["plot_panel_size_mm"],
            "reference_panel_size_mm": layout["legend_panel_size_mm"],
            "plot_region_mm": layout["plot_region_mm"],
            "margins_mm": style["margins_mm"],
        },
        "autofixes_applied": [],
        "visual_extent_axis_clearance": {},
        "layout_issues": [],
        "visual_data_transforms": json_safe(payload.get("visual_data_transforms", [])),
        "terminal_transform_steps": json_safe(transform_steps or []),
        "provenance": {"veusz": "vendored_native_document"},
        "style": style,
        "axes": axes,
        "legend": _inside_legend_contract(payload, request),
        "categorical": None,
        "scalar_field": None,
        "reference_guides": [],
        "series": performance_series_records(payload),
        "direct_labels": [],
        "performance_comparison": performance,
    }
