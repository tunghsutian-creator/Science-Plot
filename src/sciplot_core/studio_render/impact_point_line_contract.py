"""Build the categorical contract for impact point-line overlays."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_BAR_WIDTH_FRACTION,
    CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
    IMPACT_POINT_LINE_CONDITION_OFFSET_FRACTION,
    IMPACT_POINT_LINE_MEAN_MARKER_EDGE_COLOR,
    IMPACT_POINT_LINE_MEAN_MARKER_EDGE_WIDTH_PT,
    IMPACT_POINT_LINE_RAW_MARKER_ALPHA,
    IMPACT_POINT_LINE_RAW_MARKER_SCALE,
    UNIFIED_LINE_WIDTH_PT,
)
from sciplot_core.studio_render.models import (
    IMPACT_POINT_LINE_SUMMARY_KIND,
    IMPACT_POINT_LINE_RAW_KIND,
    StudioPreparationBlocked,
    StudioSeries,
)


def _impact_point_line_contract(
    series: list[StudioSeries],
    *,
    template_id: str,
) -> dict[str, Any] | None:
    impact_summary = [
        item
        for item in series
        if item.presentation_kind == IMPACT_POINT_LINE_SUMMARY_KIND
    ]
    if impact_summary:
        if template_id != "point_line":
            raise StudioPreparationBlocked(
                "impact_point_line_template_mismatch",
                "Impact condition summary lines require the point_line template.",
            )
        sample_labels = impact_summary[0].component_labels
        positions = tuple(float(index) for index in range(1, len(sample_labels) + 1))
        condition_offsets = tuple(
            float(item.x_values[0]) - positions[0] if item.x_values else math.nan
            for item in impact_summary
        )
        if not sample_labels or any(
            item.component_labels != sample_labels
            or len(item.x_values) != len(sample_labels)
            or len(item.y_values) != len(sample_labels)
            or len(item.error_values) != len(sample_labels)
            or any(
                not math.isclose(
                    float(x_value),
                    positions[index] + condition_offsets[condition_index],
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                for index, x_value in enumerate(item.x_values)
            )
            for condition_index, item in enumerate(impact_summary)
        ):
            raise StudioPreparationBlocked(
                "invalid_impact_point_line_contract",
                "Impact condition lines must share one ordered categorical sample axis.",
            )
        raw_series = [
            item
            for item in series
            if item.presentation_kind == IMPACT_POINT_LINE_RAW_KIND
        ]
        error_bars = [
            {
                "condition_label": item.label,
                "sample_label": sample_labels[index],
                "position": float(position),
                "mean": float(item.y_values[index]),
                "error": float(item.error_values[index]),
                "low": float(item.y_values[index] - item.error_values[index]),
                "high": float(item.y_values[index] + item.error_values[index]),
                "color": item.color,
            }
            for item in impact_summary
            for index, position in enumerate(item.x_values)
        ]
        groups = [
            {
                "label": label,
                "position": float(position),
                "y_name": impact_summary[0].y_name,
                "raw_points_visible": True,
                "boxplot_eligible": False,
                "descriptive_statistics": {
                    "minimum": min(
                        float(item.y_values[index]) for item in impact_summary
                    ),
                    "q1": float(impact_summary[0].y_values[index]),
                    "median": float(impact_summary[0].y_values[index]),
                    "q3": float(impact_summary[0].y_values[index]),
                    "maximum": max(
                        float(item.y_values[index]) for item in impact_summary
                    ),
                },
            }
            for index, (label, position) in enumerate(
                zip(sample_labels, positions, strict=True)
            )
        ]
        return {
            "kind": "sciplot_impact_point_line_overlay_contract",
            "version": 3,
            "presentation_kind": "point_line_raw_overlay",
            "summary_statistic": "arithmetic_mean",
            "error_bar_statistic": "sample_sd",
            "native_veusz_boxplot": False,
            "raw_values_preserved": True,
            "raw_replicate_count": sum(len(item.y_values) for item in raw_series),
            "condition_labels": [item.label for item in impact_summary],
            "condition_offsets": list(condition_offsets),
            "sample_labels": list(sample_labels),
            "error_bars": error_bars,
            "groups": groups,
            "visual_style": {
                "palette_policy": "condition_roots_control_black_then_blue",
                "raw_point_color_mode": ("lightened_condition_root_with_transparency"),
                "raw_point_position_policy": "stable_hash_shuffled_even_slots",
                "raw_point_condition_offset": True,
                "condition_offset_fraction": (
                    IMPACT_POINT_LINE_CONDITION_OFFSET_FRACTION
                ),
                "raw_point_alpha": IMPACT_POINT_LINE_RAW_MARKER_ALPHA,
                "raw_marker_scale": IMPACT_POINT_LINE_RAW_MARKER_SCALE,
                "sample_marker_binding": "stable_by_sample_axis_position",
                "mean_marker_edge_color": (IMPACT_POINT_LINE_MEAN_MARKER_EDGE_COLOR),
                "mean_marker_edge_width_pt": (
                    IMPACT_POINT_LINE_MEAN_MARKER_EDGE_WIDTH_PT
                ),
                "error_cap_to_bar_ratio": CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
                "error_cap_reference_width_fraction": CATEGORICAL_BAR_WIDTH_FRACTION,
                "error_line_width_pt": UNIFIED_LINE_WIDTH_PT,
            },
        }
    return None
