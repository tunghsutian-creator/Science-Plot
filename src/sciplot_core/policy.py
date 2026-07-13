from __future__ import annotations

import math
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

DEFAULT_FIGURE_SIZE = "60x55"
WIDE_FIGURE_SIZE = "120x55"
STACKED_SPECTRUM_FIGURE_SIZE = "120x110"
JAMA_EDITORIAL_PALETTE_ID = "jama_editorial"
NPG_MODERN_PALETTE_ID = "npg_modern"
TOL_BRIGHT_PALETTE_ID = "tol_bright"
DEFAULT_PALETTE_PRESET = JAMA_EDITORIAL_PALETTE_ID
JAMA_EDITORIAL_COLORS = (
    "#374E55",
    "#DF8F44",
    "#00A1D5",
    "#B24745",
    "#79AF97",
    "#6A6599",
    "#80796B",
)
NPG_MODERN_COLORS = (
    "#3C5488",
    "#4DBBD5",
    "#00A087",
    "#E64B35",
    "#7E6148",
    "#8491B4",
    "#91D1C2",
    "#B09C85",
    "#F39B7F",
    "#DC0000",
)
TOL_BRIGHT_COLORS = (
    "#4477AA",
    "#EE6677",
    "#228833",
    "#AA3377",
    "#CCBB44",
    "#66CCEE",
    "#BBBBBB",
)
DEFAULT_PALETTE_COLORS = JAMA_EDITORIAL_COLORS
DEFAULT_LINE_STYLE_SEQUENCE = (
    "solid",
    "dashed",
    "dotted",
    "dash-dot",
    "dash-dot-dot",
    "dashed-fine",
    "dotted-fine",
)
FIGURE_SIZE_PRESETS = ("60x55", "120x55", "180x55", "60x110", "120x110", "180x110")

DEFAULT_EXPORT_FORMATS_POLICY = ("pdf", "tiff_300")
DEFAULT_LOG_TICK_FORMAT = "%Ve"
DEFAULT_LOG_MINOR_TICK_COUNT = 10
DEFAULT_LOG_MINOR_MULTIPLIERS = (2.0, 4.0, 6.0, 8.0)
DEFAULT_LEGEND_CURVE_CLEARANCE_MM = 2.0
DEFAULT_LEGEND_EDGE_PADDING_MM = 1.0
INSIDE_LEGEND_POSITIONS = ("upper_right", "lower_right", "upper_left", "lower_left")
REMOVED_OUTSIDE_LEGEND_POSITIONS = frozenset({"outside", "outside_right", "right_outside"})
DEFAULT_CATEGORICAL_SUMMARY = "median_iqr"
CATEGORICAL_SUMMARY_OPTIONS = ("median_iqr", "raw_only")
DEFAULT_RAW_POINT_JITTER_FRACTION = 0.12
MAX_RAW_POINT_JITTER_FRACTION = 0.35
MIN_BOX_REPLICATES = 2

# Public request keys accepted by the compatibility intake surface.  Keep this
# contract explicit and renderer-independent so importing intake never starts
# Matplotlib merely to introspect a legacy function signature.
RENDER_OPTION_KEYS = frozenset(
    {
        "size",
        "xscale",
        "yscale",
        "reverse_x",
        "x_min",
        "x_max",
        "y_min",
        "y_max",
        "x_padding_fraction",
        "x_tick_density",
        "y_tick_density",
        "x_tick_edge_labels",
        "y_tick_edge_labels",
        "x_tick_format",
        "y_tick_format",
        "x_ticks",
        "y_ticks",
        "minor_tick_count",
        "series_order",
        "series_include",
        "series_styles",
        "line_style_sequence",
        "marker_sequence",
        "marker_size",
        "marker_fill_mode",
        "summary_statistic",
        "raw_point_jitter_fraction",
        "palette_colors",
        "font_size_pt",
        "legend_font_size_pt",
        "axis_linewidth_pt",
        "tick_width_pt",
        "tick_length_pt",
        "minor_tick_width_pt",
        "minor_tick_length_pt",
        "line_width_pt",
        "line_alpha",
        "marker_alpha",
        "marker_line_width_pt",
        "series_offsets",
        "stack_spacing_scale",
        "legend_position",
        "legend_curve_clearance_mm",
        "legend_edge_padding_mm",
        "series_label_mode",
        "x_label_override",
        "y_label_override",
        "baseline",
        "show_colorbar",
        "style_preset",
        "palette_preset",
        "visual_theme_id",
        "fit_options",
        "extra_x_axis",
        "extra_y_axis",
        "x_axis_breaks",
        "y_axis_breaks",
        "reference_guides",
        "reference_line",
        "reference_band",
        "text_annotations",
        "shape_annotations",
        "analytical_layers",
        "data_variables",
        "data_transforms",
    }
)

