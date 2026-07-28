"""Declare one-step states and issue-specific quality actions."""

from __future__ import annotations

from typing import Any
from sciplot_core.policy import (
    UNIFIED_LINE_WIDTH_PT,
)
from sciplot_core.split import DEFAULT_STACK_SPLIT_POLICY


ONE_STEP_MODEL_KIND = "sciplot_one_step_project"


ONE_STEP_MODEL_VERSION = 2


_LEGEND_INLINE_STRATEGY = {
    "object": "legend",
    "fallback_order": ["inside_auto_legend", "inline_labels"],
    "reject_if": [
        "legend_overlap",
        "legend_footprint",
        "legend_axes_too_small",
        "legend_outside_bounds",
    ],
}


_LEGEND_AUTO_STRATEGY = {
    "object": "legend",
    "fallback_order": ["inside_auto_legend", "inline_labels"],
    "reject_if": [
        "label_collision",
        "label_out_of_bounds",
        "stacked_label_collision",
        "stacked_label_bounds",
    ],
}


_STACK_SPLIT_POLICY = DEFAULT_STACK_SPLIT_POLICY


_ISSUE_QUALITY_ACTIONS: dict[str, dict[str, Any]] = {
    "stroke_weight_out_of_band": {
        "id": "normalize_line_width",
        "label": "Normalize line width",
        "reason": "Curve strokes fall outside the publication-style line-weight contract.",
        "series_style_patch": {
            "target": "visible_series",
            "line_width": UNIFIED_LINE_WIDTH_PT,
        },
    },
    "line_tick_hierarchy": {
        "id": "normalize_line_width",
        "label": "Normalize line width",
        "reason": "Curve strokes are visually weaker than the tick hierarchy.",
        "series_style_patch": {
            "target": "visible_series",
            "line_width": UNIFIED_LINE_WIDTH_PT,
        },
    },
    "stroke_hierarchy": {
        "id": "normalize_line_width",
        "label": "Normalize line width",
        "reason": "The plotted stroke hierarchy is outside the visual QA contract.",
        "series_style_patch": {
            "target": "visible_series",
            "line_width": UNIFIED_LINE_WIDTH_PT,
        },
    },
    "tick_label_overlap": {
        "id": "use_sparse_ticks",
        "label": "Use sparse ticks",
        "reason": "Major tick labels overlap in the rendered frame.",
        "render_options_patch": {
            "x_tick_density": "sparse",
            "y_tick_density": "sparse",
        },
    },
    "axis_label_crowding": {
        "id": "use_sparse_ticks",
        "label": "Use sparse ticks",
        "reason": "Axis tick labels are too crowded for the current figure size.",
        "render_options_patch": {
            "x_tick_density": "sparse",
            "y_tick_density": "sparse",
        },
    },
    "category_crowding": {
        "id": "use_sparse_ticks",
        "label": "Use sparse ticks",
        "reason": "Categorical labels are crowded in the rendered frame.",
        "render_options_patch": {"x_tick_density": "sparse"},
    },
    "legend_overlap": {
        "id": "use_inline_labels",
        "label": "Use inline labels",
        "reason": "The legend overlaps data, ticks, axis labels, or direct labels.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "legend_footprint": {
        "id": "use_inline_labels",
        "label": "Use inline labels",
        "reason": "The legend footprint leaves too little useful plotting area.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "legend_axes_too_small": {
        "id": "use_inline_labels",
        "label": "Use inline labels",
        "reason": "Legend avoidance makes the data axes too small.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "legend_outside_bounds": {
        "id": "use_inside_or_inline_labels",
        "label": "Keep labels inside",
        "reason": "The legend extends outside the rendered canvas.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "legend_crowded_inside": {
        "id": "use_inside_or_inline_labels",
        "label": "Keep labels inside",
        "reason": "The visible legend is too crowded for the fixed publication frame.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "label_collision": {
        "id": "use_auto_legend",
        "label": "Use auto legend",
        "reason": "Direct labels collide; let the renderer choose a safer legend/label mode.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
        "layout_strategy": _LEGEND_AUTO_STRATEGY,
    },
    "label_out_of_bounds": {
        "id": "use_auto_legend",
        "label": "Use auto legend",
        "reason": "At least one direct label falls outside the plotting axes.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
        "layout_strategy": _LEGEND_AUTO_STRATEGY,
    },
    "ftir_wavenumber_bounds_missing": {
        "id": "restore_ftir_wavenumber_axis",
        "label": "Restore FTIR axis",
        "reason": "FTIR/wavenumber plots must show 4000 to 400 cm^-1 with endpoint ticks.",
        "render_options_patch": {
            "x_min": 400.0,
            "x_max": 4000.0,
            "reverse_x": True,
            "x_tick_density": "auto",
        },
    },
    "stacked_top_blank_excess": {
        "id": "tighten_stacked_y_axis",
        "label": "Tighten stacked y-axis",
        "reason": "Stacked curves leave excessive blank area above the data.",
        "clear_render_options": ["y_min", "y_max"],
    },
    "data_vertical_occupancy_low": {
        "id": "tighten_stacked_y_axis",
        "label": "Tighten stacked y-axis",
        "reason": "The data occupy too little vertical space in the plotted frame.",
        "clear_render_options": ["y_min", "y_max"],
    },
    "stack_curve_overlap": {
        "id": "increase_stack_spacing",
        "label": "Increase stack spacing",
        "reason": "Manual stacked-curve spacing causes curve overlap.",
        "clear_render_options": ["stack_spacing_scale"],
    },
    "stack_spacing_too_loose": {
        "id": "tighten_stacked_y_axis",
        "label": "Tighten stacked y-axis",
        "reason": "Manual stacked-curve spacing is too loose for the current figure.",
        "clear_render_options": ["stack_spacing_scale", "y_min", "y_max"],
    },
    "stack_peak_too_small": {
        "id": "increase_figure_height_or_split",
        "label": "Increase height or split",
        "reason": "Stacked peaks are below the minimum readable pixel height.",
        "figure_size_patch": {
            "mode": "increase_height",
            "fallback_size": "60x110",
            "split_if_unavailable": True,
        },
        "split_policy": _STACK_SPLIT_POLICY,
        "requires_human_confirmation": True,
    },
    "stacked_label_collision": {
        "id": "use_auto_legend",
        "label": "Use auto legend",
        "reason": "Stacked direct labels collide.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
        "layout_strategy": _LEGEND_AUTO_STRATEGY,
    },
    "stacked_label_bounds": {
        "id": "use_auto_legend",
        "label": "Use auto legend",
        "reason": "At least one stacked direct label is outside the plotting axes.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
        "layout_strategy": _LEGEND_AUTO_STRATEGY,
    },
}


