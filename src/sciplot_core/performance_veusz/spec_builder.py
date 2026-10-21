"""Assemble the renderer-neutral performance Veusz specification."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_core.veusz_numeric_persistence import (
    FLOAT64_ENCODING,
    NUMERIC_ENCODING_KEY,
)
from sciplot_core.source_tables.parsing import (
    DECIMAL_ROUND_TRIP_ENCODING,
    SOURCE_NUMERIC_ENCODING_KEY,
)
from sciplot_core.performance_comparison import (
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PERFORMANCE_SCATTER_TEMPLATE_ID,
)
from sciplot_core.performance_comparison.radar import validate_radar_presentation_size
from sciplot_core.policy.layout_policy import FIXED_PUBLICATION_FRAME_POLICY

from sciplot_core.performance_veusz.style import (
    _RADAR_AXIS_LIMIT,
    _style_payload,
    _axis_payload,
    _expanded_axis_bounds,
    _performance_render_options,
    _inside_legend_contract,
    _literal_text,
)

from sciplot_core.performance_veusz.geometry import (
    performance_series_records,
    _performance_polygons,
    _performance_lines,
)

from sciplot_core.performance_veusz.labels import (
    _performance_labels,
)


def _selected_axis_label(payload: dict[str, Any], axis: str) -> str:
    label = str(payload[f"{axis}_label"])
    metric = payload[f"{axis}_metric"]
    if metric["metric_id"] not in payload.get("literal_metric_labels", []):
        return label
    display_label = str(metric["display_label"])
    if not label.startswith(display_label):
        raise ValueError(
            "Selected performance axis label does not match its original Metric ID."
        )
    # Escape only an implicit original identifier. The unit suffix and any
    # explicitly declared DisplayLabel retain their scientific typesetting.
    return (
        _literal_text(display_label, format_units=False) + label[len(display_label) :]
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
    validate_radar_presentation_size(payload, request)
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
                label=_selected_axis_label(payload, "x"),
                minimum=x_minimum,
                maximum=x_maximum,
                hidden=False,
            ),
            "y": _axis_payload(
                label=_selected_axis_label(payload, "y"),
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
    if template == PERFORMANCE_SCATTER_TEMPLATE_ID:
        for name in ("x", "y"):
            if payload[f"{name}_metric"]["metric_id"] in payload.get(
                "literal_metric_labels", []
            ):
                axes[name]["label_text_policy"] = (
                    "literal_identifier_with_formatted_unit"
                )
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
        NUMERIC_ENCODING_KEY: FLOAT64_ENCODING,
        **(
            {SOURCE_NUMERIC_ENCODING_KEY: DECIMAL_ROUND_TRIP_ENCODING}
            if "performance_selection" in payload
            else {}
        ),
        "created_at": utc_now_iso(),
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