DELIVERY_DIR = "delivery"
DELIVERY_EDITABLE_DIR = "editable"
DELIVERY_INTERNAL_DIR = "_sciplot_internal"
DELIVERY_FIGURES_DIR = "figures"

DEFAULT_RENDER_OPTIONS: dict[str, Any] = {
    "legend_position": "auto",
    "series_label_mode": "legend",
    "visual_theme_id": "clean_light",
    "style_preset": "nature",
    "size": DEFAULT_FIGURE_SIZE,
    "palette_preset": DEFAULT_PALETTE_PRESET,
}


def normalize_categorical_summary(value: object) -> str:
    normalized = str(value or DEFAULT_CATEGORICAL_SUMMARY).strip().casefold()
    if normalized not in CATEGORICAL_SUMMARY_OPTIONS:
        known = ", ".join(CATEGORICAL_SUMMARY_OPTIONS)
        raise ValueError(f"Unknown categorical summary `{value}`. Available: {known}.")
    return normalized


def normalize_raw_point_jitter_fraction(value: object) -> float:
    if value in (None, ""):
        return DEFAULT_RAW_POINT_JITTER_FRACTION
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Raw-point jitter fraction must be a finite number between 0 and 0.35.") from exc
    if not math.isfinite(normalized) or not 0.0 <= normalized <= MAX_RAW_POINT_JITTER_FRACTION:
        raise ValueError("Raw-point jitter fraction must be a finite number between 0 and 0.35.")
    return normalized


RHEOLOGY_FREQUENCY_X_LABEL = "ω (rad s⁻¹)"
RHEOLOGY_FREQUENCY_X_RENDER_LABEL = "\\omega (rad s^{-1})"
RHEOLOGY_FREQUENCY_TICK_FORMAT = DEFAULT_LOG_TICK_FORMAT
RHEOLOGY_METRIC_AXIS_LABELS: dict[str, str] = {
    "storage_modulus": "\\italic{G}′ (Pa)",
    "loss_modulus": "\\italic{G}″ (Pa)",
    "loss_factor": "tan \\delta",
    "tan_delta": "tan \\delta",
    "complex_modulus": "|\\italic{G}^{*}| (Pa)",
    "complex_viscosity": "|\\eta^{*}| (mPa·s)",
}


def anchored_log_decade_ticks(values: Iterable[object]) -> tuple[float, ...]:
    """Return labeled decades that visibly bracket positive log-scale data."""

    positive: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            positive.append(number)
    if not positive:
        return ()
    minimum = min(positive)
    maximum = max(positive)
    lower_exponent = math.floor(math.log10(minimum))
    lower_decade = 10.0**lower_exponent
    if minimum / lower_decade > 5.0:
        lower_exponent += 1
    upper_exponent = math.ceil(math.log10(maximum))
    ticks = [10.0**exponent for exponent in range(lower_exponent, upper_exponent + 1)]
    if len(ticks) == 1 and maximum > minimum:
        only = ticks[0]
        ticks = [only / 10.0, only] if only >= maximum else [only, only * 10.0]
    return tuple(ticks)