_STACK_SPLIT_QUALITY_ACTION = {
    "id": "split_stacked_figure",
    "label": "Split stacked figure",
    "reason": "Stacked peaks remain below readable pixel height even on a tall figure.",
    "split_policy": _STACK_SPLIT_POLICY,
    "requires_human_confirmation": True,
}


_AUTOFIX_QUALITY_ACTIONS: dict[str, dict[str, Any]] = {
    "stroke_weight_autorepaired": {
        "id": "normalize_line_width",
        "label": "Normalized line width",
        "reason": "Default strokes were raised to the publication-style line-weight floor.",
        "series_style_patch": {
            "target": "visible_series",
            "line_width": UNIFIED_LINE_WIDTH_PT,
        },
    },
    "stacked_y_axis_compacted": {
        "id": "tighten_stacked_y_axis",
        "label": "Tightened stacked y-axis",
        "reason": "The renderer compacted stacked y-limits after visual occupancy QA.",
    },
    "legend_auto_inline_labels": {
        "id": "use_inline_labels",
        "label": "Switched to inline labels",
        "reason": "The renderer used inline labels because the legend would hurt data readability.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
    },
    "direct_series_labels": {
        "id": "use_inline_labels",
        "label": "Used inline labels",
        "reason": "Direct labels were selected by the automatic layout pass.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
    },
    "legend_auto_widened_inside": {
        "id": "widen_for_inside_legend",
        "label": "Widened for inside legend",
        "reason": "The renderer widened an unlocked canvas while preserving the fixed graph margins.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
    },
    "legend_outside_removed": {
        "id": "keep_legend_inside",
        "label": "Kept legend inside",
        "reason": "A retired outside-legend request was normalized to the fixed inside-frame policy.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
    },
    "legend_auto_upper_right": {
        "id": "move_legend_upper_right",
        "label": "Moved legend upper right",
        "reason": "The legend was moved away from the lower data region.",
        "render_options_patch": {
            "legend_position": "upper_right",
            "series_label_mode": "legend",
        },
    },
    "direct_label_offset": {
        "id": "offset_direct_labels",
        "label": "Offset direct labels",
        "reason": "Inline labels were offset from their curve anchors to reduce label-on-curve collisions.",
        "render_options_patch": {
            "series_label_offset_fraction": 0.018,
            "series_label_vertical_align": "bottom",
        },
    },
    "tick_density_sparse": {
        "id": "use_sparse_ticks",
        "label": "Used sparse ticks",
        "reason": "Dense ticks were downgraded to keep labels readable.",
        "render_options_patch": {
            "x_tick_density": "sparse",
            "y_tick_density": "sparse",
        },
    },
    "split_stacked_figure_auto": {
        "id": "split_stacked_figure",
        "label": "Split stacked figure",
        "reason": "A tall unreadable stacked figure was split into series chunks.",
        "split_policy": _STACK_SPLIT_POLICY,
        "requires_human_confirmation": False,
    },
}
