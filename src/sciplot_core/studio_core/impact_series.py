"""Materialize impact point-line overlay series from canonical replicate tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.figure_plan import resolved_figure_plan_from_payload
from sciplot_core.figure_plan.request_values import (
    impact_condition_label_mapping,
)
from sciplot_core.foundation.file_hashing import (
    file_sha256,
)
from sciplot_core.policy import (
    CATEGORICAL_BOX_FILL_FRACTION,
    DEFAULT_PALETTE_COLORS,
    IMPACT_POINT_LINE_CONDITION_OFFSET_FRACTION,
    IMPACT_POINT_LINE_MEAN_MARKER_EDGE_COLOR,
    IMPACT_POINT_LINE_MEAN_MARKER_EDGE_WIDTH_PT,
    IMPACT_POINT_LINE_RAW_MARKER_ALPHA,
    IMPACT_POINT_LINE_RAW_MARKER_SCALE,
    UNIFIED_MARKER_SIZE_PT,
    categorical_fill_color,
    categorical_raw_point_half_spread,
    categorical_slot_width_mm,
)
from sciplot_core.publication import (
    build_transform_step,
)
from sciplot_core.studio_render.models import (
    IMPACT_POINT_LINE_SUMMARY_KIND,
    IMPACT_POINT_LINE_MARKER_KIND,
    IMPACT_POINT_LINE_RAW_KIND,
    POINT_LINE_MARKERS,
    StudioPreparationBlocked,
    StudioSeries,
)
from sciplot_core.studio_render.categorical_values import (
    _deterministic_category_positions,
    _mean_and_sample_sd,
)

from sciplot_core.studio_core.figure_requests import (
    _impact_point_line_condition_order,
    _impact_point_line_source,
)


def _impact_point_line_series_from_source(
    source: Path,
    *,
    request: dict[str, Any],
) -> tuple[list[StudioSeries], dict[str, Any], list[dict[str, Any]]]:
    """Build condition mean lines with sample markers and pale raw points."""

    from sciplot_core.semantic import read_impact_condition_payloads

    workbook = _impact_point_line_source(source)
    available = read_impact_condition_payloads(workbook)
    if len(available) < 2:
        raise StudioPreparationBlocked(
            "impact_point_line_needs_multiple_conditions",
            "Impact point-line comparison needs at least two workbook conditions.",
        )
    by_condition = {condition: payload for condition, payload in available}
    figure_plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    planned_task = (
        figure_plan.tasks[0]
        if figure_plan is not None
        and figure_plan.rule_id == "impact_metric"
        and len(figure_plan.tasks) == 1
        and figure_plan.tasks[0].template == "point_line"
        else None
    )
    requested_order = (
        list(planned_task.conditions)
        if planned_task is not None
        else _impact_point_line_condition_order(request)
    )
    if requested_order:
        missing = [
            condition for condition in requested_order if condition not in by_condition
        ]
        if missing:
            raise StudioPreparationBlocked(
                "unknown_impact_point_line_condition",
                "Unknown impact point-line condition(s): " + ", ".join(missing),
            )
        selected = [
            (condition, by_condition[condition]) for condition in requested_order
        ]
    else:
        compatible: dict[tuple[str, ...], list[tuple[str, Any]]] = {}
        shape_order: list[tuple[str, ...]] = []
        for condition, payload in available:
            shape = tuple(payload.samples)
            if shape not in compatible:
                shape_order.append(shape)
                compatible[shape] = []
            compatible[shape].append((condition, payload))
        selected_shape = max(
            shape_order,
            key=lambda shape: (
                len(compatible[shape]),
                len(shape),
                -shape_order.index(shape),
            ),
        )
        selected = compatible[selected_shape]
    if len(selected) < 2:
        raise StudioPreparationBlocked(
            "impact_point_line_incompatible_conditions",
            "No compatible group of at least two impact conditions shares one "
            "sample axis; choose conditions explicitly or repair the source.",
        )
    sample_order = tuple(selected[0][1].samples)
    if any(tuple(payload.samples) != sample_order for _condition, payload in selected):
        raise StudioPreparationBlocked(
            "impact_point_line_sample_axis_mismatch",
            "Every selected impact point-line condition must use the same ordered "
            "sample axis.",
        )
    units = {str(payload.unit) for _condition, payload in selected}
    if units != {"kJ/m2"}:
        raise StudioPreparationBlocked(
            "impact_point_line_unit_mismatch",
            "Impact point-line conditions must all use canonical kJ/m2 units.",
        )

    if planned_task is not None:
        label_mapping = (
            dict(
                zip(
                    planned_task.conditions,
                    planned_task.condition_labels,
                    strict=True,
                )
            )
            if planned_task.condition_labels
            else {}
        )
    else:
        label_mapping = impact_condition_label_mapping(request)
    artifact = (str(workbook), file_sha256(workbook))
    raw_point_half_spread = categorical_raw_point_half_spread(
        box_fill_fraction=CATEGORICAL_BOX_FILL_FRACTION,
        replicate_count=max(
            len(values) for _condition, payload in selected for values in payload.values
        ),
        category_slot_width_mm=categorical_slot_width_mm(
            category_count=len(sample_order),
            figure_width_mm=60.0,
        ),
    )
    condition_count = len(selected)
    condition_offsets = tuple(
        (
            -IMPACT_POINT_LINE_CONDITION_OFFSET_FRACTION
            + 2.0
            * IMPACT_POINT_LINE_CONDITION_OFFSET_FRACTION
            * condition_index
            / float(condition_count - 1)
        )
        if condition_count > 1
        else 0.0
        for condition_index in range(condition_count)
    )
    series: list[StudioSeries] = []
    for condition_index, ((condition, payload), condition_offset) in enumerate(
        zip(selected, condition_offsets, strict=True)
    ):
        display_label = label_mapping.get(condition, condition)
        color = DEFAULT_PALETTE_COLORS[condition_index % len(DEFAULT_PALETTE_COLORS)]
        summaries = tuple(
            _mean_and_sample_sd(tuple(float(value) for value in values))
            for values in payload.values
        )
        means = tuple(summary[0] for summary in summaries)
        errors = tuple(summary[1] for summary in summaries)
        positions = tuple(
            float(index) + condition_offset for index in range(1, len(sample_order) + 1)
        )
        series.append(
            StudioSeries(
                label=display_label,
                x_name=f"impact_summary_x_{condition_index + 1}",
                y_name=f"impact_summary_y_{condition_index + 1}",
                x_values=positions,
                y_values=means,
                error_values=errors,
                color=color,
                marker="none",
                line_style="solid",
                presentation_kind=IMPACT_POINT_LINE_SUMMARY_KIND,
                component_labels=sample_order,
                source_artifacts=(artifact,),
            )
        )
        raw_color = categorical_fill_color(color)
        for sample_index, (sample, values, mean) in enumerate(
            zip(sample_order, payload.values, means, strict=True),
            start=1,
        ):
            marker = POINT_LINE_MARKERS[(sample_index - 1) % len(POINT_LINE_MARKERS)]
            series.append(
                StudioSeries(
                    label=f"{display_label} · {sample} mean",
                    x_name=(
                        f"impact_mean_marker_x_{condition_index + 1}_{sample_index}"
                    ),
                    y_name=(
                        f"impact_mean_marker_y_{condition_index + 1}_{sample_index}"
                    ),
                    x_values=(float(sample_index) + condition_offset,),
                    y_values=(float(mean),),
                    color=color,
                    marker=marker,
                    marker_line_color=IMPACT_POINT_LINE_MEAN_MARKER_EDGE_COLOR,
                    marker_line_width=IMPACT_POINT_LINE_MEAN_MARKER_EDGE_WIDTH_PT,
                    presentation_kind=IMPACT_POINT_LINE_MARKER_KIND,
                    category_position=float(sample_index) + condition_offset,
                    source_artifacts=(artifact,),
                )
            )
            series.append(
                StudioSeries(
                    label=f"{display_label} · {sample} raw",
                    x_name=f"impact_raw_x_{condition_index + 1}_{sample_index}",
                    y_name=f"impact_raw_y_{condition_index + 1}_{sample_index}",
                    x_values=_deterministic_category_positions(
                        float(sample_index) + condition_offset,
                        len(values),
                        fraction=raw_point_half_spread,
                        seed_key=f"{condition}|{sample}",
                    ),
                    y_values=tuple(float(value) for value in values),
                    color=raw_color,
                    marker=marker,
                    marker_size=(
                        UNIFIED_MARKER_SIZE_PT * IMPACT_POINT_LINE_RAW_MARKER_SCALE
                    ),
                    marker_alpha=IMPACT_POINT_LINE_RAW_MARKER_ALPHA,
                    presentation_kind=IMPACT_POINT_LINE_RAW_KIND,
                    category_position=float(sample_index) + condition_offset,
                    source_artifacts=(artifact,),
                )
            )
    transform_step = build_transform_step(
        step_id="impact_condition_point_line_overlay",
        operation="summarize_condition_means_and_preserve_raw_replicates",
        input_path=workbook,
        output_path=None,
        implementation_ref=(
            "sciplot_core.studio._impact_point_line_series_from_source"
        ),
        parameters={
            "selected_conditions": [condition for condition, _payload in selected],
            "condition_labels": [
                label_mapping.get(condition, condition)
                for condition, _payload in selected
            ],
            "sample_order": list(sample_order),
            "summary_statistic": "arithmetic_mean",
            "error_bar_statistic": "sample_sd_n_minus_1",
            "raw_values_preserved": True,
            "raw_point_position_policy": "stable_hash_shuffled_even_slots",
            "condition_offsets": list(condition_offsets),
            "raw_point_condition_offset": True,
            "raw_marker_scale": IMPACT_POINT_LINE_RAW_MARKER_SCALE,
            "raw_marker_alpha": IMPACT_POINT_LINE_RAW_MARKER_ALPHA,
            "mean_marker_edge_color": IMPACT_POINT_LINE_MEAN_MARKER_EDGE_COLOR,
            "mean_marker_edge_width_pt": (IMPACT_POINT_LINE_MEAN_MARKER_EDGE_WIDTH_PT),
            "raw_replicate_count": sum(
                payload.total_replicates for _condition, payload in selected
            ),
            "condition_selection_policy": (
                figure_plan.selection_policy
                if planned_task is not None and figure_plan is not None
                else (
                    "explicit_condition_order"
                    if requested_order
                    else "largest_compatible_ordered_sample_axis_group"
                )
            ),
        },
    )
    return (
        series,
        {
            "x_label": "Sample",
            "y_label": "Impact strength (kJ m⁻²)",
            "presentation_kind": "impact_point_line_raw_overlay",
            "category_labels": list(sample_order),
            "category_positions": [
                float(index) for index in range(1, len(sample_order) + 1)
            ],
            "condition_labels": [
                label_mapping.get(condition, condition)
                for condition, _payload in selected
            ],
            "raw_replicate_count": sum(
                payload.total_replicates for _condition, payload in selected
            ),
            "summary_statistic": "arithmetic_mean",
        },
        [transform_step],
    )
