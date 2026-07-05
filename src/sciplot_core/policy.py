from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

DEFAULT_FIGURE_SIZE = "60x55"
WIDE_FIGURE_SIZE = "120x55"
SPECTRUM_JOURNAL_FIGURE_SIZE = "120x110"
SPECTRUM_JOURNAL_PALETTE_ID = "spectrum_journal_8"
SPECTRUM_JOURNAL_COLORS = (
    "#D85A2A",
    "#F29A22",
    "#008C86",
    "#7BC4DF",
    "#9A4A8A",
    "#3F6FB5",
    "#C24D70",
    "#6E9F45",
)
FIGURE_SIZE_PRESETS = ("60x55", "120x55", "180x55", "60x110", "120x110", "180x110")

DEFAULT_EXPORT_FORMATS_POLICY = ("pdf", "tiff_300")

DELIVERY_DIR = "delivery"
DELIVERY_INTERNAL_DIR = "_sciplot_internal"
DELIVERY_FIGURES_DIR = "figures"

DEFAULT_RENDER_OPTIONS: dict[str, Any] = {
    "legend_position": "auto",
    "series_label_mode": "legend",
    "visual_theme_id": "clean_light",
    "style_preset": "nature",
    "size": DEFAULT_FIGURE_SIZE,
    "palette_preset": "colorblind_safe",
}

TORQUE_CURVE_RENDER_OPTIONS: dict[str, Any] = {
    **DEFAULT_RENDER_OPTIONS,
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
    **DEFAULT_RENDER_OPTIONS,
    "size": SPECTRUM_JOURNAL_FIGURE_SIZE,
    "palette_preset": SPECTRUM_JOURNAL_PALETTE_ID,
    "series_label_mode": "inline",
    "baseline": "linear_endpoints",
}

FTIR_SPECTRUM_RENDER_OPTIONS: dict[str, Any] = {
    **SPECTRUM_STACK_RENDER_OPTIONS,
    "reverse_x": True,
    "x_min": 400.0,
    "x_max": 4000.0,
    "x_tick_density": "auto",
}

NMR_SPECTRUM_RENDER_OPTIONS: dict[str, Any] = {
    **SPECTRUM_STACK_RENDER_OPTIONS,
    "reverse_x": True,
}


@dataclass(frozen=True)
class StrokePolicy:
    default_line_width_pt: float = 1.2
    min_line_width_pt: float = 1.0
    max_line_width_pt: float = 1.6
    min_line_to_tick_ratio: float = 0.9
    max_line_to_tick_ratio: float = 1.8


@dataclass(frozen=True)
class LayoutPolicy:
    """User-facing figure policy shared by CLI, workflow, QA, and Codex handoff."""

    policy_id: str
    figure_size: str = DEFAULT_FIGURE_SIZE
    allowed_legend_positions: tuple[str, ...] = ("upper_right", "lower_right", "upper_left", "lower_left")
    forbid_outside_legend: bool = False
    inside_legend_max_series: int = 4
    prefer_inline_min_series: int | None = None
    max_blank_area_ratio: float = 0.22
    min_axes_area_ratio: float = 0.35
    tick_policy: dict[str, Any] = field(default_factory=dict)
    stack_spacing_policy: dict[str, Any] = field(default_factory=dict)
    stroke_policy: StrokePolicy = field(default_factory=StrokePolicy)


DEFAULT_LAYOUT_POLICY = LayoutPolicy(policy_id="default_curve")

FTIR_LAYOUT_POLICY = LayoutPolicy(
    policy_id="ftir_spectrum",
    figure_size=SPECTRUM_JOURNAL_FIGURE_SIZE,
    allowed_legend_positions=("upper_right", "upper_left", "lower_right", "lower_left", "inline"),
    forbid_outside_legend=True,
    inside_legend_max_series=4,
    prefer_inline_min_series=5,
    max_blank_area_ratio=0.18,
    tick_policy={
        "reverse_x": True,
        "x_min": 400.0,
        "x_max": 4000.0,
        "required_x_ticks": (4000.0, 400.0),
        "preferred_x_ticks": (4000.0, 3000.0, 2000.0, 1000.0, 400.0),
        "optional_x_ticks": (3500.0, 2500.0, 1500.0, 500.0),
    },
    stack_spacing_policy={
        "mode": "auto",
        "robust_peak": "p99-p01",
        "min_gap_peak_fraction": 0.25,
        "padding_peak_fraction": 0.10,
        "nice_span_sequence": (1, 2, 5, 10, 20, 50, 100),
    },
)

NMR_LAYOUT_POLICY = LayoutPolicy(
    policy_id="nmr_spectrum",
    figure_size=SPECTRUM_JOURNAL_FIGURE_SIZE,
    allowed_legend_positions=("upper_right", "upper_left", "lower_right", "lower_left", "inline"),
    forbid_outside_legend=True,
    inside_legend_max_series=4,
    prefer_inline_min_series=5,
    max_blank_area_ratio=0.18,
    tick_policy={
        "reverse_x": True,
    },
    stack_spacing_policy={
        "mode": "auto",
        "robust_peak": "p99-p01",
        "min_gap_peak_fraction": 0.25,
        "padding_peak_fraction": 0.10,
        "nice_span_sequence": (1, 2, 5, 10, 20, 50, 100),
    },
)

