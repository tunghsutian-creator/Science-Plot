"""Represent and resolve semantic layout and stroke policies."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sciplot_core.policy.visual_identity import (
    DEFAULT_FIGURE_SIZE,
    STACKED_SPECTRUM_FIGURE_SIZE,
)

from sciplot_core.policy.frame_export import (
    UNIFIED_LINE_WIDTH_PT,
)

from sciplot_core.policy.categorical import (
    INSIDE_LEGEND_POSITIONS,
    REMOVED_OUTSIDE_LEGEND_POSITIONS,
)


@dataclass(frozen=True)
class StrokePolicy:
    default_line_width_pt: float = UNIFIED_LINE_WIDTH_PT
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
    frame_alignment_policy: FrameAlignmentPolicy = field(
        default_factory=FrameAlignmentPolicy
    )


DEFAULT_LAYOUT_POLICY = LayoutPolicy(policy_id="default_curve")


FTIR_LAYOUT_POLICY = LayoutPolicy(
    policy_id="ftir_spectrum",
    figure_size=STACKED_SPECTRUM_FIGURE_SIZE,
    allowed_legend_positions=(
        "upper_right",
        "upper_left",
        "lower_right",
        "lower_left",
        "inline",
    ),
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
    allowed_legend_positions=(
        "upper_right",
        "lower_right",
        "upper_left",
        "lower_left",
        "inline",
    ),
    forbid_outside_legend=True,
    inside_legend_max_series=8,
    prefer_inline_min_series=None,
)


STRESS_RELAXATION_LAYOUT_POLICY = LayoutPolicy(
    policy_id="rheology_stress_relaxation",
    allowed_legend_positions=(
        "upper_right",
        "lower_right",
        "upper_left",
        "lower_left",
        "inline",
    ),
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


def layout_policy_for_semantic(
    semantic: dict[str, Any] | None, *, template: str | None = None
) -> LayoutPolicy:
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
