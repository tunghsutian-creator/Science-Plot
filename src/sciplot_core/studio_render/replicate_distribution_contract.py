"""Build the categorical contract for replicate distributions."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_BAR_FILL_TRANSPARENCY,
    CATEGORICAL_BAR_LINE_WIDTH_PT,
    CATEGORICAL_BAR_WIDTH_FRACTION,
    CATEGORICAL_BOX_FILL_FRACTION,
    CATEGORICAL_BOX_FILL_TRANSPARENCY,
    CATEGORICAL_BOX_LINE_WIDTH_PT,
    CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
    CATEGORICAL_GROUPED_BAR_WIDTH_FRACTION,
    DEFAULT_CATEGORICAL_SUMMARY,
    DEFAULT_PALETTE_PRESET,
    MIN_BOX_REPLICATES,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    categorical_box_native_fill_scale,
    categorical_component_fill_color,
    categorical_fill_color,
    categorical_keyline_color,
    normalize_categorical_summary,
)
from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
    StudioSeries,
)
from sciplot_core.studio_render.categorical_values import (
    _mean_and_sample_sd,
)
from sciplot_core.studio_render.categorical_groups import (
    _grouped_bar_identity,
)
from sciplot_core.studio_render.template_resolution import (
    _quantile,
)


def _replicate_distribution_contract(
    series: list[StudioSeries],
    *,
    template_id: str,
    render_options: dict[str, Any],
) -> dict[str, Any] | None:
    categorical = [
        item
        for item in series
        if item.presentation_kind
        in {"categorical_replicates", "categorical_grouped_replicates"}
    ]
    if not categorical:
        return None
    grouped_bar = any(
        item.presentation_kind == "categorical_grouped_replicates"
        for item in categorical
    )
    if grouped_bar and (
        template_id != "bar"
        or any(
            item.presentation_kind != "categorical_grouped_replicates"
            for item in categorical
        )
    ):
        raise StudioPreparationBlocked(
            "grouped_replicates_require_bar",
            "Grouped categorical replicates are supported only by the bar template.",
        )
    grouped_condition_labels: list[str] = []
    if grouped_bar:
        for item in categorical:
            _sample, condition = _grouped_bar_identity(item.label)
            if condition not in grouped_condition_labels:
                grouped_condition_labels.append(condition)
    summary_statistic = normalize_categorical_summary(
        render_options.get("summary_statistic") or DEFAULT_CATEGORICAL_SUMMARY
    )
    box_fill_fraction = float(
        render_options.get(
            "_categorical_box_fill_fraction",
            CATEGORICAL_BOX_FILL_FRACTION,
        )
    )
    category_slot_width_mm = float(
        render_options.get("_categorical_slot_width_mm") or 0.0
    )
    box_width_mm = float(render_options.get("_categorical_box_width_mm") or 0.0)
    box_native_fill_scale = float(
        render_options.get("_categorical_box_native_fill_scale")
        or categorical_box_native_fill_scale(category_count=len(categorical))
    )
    box_aspect_constraint = render_options.get("_categorical_box_aspect_constraint")
    marker_diameter_mm = 2.0 * UNIFIED_MARKER_SIZE_PT * 25.4 / 72.0
    groups: list[dict[str, Any]] = []
    for index, item in enumerate(categorical, start=1):
        sample_label = item.label
        condition_label: str | None = None
        condition_index = 0
        if grouped_bar:
            sample_label, condition_label = _grouped_bar_identity(item.label)
            condition_index = grouped_condition_labels.index(condition_label)
        values = [
            float(value) for value in item.y_values if math.isfinite(float(value))
        ]
        bar_statistics: dict[str, float | str] = {}
        if template_id == "bar":
            mean, error = _mean_and_sample_sd(values)
            bar_statistics = {
                "bar_mean": mean,
                "bar_error": error,
                "bar_error_statistic": "sd",
            }
        position = float(
            item.category_position if item.category_position is not None else index
        )
        eligible = (
            summary_statistic == "median_iqr" and len(values) >= MIN_BOX_REPLICATES
        )
        q1 = _quantile(values, 0.25)
        median = _quantile(values, 0.5)
        q3 = _quantile(values, 0.75)
        raw_point_half_spread = max(
            (
                abs(float(value) - position)
                for value in item.x_values
                if math.isfinite(float(value))
            ),
            default=0.0,
        )
        raw_point_band_fraction = 2.0 * raw_point_half_spread
        inside_iqr_count = sum(q1 <= value <= q3 for value in values)
        groups.append(
            {
                "label": item.label,
                "sample_label": sample_label,
                "condition_label": condition_label,
                "condition_index": condition_index,
                "color": item.color,
                "fill_color": (
                    categorical_component_fill_color(
                        item.color,
                        component_index=(
                            len(grouped_condition_labels) - 1 - condition_index
                        ),
                        component_count=len(grouped_condition_labels),
                    )
                    if grouped_bar
                    else categorical_fill_color(item.color)
                ),
                "keyline_color": categorical_keyline_color(item.color),
                "position": position,
                "y_name": item.y_name,
                "raw_values": values,
                "replicate_count": len(values),
                "raw_point_half_spread": raw_point_half_spread,
                "raw_point_band_fraction": raw_point_band_fraction,
                "raw_point_band_width_mm": (
                    raw_point_band_fraction * category_slot_width_mm
                ),
                "raw_point_box_width_ratio": (
                    raw_point_band_fraction / box_fill_fraction
                    if box_fill_fraction > 0.0
                    else 0.0
                ),
                "raw_points_within_box_width": (
                    raw_point_half_spread <= box_fill_fraction * 0.5 + 1e-12
                ),
                "raw_marker_glyphs_within_box_width": (
                    raw_point_band_fraction * category_slot_width_mm
                    + marker_diameter_mm
                    <= box_width_mm + 1e-12
                ),
                "inside_iqr_count": inside_iqr_count,
                "inside_iqr_fraction": inside_iqr_count / len(values),
                "boxplot_eligible": eligible,
                "summary_status": (
                    "bar_error"
                    if template_id == "bar"
                    else "boxplot"
                    if eligible
                    else "raw_only"
                    if summary_statistic == "raw_only"
                    else "insufficient_replicates"
                ),
                "descriptive_statistics": {
                    "minimum": min(values),
                    "q1": q1,
                    "median": median,
                    "q3": q3,
                    "maximum": max(values),
                },
                **bar_statistics,
                "raw_points_visible": (
                    template_id == "box_strip"
                    or summary_statistic == "raw_only"
                    or len(values) < MIN_BOX_REPLICATES
                ),
            }
        )
    return {
        "kind": "sciplot_categorical_replicate_contract",
        "version": 2,
        "presentation_kind": (
            "grouped_bar_error"
            if grouped_bar
            else "bar_error"
            if template_id == "bar"
            else "box_strip"
            if template_id == "box_strip"
            else "box"
        ),
        "summary_statistic": summary_statistic,
        "minimum_box_replicates": MIN_BOX_REPLICATES,
        "quartile_method": "linear_interpolation_at_(n_minus_1)_times_p",
        "box_definition": "q1_to_q3_middle_50_percent_interval",
        "box_whisker_mode": "1.5IQR",
        "box_aspect_constraint": (
            dict(box_aspect_constraint)
            if isinstance(box_aspect_constraint, dict)
            else None
        ),
        "mean_marker_visible": False,
        **({"bar_error_statistic": "sd"} if template_id == "bar" else {}),
        "condition_labels": grouped_condition_labels,
        "condition_count": len(grouped_condition_labels),
        "sample_color_binding": ("categorical_root_by_sample" if grouped_bar else None),
        "condition_tone_binding": (
            "ordered_opaque_lightness_within_sample" if grouped_bar else None
        ),
        "native_veusz_boxplot": summary_statistic == "median_iqr"
        and template_id != "bar"
        and any(group["boxplot_eligible"] for group in groups),
        "raw_values_preserved": True,
        "raw_replicate_count": sum(group["replicate_count"] for group in groups),
        "visual_style": {
            "palette_policy": (
                "sample_roots_with_condition_tones"
                if grouped_bar
                else "relaxed_multi_category"
            ),
            "palette_preset": str(
                render_options.get("palette_preset") or DEFAULT_PALETTE_PRESET
            ),
            "box_fill_mode": "series_color",
            "box_fill_transparency": CATEGORICAL_BOX_FILL_TRANSPARENCY,
            "box_fill_fraction": box_fill_fraction,
            "box_native_fill_scale": box_native_fill_scale,
            "box_width_policy": (
                "min(categorical_bar_width_times_4_over_3,data_iqr_physical_aspect_cap)"
            ),
            "category_count": len(groups),
            "category_slot_width_mm": category_slot_width_mm,
            "box_width_mm": box_width_mm,
            "raw_marker_diameter_mm": marker_diameter_mm,
            "raw_point_band_policy": (
                "min(box_ratio_log2_replicates,box_width_minus_one_marker_diameter)"
            ),
            "raw_point_position_policy": "stable_hash_shuffled_even_slots",
            "raw_point_layout": str(
                render_options.get("_categorical_raw_point_layout") or "fixed"
            ),
            "box_line_mode": str(render_options.get("box_line_mode") or "series_color"),
            "raw_point_color_mode": "series_color",
            "raw_point_alpha": float(render_options.get("marker_alpha", 0.80)),
            "box_line_width_pt": CATEGORICAL_BOX_LINE_WIDTH_PT,
            "bar_width_fraction": (
                CATEGORICAL_GROUPED_BAR_WIDTH_FRACTION
                if grouped_bar
                else CATEGORICAL_BAR_WIDTH_FRACTION
            ),
            "native_barfill": (1.0 if grouped_bar else CATEGORICAL_BAR_WIDTH_FRACTION),
            "bar_fill_transparency": CATEGORICAL_BAR_FILL_TRANSPARENCY,
            "bar_line_width_pt": CATEGORICAL_BAR_LINE_WIDTH_PT,
            "error_cap_to_bar_ratio": CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
            "error_line_width_pt": UNIFIED_LINE_WIDTH_PT,
        },
        "groups": groups,
        "insufficient_replicate_groups": [
            group["label"]
            for group in groups
            if group["summary_status"] == "insufficient_replicates"
        ],
    }