TORQUE_LAYOUT_POLICY = LayoutPolicy(
    policy_id="torque_curve",
    allowed_legend_positions=("upper_right", "lower_right", "upper_left", "lower_left", "inline"),
    forbid_outside_legend=True,
    inside_legend_max_series=8,
    prefer_inline_min_series=None,
)

STRESS_RELAXATION_LAYOUT_POLICY = LayoutPolicy(
    policy_id="rheology_stress_relaxation",
    allowed_legend_positions=("upper_right", "lower_right", "upper_left", "lower_left", "inline"),
    forbid_outside_legend=True,
    inside_legend_max_series=8,
    prefer_inline_min_series=None,
)

LAYOUT_POLICIES: dict[str, LayoutPolicy] = {
    "default": DEFAULT_LAYOUT_POLICY,
    "generic_curve": DEFAULT_LAYOUT_POLICY,
    "ftir_spectrum": FTIR_LAYOUT_POLICY,
    "nmr_spectrum": NMR_LAYOUT_POLICY,
    "torque_curve": TORQUE_LAYOUT_POLICY,
    "rheology_stress_relaxation": STRESS_RELAXATION_LAYOUT_POLICY,
}


def _policy_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _policy_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_policy_value(item) for item in value]
    return deepcopy(value)


def layout_policy_for_semantic(semantic: dict[str, Any] | None, *, template: str | None = None) -> LayoutPolicy:
    semantic = semantic if isinstance(semantic, dict) else {}
    for key in (
        semantic.get("rule_id"),
        semantic.get("semantic_family"),
        template,
    ):
        if isinstance(key, str) and key in LAYOUT_POLICIES:
            return LAYOUT_POLICIES[key]
    return DEFAULT_LAYOUT_POLICY


def layout_policy_payload(policy: LayoutPolicy) -> dict[str, Any]:
    return {
        "kind": "sciplot_layout_policy",
        "version": 1,
        "policy_id": policy.policy_id,
        "figure_size": policy.figure_size,
        "allowed_legend_positions": list(policy.allowed_legend_positions),
        "forbid_outside_legend": policy.forbid_outside_legend,
        "inside_legend_max_series": policy.inside_legend_max_series,
        "prefer_inline_min_series": policy.prefer_inline_min_series,
        "max_blank_area_ratio": policy.max_blank_area_ratio,
        "min_axes_area_ratio": policy.min_axes_area_ratio,
        "tick_policy": _policy_value(policy.tick_policy),
        "stack_spacing_policy": _policy_value(policy.stack_spacing_policy),
        "stroke_policy": {
            "default_line_width_pt": policy.stroke_policy.default_line_width_pt,
            "min_line_width_pt": policy.stroke_policy.min_line_width_pt,
            "max_line_width_pt": policy.stroke_policy.max_line_width_pt,
            "min_line_to_tick_ratio": policy.stroke_policy.min_line_to_tick_ratio,
            "max_line_to_tick_ratio": policy.stroke_policy.max_line_to_tick_ratio,
        },
    }


def render_options_copy(options: dict[str, Any] | None = None) -> dict[str, Any]:
    base = deepcopy(DEFAULT_RENDER_OPTIONS)
    if options:
        base.update(deepcopy(options))
    return base


__all__ = [
    "DEFAULT_EXPORT_FORMATS_POLICY",
    "DEFAULT_FIGURE_SIZE",
    "DEFAULT_LAYOUT_POLICY",
    "DEFAULT_RENDER_OPTIONS",
    "DELIVERY_DIR",
    "DELIVERY_FIGURES_DIR",
    "DELIVERY_INTERNAL_DIR",
    "FIGURE_SIZE_PRESETS",
    "FTIR_SPECTRUM_RENDER_OPTIONS",
    "FTIR_LAYOUT_POLICY",
    "LAYOUT_POLICIES",
    "LayoutPolicy",
    "NMR_LAYOUT_POLICY",
    "NMR_SPECTRUM_RENDER_OPTIONS",
    "SPECTRUM_JOURNAL_COLORS",
    "SPECTRUM_JOURNAL_FIGURE_SIZE",
    "SPECTRUM_JOURNAL_PALETTE_ID",
    "SPECTRUM_STACK_RENDER_OPTIONS",
    "STRESS_RELAXATION_LAYOUT_POLICY",
    "StrokePolicy",
    "TORQUE_CURVE_RENDER_OPTIONS",
    "TORQUE_LAYOUT_POLICY",
    "TORQUE_OFFSET_STACK_RENDER_OPTIONS",
    "WIDE_FIGURE_SIZE",
    "layout_policy_for_semantic",
    "layout_policy_payload",
    "render_options_copy",
]
