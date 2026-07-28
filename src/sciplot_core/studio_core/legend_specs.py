"""Build categorical and factorized legend specifications."""

from __future__ import annotations

import re
from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_COMPONENT_LEGEND_LABEL_X_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_ROW_GAP_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_SWATCH_HEIGHT_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_SWATCH_LEFT_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_SWATCH_WIDTH_FRACTION,
    CATEGORICAL_COMPONENT_LEGEND_TOP_FRACTION,
    CATEGORICAL_GROUPED_LEGEND_LABEL_X_FRACTION,
    CATEGORICAL_GROUPED_LEGEND_SWATCH_LEFT_FRACTION,
    CATEGORICAL_GROUPED_LEGEND_SWATCH_WIDTH_FRACTION,
    FACTOR_CURVE_LEGEND_CONDITION_LABEL_ALIGNS,
    FACTOR_CURVE_LEGEND_CONDITION_LABEL_X_FRACTIONS,
    FACTOR_CURVE_LEGEND_CONDITION_SWATCH_X,
    FACTOR_CURVE_LEGEND_CONDITION_SWATCH_HEIGHT_FRACTION,
    FACTOR_CURVE_LEGEND_ENTRY_Y_FRACTIONS,
    FACTOR_CURVE_LEGEND_FORMULA_COLUMN_X_FRACTIONS,
    FACTOR_CURVE_LEGEND_FORMULA_ENTRY_Y_FRACTION,
    FACTOR_CURVE_LEGEND_FORMULA_LABEL_GAP_FRACTION,
    FACTOR_CURVE_LEGEND_FORMULA_SWATCH_LENGTH_FRACTION,
    FACTOR_CURVE_LEGEND_TITLE_X_FRACTION,
    FACTOR_CURVE_LEGEND_TITLE_Y_FRACTION,
    UNIFIED_FOREGROUND_COLOR,
)
from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
    StudioSeries,
    _VeuszStyleContract,
)
from sciplot_core.studio_render.categorical_groups import (
    _factorized_curve_grid,
)


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
    rows: list[dict[str, Any]] = []
    for display_index, component_index in enumerate(
        reversed(range(len(component_labels))),
        start=1,
    ):
        colors: list[str] = []
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


def _factor_condition_display_label(value: str) -> str:
    text = str(value).strip()
    match = re.search(r"(?<!\w)(\d+(?:\.\d+)?\s*%)", text)
    return match.group(1).replace(" ", "") if match is not None else text


def _curve_factor_legend_spec(
    series: list[StudioSeries],
    *,
    template_id: str,
    style: _VeuszStyleContract,
    mode: str,
) -> dict[str, Any] | None:
    """Build two independent legend groups for a complete curve factor grid."""

    grid = _factorized_curve_grid(series, template_id=template_id)
    if grid is None:
        return None
    formulas = [str(value) for value in grid["formula_order"]]
    conditions = [str(value) for value in grid["condition_order"]]
    combinations = grid["combinations"]
    condition_entries: list[dict[str, Any]] = []
    for condition_index, condition in enumerate(conditions):
        references = [combinations[(formula, condition)] for formula in formulas]
        swatch_x = FACTOR_CURVE_LEGEND_CONDITION_SWATCH_X[condition_index]
        condition_entries.append(
            {
                "name": f"curve_factor_condition_{condition_index + 1}",
                "label": _factor_condition_display_label(condition),
                "source_label": condition,
                "colors": [str(reference.color) for reference in references],
                "swatch_left_fraction": (swatch_x[0]),
                "swatch_width_fraction": (swatch_x[1] - swatch_x[0]),
                "swatch_height_fraction": (
                    FACTOR_CURVE_LEGEND_CONDITION_SWATCH_HEIGHT_FRACTION
                ),
                "label_x_fraction": (
                    FACTOR_CURVE_LEGEND_CONDITION_LABEL_X_FRACTIONS[condition_index]
                ),
                "label_align": (
                    FACTOR_CURVE_LEGEND_CONDITION_LABEL_ALIGNS[condition_index]
                ),
                "y_fraction": FACTOR_CURVE_LEGEND_ENTRY_Y_FRACTIONS[condition_index],
            }
        )
    formula_entries: list[dict[str, Any]] = []
    dark_condition = conditions[-1]
    for formula_index, formula in enumerate(formulas):
        reference = combinations[(formula, dark_condition)]
        x_start = FACTOR_CURVE_LEGEND_FORMULA_COLUMN_X_FRACTIONS[formula_index]
        formula_entries.append(
            {
                "name": f"curve_factor_formula_{formula_index + 1}",
                "label": formula,
                "source_label": formula,
                "color": reference.color,
                "line_style": "solid",
                "line_width_pt": style.line_width_pt,
                "x_start_fraction": x_start,
                "x_end_fraction": (
                    x_start + FACTOR_CURVE_LEGEND_FORMULA_SWATCH_LENGTH_FRACTION
                ),
                "label_x_fraction": (
                    x_start
                    + FACTOR_CURVE_LEGEND_FORMULA_SWATCH_LENGTH_FRACTION
                    + FACTOR_CURVE_LEGEND_FORMULA_LABEL_GAP_FRACTION
                ),
                "y_fraction": FACTOR_CURVE_LEGEND_FORMULA_ENTRY_Y_FRACTION,
            }
        )
    return {
        "presentation_kind": "factorized_curve",
        "native_key": False,
        "mode": mode,
        "factor_order": ["condition", "formula"],
        "formula_color_binding": "control_first_categorical_root",
        "formula_line_style_binding": "solid",
        "condition_tone_binding": "ordered_opaque_light_dark",
        "condition_swatch_kind": "segmented_formula_colors",
        "row_alignment": "edge_aligned_to_formula_row",
        "block_left_x_fraction": (FACTOR_CURVE_LEGEND_FORMULA_COLUMN_X_FRACTIONS[0]),
        "block_right_x_fraction": (FACTOR_CURVE_LEGEND_CONDITION_LABEL_X_FRACTIONS[-1]),
        "label_text_size_pt": style.legend_font_size_pt,
        "label_text_color": UNIFIED_FOREGROUND_COLOR,
        "groups": [
            {
                "id": "condition",
                "title": "Weight reduction",
                "title_x_fraction": FACTOR_CURVE_LEGEND_TITLE_X_FRACTION,
                "title_y_fraction": FACTOR_CURVE_LEGEND_TITLE_Y_FRACTION,
                "title_align": "left",
                "entries": condition_entries,
            },
            {
                "id": "formula",
                "title": "",
                "entries": formula_entries,
            },
        ],
    }
