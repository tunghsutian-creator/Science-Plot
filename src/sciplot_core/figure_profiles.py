from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sciplot_core.policy import (
    DEFAULT_LOG_MINOR_TICK_COUNT,
    POINT_LINE_RENDER_OPTIONS,
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_FONT_FAMILY,
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MINOR_TICK_LENGTH_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_TICK_LENGTH_PT,
    UNIFIED_TICK_WIDTH_PT,
)


@dataclass(frozen=True)
class FigureProfile:
    profile_id: str
    label: str
    figure_kind: str
    template: str | None
    size_mm: tuple[float, float]
    render_options: dict[str, Any]
    frame_margins_mm: dict[str, float] | None
    qa_contract: dict[str, Any]
    description: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": "sciplot_figure_profile",
            "version": 1,
            "profile_id": self.profile_id,
            "label": self.label,
            "figure_kind": self.figure_kind,
            "template": self.template,
            "size_mm": list(self.size_mm),
            "render_options": deepcopy(self.render_options),
            "frame_margins_mm": deepcopy(self.frame_margins_mm),
            "qa_contract": deepcopy(self.qa_contract),
            "description": self.description,
            "input_contract": "plot_ready_data_only",
        }


_THICKNESS_FRAME_MM = {
    "left": 13.0,
    "right": 4.0,
    "bottom": 10.5,
    "top": 4.5,
}
_THICKNESS_MAJOR_TICKS = [-2.0, -1.0, 0.0, 1.0, 2.0]
_THICKNESS_MINOR_TICKS = [
    round(value / 5.0, 10)
    for value in range(-9, 10)
    if value not in {-5, 0, 5}
]
_SPARSE_LOG_MINOR_MULTIPLIERS = (2.0, 4.0, 6.0, 8.0)


def _thickness_curve_options(*, y_label: str) -> dict[str, Any]:
    return {
        **deepcopy(POINT_LINE_RENDER_OPTIONS),
        "size": "120x55",
        "xscale": "linear",
        "yscale": "log",
        "x_min": -2.0,
        "x_max": 2.0,
        "x_ticks": list(_THICKNESS_MAJOR_TICKS),
        "x_minor_ticks": list(_THICKNESS_MINOR_TICKS),
        "x_minor_tick_count": 5,
        "y_minor_tick_count": DEFAULT_LOG_MINOR_TICK_COUNT,
        "x_label_override": "Thickness position (mm)",
        "y_label_override": y_label,
        "y_tick_format": "%Ve",
        "marker_fill_mode": "filled",
        "legend_position": "auto",
        "series_label_mode": "legend",
    }