def rheology_metric_axis_label(value: object) -> str | None:
    """Resolve common rheology metric names and symbols to Veusz math labels."""

    text = str(value or "").strip()
    folded = text.casefold()
    token = "".join(character for character in folded if character.isalnum())
    if any(term in folded for term in ("tan δ", "tanδ", "tan delta")) or token in {
        "lossfactor",
        "tandelta",
    }:
        return RHEOLOGY_METRIC_AXIS_LABELS["loss_factor"]
    if any(term in folded for term in ("η", "eta")) or token in {
        "complexviscosity",
        "viscosity",
    }:
        return RHEOLOGY_METRIC_AXIS_LABELS["complex_viscosity"]
    if "complex modulus" in folded or "g*" in folded or "g∗" in folded or token == "complexmodulus":
        return RHEOLOGY_METRIC_AXIS_LABELS["complex_modulus"]
    if "loss modulus" in folded or "g″" in folded or 'g"' in folded or "g''" in folded or token == "lossmodulus":
        return RHEOLOGY_METRIC_AXIS_LABELS["loss_modulus"]
    if "storage modulus" in folded or "g′" in folded or "g'" in folded or token == "storagemodulus":
        return RHEOLOGY_METRIC_AXIS_LABELS["storage_modulus"]
    return RHEOLOGY_METRIC_AXIS_LABELS.get(token)


RHEOLOGY_FREQUENCY_RENDER_OPTIONS: dict[str, Any] = {
    **DEFAULT_RENDER_OPTIONS,
    "xscale": "log",
    "yscale": "log",
    "reverse_x": False,
    "x_label_override": RHEOLOGY_FREQUENCY_X_RENDER_LABEL,
    "x_tick_format": RHEOLOGY_FREQUENCY_TICK_FORMAT,
    "y_tick_format": RHEOLOGY_FREQUENCY_TICK_FORMAT,
    "minor_tick_count": 10,
    "marker_sequence": ["circle", "square", "diamond", "triangle"],
    "marker_size": 1.7,
    "marker_fill_mode": "filled",
    "palette_preset": JAMA_EDITORIAL_PALETTE_ID,
    "font_size_pt": 7.0,
    "legend_font_size_pt": 6.5,
    "axis_linewidth_pt": 0.7,
    "tick_width_pt": 0.7,
    "tick_length_pt": 2.8,
    "minor_tick_width_pt": 0.45,
    "minor_tick_length_pt": 1.5,
    "line_width_pt": 0.9,
    "line_alpha": 1.0,
    "marker_alpha": 1.0,
    "marker_line_width_pt": 0.3,
    "legend_curve_clearance_mm": DEFAULT_LEGEND_CURVE_CLEARANCE_MM,
    "legend_edge_padding_mm": DEFAULT_LEGEND_EDGE_PADDING_MM,
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
    "size": STACKED_SPECTRUM_FIGURE_SIZE,
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


@dataclass(frozen=True)
class StrokePolicy:
    default_line_width_pt: float = 1.2
    min_line_width_pt: float = 1.0
    max_line_width_pt: float = 1.6
    min_line_to_tick_ratio: float = 0.9
    max_line_to_tick_ratio: float = 1.8


@dataclass(frozen=True)
class FrameAlignmentPolicy:
    """Physical alignment contract for standalone publication figures."""

    margin_mode: str = "fixed_mm"
    outside_legend_allowed: bool = False
    auxiliary_frame_envelope: str = "standard_graph_frame"
    auxiliary_text_envelope: str = "standard_text_safe_area"


FIXED_PUBLICATION_FRAME_POLICY = FrameAlignmentPolicy()


@dataclass(frozen=True)
class LayoutPolicy:
    """User-facing figure policy shared by CLI, workflow, QA, and Codex handoff."""

    policy_id: str
    figure_size: str = DEFAULT_FIGURE_SIZE
    allowed_legend_positions: tuple[str, ...] = INSIDE_LEGEND_POSITIONS
    forbid_outside_legend: bool = True
    inside_legend_max_series: int = 4
    prefer_inline_min_series: int | None = None
    max_blank_area_ratio: float = 0.22
    min_axes_area_ratio: float = 0.35
    tick_policy: dict[str, Any] = field(default_factory=dict)
    stack_spacing_policy: dict[str, Any] = field(default_factory=dict)
    stroke_policy: StrokePolicy = field(default_factory=StrokePolicy)
    frame_alignment_policy: FrameAlignmentPolicy = field(default_factory=FrameAlignmentPolicy)


DEFAULT_LAYOUT_POLICY = LayoutPolicy(policy_id="default_curve")

FTIR_LAYOUT_POLICY = LayoutPolicy(
    policy_id="ftir_spectrum",
    figure_size=STACKED_SPECTRUM_FIGURE_SIZE,
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
    "torque_curve": TORQUE_LAYOUT_POLICY,
    "rheology_stress_relaxation": STRESS_RELAXATION_LAYOUT_POLICY,
}


def _policy_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _policy_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_policy_value(item) for item in value]
    return deepcopy(value)


