"""Shared existing segmented component-legend specification geometry."""
from __future__ import annotations

from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_COMPONENT_LEGEND_LABEL_X_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_ROW_GAP_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_SWATCH_HEIGHT_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_SWATCH_LEFT_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_SWATCH_WIDTH_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_TOP_FRACTION,
    UNIFIED_FOREGROUND_COLOR,
)
from sciplot_core.policy.categorical import (
    CATEGORICAL_GROUPED_LEGEND_LABEL_X_FRACTION,
    CATEGORICAL_GROUPED_LEGEND_SWATCH_LEFT_FRACTION,
    CATEGORICAL_GROUPED_LEGEND_SWATCH_WIDTH_FRACTION,
)
from sciplot_core.studio_render.models import StudioPreparationBlocked, _VeuszStyleContract


def _categorical_component_legend_spec(
    categorical: dict[str, Any] | None,
    *,
    style: _VeuszStyleContract,
) -> dict[str, Any] | None:
    """Return a multicolour legend for stacked components or grouped bars."""

    if not isinstance(categorical, dict):
        return None
    groups = [
        group for group in categorical.get("groups", []) if isinstance(group, dict)
    ]
    if categorical.get("presentation_kind") == "grouped_bar_error":
        condition_labels = [
            str(value) for value in categorical.get("condition_labels", [])
        ]
        sample_labels = list(
            dict.fromkeys(str(group.get("sample_label") or "") for group in groups)
        )
        if not groups or not condition_labels or not all(sample_labels):
            return None
        rows: list[dict[str, Any]] = []
        for condition_index, condition_label in enumerate(condition_labels):
            colors: list[str] = []
            for sample_label in sample_labels:
                match = next(
                    (
                        group
                        for group in groups
                        if group.get("sample_label") == sample_label
                        and group.get("condition_label") == condition_label
                    ),
                    None,
                )
                if match is None:
                    raise StudioPreparationBlocked(
                        "inconsistent_grouped_bar_legend",
                        "The grouped-bar legend cannot resolve every sample tone.",
                    )
                colors.append(str(match["fill_color"]))
            rows.append(
                {
                    "name": f"component_legend_row_{condition_index + 1}",
                    "label": condition_label,
                    "component_index": condition_index,
                    "stack_role": "left" if condition_index == 0 else "right",
                    "y_fraction": (
                        CATEGORICAL_COMPONENT_LEGEND_TOP_FRACTION
                        - condition_index
                        * CATEGORICAL_COMPONENT_LEGEND_ROW_GAP_FRACTION
                    ),
                    "colors": colors,
                    "sample_labels": sample_labels,
                }
            )
        return {
            "presentation_kind": "segmented_component",
            "native_key": False,
            "component_order": "visible_group_left_to_right",
            "sample_color_binding": "control_first_categorical_roots",
            "swatch_left_fraction": (CATEGORICAL_GROUPED_LEGEND_SWATCH_LEFT_FRACTION),
            "swatch_width_fraction": (CATEGORICAL_GROUPED_LEGEND_SWATCH_WIDTH_FRACTION),
            "swatch_height_fraction": (
                CATEGORICAL_COMPONENT_LEGEND_SWATCH_HEIGHT_FRACTION
            ),
            "label_x_fraction": CATEGORICAL_GROUPED_LEGEND_LABEL_X_FRACTION,
            "label_text_size_pt": style.legend_font_size_pt,
            "label_text_color": UNIFIED_FOREGROUND_COLOR,
            "rows": rows,
        }
    if categorical.get("presentation_kind") != "stacked_components":
        return None
    component_labels = [str(value) for value in categorical.get("component_labels", [])]
    if not groups or not component_labels:
        return None
    rows = []
    for display_index, component_index in enumerate(
        reversed(range(len(component_labels))),
        start=1,
    ):
        colors = []
        for group in groups:
            components = [
                component
                for component in group.get("components", [])
                if isinstance(component, dict)
            ]
            if component_index >= len(components):
                raise StudioPreparationBlocked(
                    "inconsistent_categorical_component_legend",
                    "The stacked-component legend cannot resolve every sample tone.",
                )
            colors.append(str(components[component_index]["fill_color"]))
        rows.append(
            {
                "name": f"component_legend_row_{display_index}",
                "label": component_labels[component_index],
                "component_index": component_index,
                "stack_role": (
                    "top"
                    if component_index == len(component_labels) - 1
                    else "bottom"
                    if component_index == 0
                    else "middle"
                ),
                "y_fraction": (
                    CATEGORICAL_COMPONENT_LEGEND_TOP_FRACTION
                    - (display_index - 1)
                    * CATEGORICAL_COMPONENT_LEGEND_ROW_GAP_FRACTION
                ),
                "colors": colors,
                "sample_labels": [str(group.get("label") or "") for group in groups],
            }
        )
    return {
        "presentation_kind": "segmented_component",
        "native_key": False,
        "component_order": "visible_stack_top_to_bottom",
        "sample_color_binding": "control_first_categorical_roots",
        "swatch_left_fraction": (CATEGORICAL_COMPONENT_LEGEND_SWATCH_LEFT_FRACTION),
        "swatch_width_fraction": (CATEGORICAL_COMPONENT_LEGEND_SWATCH_WIDTH_FRACTION),
        "swatch_height_fraction": (CATEGORICAL_COMPONENT_LEGEND_SWATCH_HEIGHT_FRACTION),
        "label_x_fraction": CATEGORICAL_COMPONENT_LEGEND_LABEL_X_FRACTION,
        "label_text_size_pt": style.legend_font_size_pt,
        "label_text_color": UNIFIED_FOREGROUND_COLOR,
        "rows": rows,
    }


component_legend_spec = _categorical_component_legend_spec
