"""Declare recipe and template-specific render defaults."""

from __future__ import annotations

from typing import Any

from sciplot_core.policy.visual_identity import (
    DEFAULT_FIGURE_SIZE,
    STACKED_SPECTRUM_FIGURE_SIZE,
    DEFAULT_PALETTE_PRESET,
)

from sciplot_core.policy.frame_export import (
    DEFAULT_LOG_TICK_FORMAT,
    DEFAULT_LOG_MINOR_TICK_COUNT,
    DEFAULT_LEGEND_CURVE_CLEARANCE_MM,
    DEFAULT_LEGEND_EDGE_PADDING_MM,
)

from sciplot_core.policy.render_options import (
    DEFAULT_RENDER_OPTIONS,
)

from sciplot_core.policy.axis_defaults import (
    RHEOLOGY_FREQUENCY_X_RENDER_LABEL,
    RHEOLOGY_FREQUENCY_TICK_FORMAT,
    RHEOLOGY_METRIC_AXIS_LABELS,
)

CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS: dict[str, Any] = {
    **DEFAULT_RENDER_OPTIONS,
    "legend_position": "none",
    "series_label_mode": "none",
    "marker_sequence": ["circle"],
    "marker_fill_mode": "filled",
    "raw_point_jitter_fraction": 0.14,
    "palette_preset": DEFAULT_PALETTE_PRESET,
    "line_alpha": 1.0,
    "marker_alpha": 0.80,
    "box_line_mode": "series_color",
}


CURVE_RENDER_OPTIONS: dict[str, Any] = {
    **DEFAULT_RENDER_OPTIONS,
    "palette_preset": DEFAULT_PALETTE_PRESET,
    "line_alpha": 1.0,
    "legend_curve_clearance_mm": DEFAULT_LEGEND_CURVE_CLEARANCE_MM,
    "legend_edge_padding_mm": DEFAULT_LEGEND_EDGE_PADDING_MM,
}


POINT_LINE_RENDER_OPTIONS: dict[str, Any] = {
    **CURVE_RENDER_OPTIONS,
    "marker_sequence": ["circle", "square", "diamond", "triangle"],
    "marker_fill_mode": "filled",
    "marker_alpha": 1.0,
}


RHEOLOGY_FREQUENCY_RENDER_OPTIONS: dict[str, Any] = {
    **POINT_LINE_RENDER_OPTIONS,
    "xscale": "log",
    "yscale": "log",
    "reverse_x": False,
    "x_label_override": RHEOLOGY_FREQUENCY_X_RENDER_LABEL,
    "x_tick_format": RHEOLOGY_FREQUENCY_TICK_FORMAT,
    "y_tick_format": RHEOLOGY_FREQUENCY_TICK_FORMAT,
    "minor_tick_count": DEFAULT_LOG_MINOR_TICK_COUNT,
}


RHEOLOGY_TEMPERATURE_RENDER_OPTIONS: dict[str, Any] = {
    **POINT_LINE_RENDER_OPTIONS,
    "xscale": "linear",
    "yscale": "log",
    "reverse_x": False,
    "x_label_override": "Temperature (°C)",
    "y_label_override": RHEOLOGY_METRIC_AXIS_LABELS["storage_modulus"],
    "y_tick_format": DEFAULT_LOG_TICK_FORMAT,
    "y_minor_tick_count": DEFAULT_LOG_MINOR_TICK_COUNT,
}


TORQUE_CURVE_RENDER_OPTIONS: dict[str, Any] = {
    **CURVE_RENDER_OPTIONS,
    "series_label_mode": "legend",
    "size": DEFAULT_FIGURE_SIZE,
}


TORQUE_OFFSET_STACK_RENDER_OPTIONS: dict[str, Any] = {
    "size": DEFAULT_FIGURE_SIZE,
    "x_label_override": "Time",
    "y_label_override": "Screw torque",
    "stack_spacing_scale": 0.05,
    "series_label_mode": "legend",
}


SPECTRUM_STACK_RENDER_OPTIONS: dict[str, Any] = {
    **CURVE_RENDER_OPTIONS,
    "size": STACKED_SPECTRUM_FIGURE_SIZE,
    "series_label_mode": "inline",
    "baseline": "none",
}


FTIR_SPECTRUM_RENDER_OPTIONS: dict[str, Any] = {
    **SPECTRUM_STACK_RENDER_OPTIONS,
    "reverse_x": True,
    "x_tick_density": "auto",
}
