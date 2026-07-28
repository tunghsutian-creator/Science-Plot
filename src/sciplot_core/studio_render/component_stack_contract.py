"""Build the categorical contract for additive component stacks."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_BAR_FILL_TRANSPARENCY,
    CATEGORICAL_BAR_LINE_WIDTH_PT,
    CATEGORICAL_BAR_WIDTH_FRACTION,
    CATEGORICAL_STACK_MAX_LIGHTEN_FRACTION,
    DEFAULT_PALETTE_PRESET,
    categorical_component_fill_color,
)
from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
    StudioSeries,
)


def _component_stack_contract(
    series: list[StudioSeries],
    *,
    template_id: str,
    render_options: dict[str, Any],
) -> dict[str, Any] | None:
    component_stacks = [
        item for item in series if item.presentation_kind == "categorical_components"
    ]
    if component_stacks:
        if template_id != "bar":
            raise StudioPreparationBlocked(
                "categorical_components_require_bar",
                "Additive categorical components are supported only by the bar template.",
            )
        component_labels = component_stacks[0].component_labels
        if len(component_labels) < 2:
            raise StudioPreparationBlocked(
                "invalid_categorical_component_contract",
                "A stacked-component bar needs at least two component labels.",
            )
        if any(
            item.component_labels != component_labels
            or len(item.y_values) != len(component_labels)
            for item in component_stacks
        ):
            raise StudioPreparationBlocked(
                "inconsistent_categorical_component_contract",
                "Every sample must use the same ordered stacked components.",
            )
        groups: list[dict[str, Any]] = []
        for index, item in enumerate(component_stacks, start=1):
            position = float(
                item.category_position if item.category_position is not None else index
            )
            cumulative = 0.0
            components: list[dict[str, Any]] = []
            for component_index, (label, raw_value) in enumerate(
                zip(component_labels, item.y_values, strict=True)
            ):
                value = float(raw_value)
                if not math.isfinite(value) or value < 0.0:
                    raise StudioPreparationBlocked(
                        "invalid_categorical_component_value",
                        "Stacked-component bars require finite non-negative values.",
                    )
                lower = cumulative
                cumulative += value
                components.append(
                    {
                        "label": label,
                        "value": value,
                        "stack_bottom": lower,
                        "stack_top": cumulative,
                        "fill_color": categorical_component_fill_color(
                            item.color,
                            component_index=component_index,
                            component_count=len(component_labels),
                        ),
                        "keyline_color": item.color,
                    }
                )
            groups.append(
                {
                    "label": item.label,
                    "color": item.color,
                    "position": position,
                    "y_name": item.y_name,
                    "components": components,
                    "component_values": [float(value) for value in item.y_values],
                    "component_count": len(components),
                    "stack_total": cumulative,
                    "raw_points_visible": False,
                    "boxplot_eligible": False,
                    "descriptive_statistics": {
                        "minimum": 0.0,
                        "q1": cumulative,
                        "median": cumulative,
                        "q3": cumulative,
                        "maximum": cumulative,
                    },
                }
            )
        return {
            "kind": "sciplot_categorical_component_contract",
            "version": 1,
            "presentation_kind": "stacked_components",
            "component_labels": list(component_labels),
            "component_count": len(component_labels),
            "component_value_count": sum(len(group["components"]) for group in groups),
            "sample_color_binding": "categorical_root_by_sample",
            "component_tone_binding": "ordered_opaque_lightness_within_sample",
            "summary_statistic": None,
            "native_veusz_boxplot": False,
            "raw_values_preserved": True,
            "raw_replicate_count": 0,
            "groups": groups,
            "visual_style": {
                "palette_policy": "sample_roots_with_component_tones",
                "palette_preset": str(
                    render_options.get("palette_preset") or DEFAULT_PALETTE_PRESET
                ),
                "bar_fill_transparency": CATEGORICAL_BAR_FILL_TRANSPARENCY,
                "bar_width_fraction": CATEGORICAL_BAR_WIDTH_FRACTION,
                "bar_line_width_pt": CATEGORICAL_BAR_LINE_WIDTH_PT,
                "component_tone_mode": "opaque_same_hue_lightness",
                "component_lighten_fraction_max": (
                    0.0
                    if len(component_labels) == 1
                    else CATEGORICAL_STACK_MAX_LIGHTEN_FRACTION
                ),
            },
        }
    return None
