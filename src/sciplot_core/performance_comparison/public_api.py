"""Prepare performance payloads and summarize transform parameters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.source_tables.parsing import DECIMAL_ROUND_TRIP_ENCODING

from sciplot_core.performance_comparison.models import (
    PERFORMANCE_SCATTER_TEMPLATE_ID,
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PerformanceComparisonError,
)

from sciplot_core.performance_comparison.source_loading import (
    load_performance_comparison,
)

from sciplot_core.performance_comparison.scatter import (
    build_performance_scatter_payload,
)

from sciplot_core.performance_comparison.radar import (
    build_performance_radar_payload,
)


def prepare_performance_comparison(
    source: str | Path,
    *,
    template_id: str,
    selection: dict[str, Any] | None = None,
    source_numeric_encoding: str = DECIMAL_ROUND_TRIP_ENCODING,
    compatibility_fused_digits: bool | None = True,
) -> dict[str, Any]:
    """Return the validated source-bound payload for one production template."""

    if selection is not None and template_id != PERFORMANCE_SCATTER_TEMPLATE_ID:
        raise PerformanceComparisonError("performance_selection_template_invalid", "Explicit X/Y metric selection supports the scatter template.")
    comparison = load_performance_comparison(source, selection=selection, source_numeric_encoding=source_numeric_encoding,
                                             compatibility_fused_digits=compatibility_fused_digits)
    if template_id == PERFORMANCE_SCATTER_TEMPLATE_ID:
        if selection is not None:
            from sciplot_core.performance_comparison.selected_scatter import build_selected_scatter_payload
            return build_selected_scatter_payload(comparison)
        return build_performance_scatter_payload(comparison)
    if template_id == PERFORMANCE_RADAR_TEMPLATE_ID:
        return build_performance_radar_payload(comparison)
    raise PerformanceComparisonError(
        "performance_template_invalid",
        "Performance comparisons support the scatter and polar_curve "
        f"(radar) templates, not {template_id!r}.",
    )


def performance_transform_parameters(payload: dict[str, Any]) -> dict[str, Any]:
    """Return lineage parameters shared by Studio and workflow evidence."""

    result = {
        "template": payload["template"],
        "source_sha256": payload["source_sha256"],
        "source_row_count": payload["source_row_count"],
        "material_count": payload["material_count"],
        "sample_count": payload["sample_count"],
        "reference_count": payload["reference_count"],
        "series_count": payload.get(
            "series_count",
            len(payload.get("series", [])),
        ),
        "legend_item_count": payload.get(
            "legend_item_count",
            len(payload.get("legend_items", [])),
        ),
        "legend_panel_reserved": bool(
            payload.get("layout", {}).get("legend_uses_reserved_panel")
        ),
        "plot_region_mm": payload.get("layout", {}).get("plot_region_mm"),
        "scientific_values_modified": False,
    }
    if "performance_selection" in payload:
        result.update({key: payload[key] for key in (
            "performance_selection", "source_material_count", "selected_row_count",
            "excluded_metrics", "valid_pair_count", "missing_pair_count", "source_observations",
        )})
    if payload["template"] == PERFORMANCE_SCATTER_TEMPLATE_ID:
        result.update(
            {
                "x_metric": payload["x_metric"]["metric_id"],
                "y_metric": payload["y_metric"]["metric_id"],
                "sample_envelope_method": (
                    "deterministic irregular smoothed enclosure with "
                    "normalized-axis padding; circle/capsule fallback"
                ),
                "sample_envelope_border": "hidden",
                "repeated_x_visual_jitter": payload.get(
                    "visual_data_transforms",
                    [],
                ),
                "sample_envelope_groups": [
                    {
                        "group": item["group"],
                        "members": item["members"],
                    }
                    for item in payload["envelopes"]
                ],
            }
        )
    else:
        result.update(
            {
                "metric_ids": [
                    item["metric_id"] for item in payload.get("metrics", [])
                ],
                "normalization": payload.get("normalization"),
                "sample_polygons_filled": True,
                "reference_series_markers_only": True,
            }
        )
    return cast(dict[str, Any], json_safe(result))
