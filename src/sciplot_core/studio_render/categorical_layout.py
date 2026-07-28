"""Compute categorical bar and box layout defaults from physical figure geometry."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_BAR_MAX_ERROR_FRACTION,
    CATEGORICAL_BAR_TARGET_MEAN_FRACTION,
    CATEGORICAL_BOX_MIN_MARKER_DIAMETERS,
    CATEGORICAL_BOX_MIN_PHYSICAL_ASPECT_RATIO,
    CATEGORICAL_STACK_TARGET_TOTAL_FRACTION,
    DEFAULT_FIGURE_SIZE,
    MIN_BOX_REPLICATES,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_BOTTOM_MARGIN_MM,
    UNIFIED_TOP_MARGIN_MM,
    categorical_box_width_mm,
    categorical_slot_width_mm,
    compact_linear_axis,
)

from sciplot_core.studio_render.models import (
    StudioSeries,
    _VeuszAxisContract,
)

from sciplot_core.studio_render.categorical_values import (
    _mean_and_sample_sd,
)

from sciplot_core.studio_render.template_resolution import (
    _quantile,
)

from sciplot_core.studio_render.axis_scale import (
    _axis_scale,
)

from sciplot_core.studio_render.value_parsing import (
    _size_mm,
)


def _categorical_bar_axis_defaults(
    series: list[StudioSeries],
) -> dict[str, Any] | None:
    """Give positive bar charts enough headroom for both means and SD bars."""

    component_stacks = [
        item for item in series if item.presentation_kind == "categorical_components"
    ]
    if component_stacks:
        totals: list[float] = []
        for item in component_stacks:
            values = [
                float(value) for value in item.y_values if math.isfinite(float(value))
            ]
            if len(values) != len(item.y_values) or not values or min(values) < 0.0:
                return None
            totals.append(math.fsum(values))
        compact_axis = compact_linear_axis(
            (
                0.0,
                max(totals) / CATEGORICAL_STACK_TARGET_TOTAL_FRACTION,
            ),
            padding_fraction=0.0,
        )
        if compact_axis is None:
            return None
        _axis_min, axis_max, axis_ticks = compact_axis
        return {
            "y_min": 0.0,
            "y_max": float(axis_max),
            "y_ticks": list(axis_ticks),
        }

    groups: list[tuple[float, float]] = []
    for item in series:
        if item.presentation_kind != "categorical_replicates":
            continue
        values = [
            float(value) for value in item.y_values if math.isfinite(float(value))
        ]
        if not values or min(values) < 0.0:
            return None
        mean, error = _mean_and_sample_sd(values)
        groups.append((mean, error))
    if not groups:
        return None
    required_upper = max(
        max(mean for mean, _error in groups) / CATEGORICAL_BAR_TARGET_MEAN_FRACTION,
        max(mean + error for mean, error in groups)
        / CATEGORICAL_BAR_MAX_ERROR_FRACTION,
    )
    compact_axis = compact_linear_axis((0.0, required_upper), padding_fraction=0.0)
    if compact_axis is None:
        return None
    _axis_min, axis_max, axis_ticks = compact_axis
    return {"y_min": 0.0, "y_max": float(axis_max), "y_ticks": list(axis_ticks)}


def _apply_categorical_box_aspect_width(
    render_options: dict[str, Any],
    series: list[StudioSeries],
    *,
    axis_contract: _VeuszAxisContract,
    template_id: str,
) -> dict[str, Any]:
    """Narrow box width toward its data-derived physical IQR height.

    The vertical box extent remains exactly Q1..Q3 on the resolved data axis.
    Only the horizontal width is capped. A marker-capacity floor prevents the
    new aspect rule from collapsing the strip-plot band into a single column.
    """

    updated = dict(render_options)
    if (
        template_id not in {"box", "box_strip"}
        or _axis_scale(updated, "y") != "linear"
        or axis_contract.y_min is None
        or axis_contract.y_max is None
    ):
        return updated

    categorical = [
        item for item in series if item.presentation_kind == "categorical_replicates"
    ]
    axis_span = float(axis_contract.y_max) - float(axis_contract.y_min)
    if not categorical or axis_span <= 0.0:
        return updated

    group_iqrs: list[float] = []
    for item in categorical:
        values = [
            float(value) for value in item.y_values if math.isfinite(float(value))
        ]
        if len(values) < MIN_BOX_REPLICATES:
            continue
        iqr = _quantile(values, 0.75) - _quantile(values, 0.25)
        if iqr > 0.0:
            group_iqrs.append(iqr)
    if not group_iqrs:
        return updated

    figure_width_mm, figure_height_mm = _size_mm(
        str(updated.get("size") or DEFAULT_FIGURE_SIZE)
    )
    slot_width_mm = categorical_slot_width_mm(
        category_count=len(categorical),
        figure_width_mm=float(figure_width_mm),
    )
    nominal_width_mm = categorical_box_width_mm(
        category_count=len(categorical),
        figure_width_mm=float(figure_width_mm),
    )
    representative_iqr = _quantile(group_iqrs, 0.5)
    graph_height_mm = max(
        float(figure_height_mm) - UNIFIED_BOTTOM_MARGIN_MM - UNIFIED_TOP_MARGIN_MM,
        1.0,
    )
    representative_height_mm = representative_iqr / axis_span * graph_height_mm
    target = CATEGORICAL_BOX_MIN_PHYSICAL_ASPECT_RATIO
    aspect_width_cap_mm = representative_height_mm / target
    marker_diameter_mm = 2.0 * UNIFIED_MARKER_SIZE_PT * 25.4 / 72.0
    marker_capacity_floor_mm = CATEGORICAL_BOX_MIN_MARKER_DIAMETERS * marker_diameter_mm
    resolved_width_mm = min(
        nominal_width_mm,
        max(aspect_width_cap_mm, marker_capacity_floor_mm),
    )
    if resolved_width_mm <= 0.0 or slot_width_mm <= 0.0:
        return updated
    resolved_fraction = resolved_width_mm / slot_width_mm
    resolved_aspect = representative_height_mm / resolved_width_mm
    updated["_categorical_box_fill_fraction"] = resolved_fraction
    updated["_categorical_box_width_mm"] = resolved_width_mm
    updated["_categorical_box_aspect_constraint"] = {
        "kind": "sciplot_categorical_box_physical_aspect_constraint",
        "version": 1,
        "mode": "narrow_width_toward_data_derived_iqr_height",
        "minimum_height_to_width_ratio": target,
        "representative_statistic": "median_group_iqr",
        "representative_iqr_axis_units": representative_iqr,
        "resolved_y_axis_span": axis_span,
        "representative_box_height_mm": representative_height_mm,
        "nominal_box_width_mm": nominal_width_mm,
        "aspect_width_cap_mm": aspect_width_cap_mm,
        "marker_capacity_floor_mm": marker_capacity_floor_mm,
        "resolved_box_width_mm": resolved_width_mm,
        "resolved_height_to_width_ratio": resolved_aspect,
        "box_width_narrowed": resolved_width_mm < nominal_width_mm - 1e-12,
        "statistics_modified": False,
        "y_axis_modified": False,
        "status": (
            "satisfied"
            if resolved_aspect + 1e-12 >= target
            else "limited_by_marker_capacity"
            if math.isclose(resolved_width_mm, marker_capacity_floor_mm)
            else "limited_by_category_slot"
        ),
    }
    return updated
