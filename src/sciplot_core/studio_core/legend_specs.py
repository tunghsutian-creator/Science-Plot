"""Build categorical and factorized legend specifications."""

from __future__ import annotations

import re
from typing import Any
from sciplot_core.policy import (
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
    StudioSeries,
    _VeuszStyleContract,
)
from sciplot_core.studio_render.categorical_groups import (
    _factorized_curve_grid,
)


from sciplot_core.studio_render.component_legend import (
    _categorical_component_legend_spec as _categorical_component_legend_spec,
)


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