_PROFILES: dict[str, FigureProfile] = {
    "rheology_temperature_gprime_v1": FigureProfile(
        profile_id="rheology_temperature_gprime_v1",
        label="Temperature-sweep storage modulus",
        figure_kind="curve",
        template="point_line",
        size_mm=(60.0, 55.0),
        render_options={
            **deepcopy(POINT_LINE_RENDER_OPTIONS),
            "size": "60x55",
            "xscale": "linear",
            "yscale": "log",
            "x_label_override": "Temperature (°C)",
            "y_label_override": "\\italic{G}′ (Pa)",
            "y_tick_format": "%Ve",
            "y_minor_tick_count": DEFAULT_LOG_MINOR_TICK_COUNT,
            "marker_fill_mode": "filled",
        },
        frame_margins_mm=None,
        qa_contract={
            "filled_markers": True,
            "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
            "log_y_minor_ticks_per_decade": len(_SPARSE_LOG_MINOR_MULTIPLIERS),
            "exact_axis_labels": {
                "x": "Temperature (°C)",
                "y": "\\italic{G}′ (Pa)",
            },
        },
        description=(
            "Reusable temperature-sweep G′ curve style. Dashed extrapolation or "
            "unsupported-range styling remains an explicit property of the plot-ready series."
        ),
    ),
    "thickness_gprime_v1": FigureProfile(
        profile_id="thickness_gprime_v1",
        label="Storage modulus across thickness",
        figure_kind="curve",
        template="point_line",
        size_mm=(120.0, 55.0),
        render_options=_thickness_curve_options(y_label="\\italic{G}′ (Pa)"),
        frame_margins_mm=deepcopy(_THICKNESS_FRAME_MM),
        qa_contract={
            "filled_markers": True,
            "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
            "x_major_ticks": list(_THICKNESS_MAJOR_TICKS),
            "x_minor_interval_mm": 0.2,
            "log_y_minor_ticks_per_decade": len(_SPARSE_LOG_MINOR_MULTIPLIERS),
            "exact_axis_labels": {
                "x": "Thickness position (mm)",
                "y": "\\italic{G}′ (Pa)",
            },
            "plot_frame_x_mm": [13.0, 116.0],
        },
        description=(
            "Symmetric full-thickness G′ curve with the 13–116 mm physical frame "
            "used for direct alignment to the four-panel cloud strip."
        ),
    ),
    "thickness_gprime_ratio_v1": FigureProfile(
        profile_id="thickness_gprime_ratio_v1",
        label="Normalized storage modulus across thickness",
        figure_kind="curve",
        template="point_line",
        size_mm=(120.0, 55.0),
        render_options=_thickness_curve_options(y_label="\\italic{G}′/\\italic{G}′_{0}"),
        frame_margins_mm=deepcopy(_THICKNESS_FRAME_MM),
        qa_contract={
            "filled_markers": True,
            "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
            "x_major_ticks": list(_THICKNESS_MAJOR_TICKS),
            "x_minor_interval_mm": 0.2,
            "log_y_minor_ticks_per_decade": len(_SPARSE_LOG_MINOR_MULTIPLIERS),
            "exact_axis_labels": {
                "x": "Thickness position (mm)",
                "y": "\\italic{G}′/\\italic{G}′_{0}",
            },
            "plot_frame_x_mm": [13.0, 116.0],
        },
        description=(
            "SI companion for a precomputed sample-specific G′/G′₀ curve. "
            "The profile does not define or calculate G′₀."
        ),
    ),
    "relative_gradient_strip_v1": FigureProfile(
        profile_id="relative_gradient_strip_v1",
        label="Shared-colorbar relative-gradient strip",
        figure_kind="shared_scalar_strip",
        template=None,
        size_mm=(120.0, 42.0),
        render_options={
            "colormap_name": "parula",
            "color_invert": False,
            "x_min": -2.0,
            "x_max": 0.0,
            "x_ticks": [-2.0, -1.0, 0.0],
            "x_minor_ticks": [-1.8, -1.6, -1.4, -1.2, -0.8, -0.6, -0.4, -0.2],
            "x_label_override": "Thickness position (mm)",
            "z_label_override": "Γ_{G′}",
            "z_unit_override": "(mm⁻¹)",
            "panel_gap_mm": 1.1,
            "panel_top_mm": 6.0,
            "panel_bottom_mm": 34.0,
            "panel_outer_left_mm": 13.0,
            "panel_outer_right_mm": 116.0,
            "colorbar_left_mm": 8.2,
            "colorbar_right_mm": 10.4,
        },
        frame_margins_mm=None,
        qa_contract={
            "shared_colorbar": True,
            "colorbar_tick_side": "left",
            "sample_title_weight": "regular",
            "display_transform": "one_dimensional_profile_repeated_vertically",
            "exact_axis_labels": {"x": "Thickness position (mm)"},
            "exact_colorbar_labels": {
                "name": "Γ_{G′}",
                "unit": "(mm⁻¹)",
            },
            "outer_frame_x_mm": [13.0, 116.0],
            "panel_frame_y_mm": [6.0, 34.0],
            "colorbar_frame_mm": [8.2, 6.0, 10.4, 34.0],
            "panel_gap_mm": 1.1,
            "font_family": UNIFIED_FONT_FAMILY,
            "font_size_pt": UNIFIED_FONT_SIZE_PT,
            "axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
            "line_width_pt": UNIFIED_LINE_WIDTH_PT,
            "tick_width_pt": UNIFIED_TICK_WIDTH_PT,
            "tick_length_pt": UNIFIED_TICK_LENGTH_PT,
            "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
            "minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
        },
        description=(
            "Four-panel-ready 120 × 42 mm strip for precomputed ΓG′ profiles. "
            "A single explicit color range is shared by every panel; the profile "
            "deliberately supplies no scientific z-range default."
        ),
    ),
}


def list_figure_profiles() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "label": profile.label,
            "figure_kind": profile.figure_kind,
            "size_mm": list(profile.size_mm),
            "description": profile.description,
        }
        for profile in _PROFILES.values()
    ]


def get_figure_profile(profile_id: str) -> FigureProfile:
    normalized = str(profile_id or "").strip()
    try:
        return deepcopy(_PROFILES[normalized])
    except KeyError as exc:
        known = ", ".join(sorted(_PROFILES))
        raise ValueError(f"Unknown figure profile `{profile_id}`. Available: {known}.") from exc


def figure_profile_payload(profile_id: str) -> dict[str, Any]:
    return get_figure_profile(profile_id).to_payload()


def figure_profile_render_options(
    profile_id: str,
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = get_figure_profile(profile_id)
    if profile.figure_kind != "curve":
        raise ValueError(f"Figure profile `{profile_id}` is not a curve profile.")
    options = deepcopy(profile.render_options)
    options.update(deepcopy(overrides or {}))
    options["_figure_profile_id"] = profile.profile_id
    return options


def figure_profile_frame_margins(profile_id: object) -> dict[str, float] | None:
    normalized = str(profile_id or "").strip()
    profile = _PROFILES.get(normalized)
    if profile is None or profile.frame_margins_mm is None:
        return None
    return deepcopy(profile.frame_margins_mm)


__all__ = [
    "FigureProfile",
    "figure_profile_frame_margins",
    "figure_profile_payload",
    "figure_profile_render_options",
    "get_figure_profile",
    "list_figure_profiles",
]