def is_removed_outside_legend_position(value: object) -> bool:
    return str(value or "").strip().casefold() in REMOVED_OUTSIDE_LEGEND_POSITIONS


def normalize_legend_position(value: object) -> str:
    """Keep every public legend inside the fixed physical graph frame."""

    normalized = str(value or "auto").strip().casefold()
    if normalized in REMOVED_OUTSIDE_LEGEND_POSITIONS:
        return "auto"
    return normalized or "auto"


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
        "frame_alignment_policy": {
            "margin_mode": policy.frame_alignment_policy.margin_mode,
            "outside_legend_allowed": policy.frame_alignment_policy.outside_legend_allowed,
            "auxiliary_frame_envelope": policy.frame_alignment_policy.auxiliary_frame_envelope,
            "auxiliary_text_envelope": policy.frame_alignment_policy.auxiliary_text_envelope,
        },
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
    "DEFAULT_LOG_MINOR_MULTIPLIERS",
    "DEFAULT_LOG_MINOR_TICK_COUNT",
    "DEFAULT_LOG_TICK_FORMAT",
    "DEFAULT_PALETTE_COLORS",
    "DEFAULT_PALETTE_PRESET",
    "DEFAULT_RENDER_OPTIONS",
    "DELIVERY_DIR",
    "DELIVERY_EDITABLE_DIR",
    "DELIVERY_FIGURES_DIR",
    "DELIVERY_INTERNAL_DIR",
    "FIGURE_SIZE_PRESETS",
    "FTIR_SPECTRUM_RENDER_OPTIONS",
    "FTIR_LAYOUT_POLICY",
    "JAMA_EDITORIAL_COLORS",
    "JAMA_EDITORIAL_PALETTE_ID",
    "LAYOUT_POLICIES",
    "LayoutPolicy",
    "NPG_MODERN_COLORS",
    "NPG_MODERN_PALETTE_ID",
    "STACKED_SPECTRUM_FIGURE_SIZE",
    "SPECTRUM_STACK_RENDER_OPTIONS",
    "STRESS_RELAXATION_LAYOUT_POLICY",
    "StrokePolicy",
    "TORQUE_CURVE_RENDER_OPTIONS",
    "TORQUE_LAYOUT_POLICY",
    "TORQUE_OFFSET_STACK_RENDER_OPTIONS",
    "TOL_BRIGHT_COLORS",
    "TOL_BRIGHT_PALETTE_ID",
    "WIDE_FIGURE_SIZE",
    "anchored_log_decade_ticks",
    "layout_policy_for_semantic",
    "layout_policy_payload",
    "render_options_copy",
    "rheology_metric_axis_label",
]
