"""Define immutable models for the serialized SciPlot plot contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DefaultsSpec:
    style_preset: str
    palette_preset: str


@dataclass(frozen=True)
class GlobalFrameSpec:
    panel_width_mm: float
    panel_height_mm: float
    left_margin_mm: float
    right_margin_mm: float
    bottom_margin_mm: float
    top_margin_mm: float


@dataclass(frozen=True)
class AxisPolicySpec:
    linear_nice_steps: tuple[float, ...]
    linear_outer_padding_fraction: float
    linear_force_visible_labeled_endpoints: bool
    log_display_steps: tuple[float, ...]
    log_label_mode: str
    log_allow_unlabeled_outer_padding: bool
    bar_zero_baseline_no_lower_padding: bool
    tensile_y_include_zero: bool
    stacked_x_use_standard_endpoint_policy: bool


@dataclass(frozen=True)
class SizePresetSpec:
    label: str
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class TypographyContract:
    font_family: tuple[str, ...]
    font_size_pt: float
    legend_font_size_pt: float
    panel_label_size_pt: float
    panel_label_weight: str


@dataclass(frozen=True)
class StrokeContract:
    axis_linewidth_pt: float
    tick_width_pt: float
    tick_length_pt: float
    minor_tick_width_pt: float
    minor_tick_length_pt: float
    line_width_pt: float
    line_alpha: float
    marker_alpha: float
    fill_alpha: float
    max_fill_alpha: float
    marker_size_pt: float


@dataclass(frozen=True)
class SpacingContract:
    axes_labelpad: float
    xtick_major_pad: float
    ytick_major_pad: float
    legend_inset_fraction: float


@dataclass(frozen=True)
class AnnotationContract:
    legend_frameon: bool
    legend_tightness: str
    label_tightness: str


@dataclass(frozen=True)
class AxisFrameContract:
    left: bool
    bottom: bool
    top: bool
    right: bool


@dataclass(frozen=True)
class ExportContract:
    figure_dpi: int
    savefig_dpi: int
    savefig_format: str
    pdf_fonttype: int
    ps_fonttype: int
    color_space: str
    vector_preferred: bool
    accessibility_note: str


@dataclass(frozen=True)
class StyleContract:
    label: str
    public: bool
    display_group: str
    description: str
    hard_constraints: bool
    preset_note: str
    recommended_palette_preset: str
    recommended_visual_theme_id: str | None
    typography: TypographyContract
    stroke: StrokeContract
    spacing: SpacingContract
    annotation: AnnotationContract
    axis_frame: AxisFrameContract
    export: ExportContract


@dataclass(frozen=True)
class PaletteContract:
    label: str
    public: bool
    description: str
    categorical: tuple[str, ...]
    sequential: str
    diverging: str


@dataclass(frozen=True)
class TemplateContract:
    label: str
    description: str
    category: str
    presentation_kind: str
    default_size: str
    allowed_sizes: tuple[str, ...]
    editable_options: tuple[str, ...]
    default_options: dict[str, Any]
    available_styles: tuple[str, ...]
    available_palettes: tuple[str, ...]
    hard_rules: tuple[str, ...]
    soft_rules: tuple[str, ...]


@dataclass(frozen=True)
class ValidationRuleContract:
    label: str
    description: str
    severity: str
    tolerance_mm: float | None = None


@dataclass(frozen=True)
class PlotContract:
    version: int
    defaults: DefaultsSpec
    style_aliases: dict[str, str]
    global_frame: GlobalFrameSpec
    axis_policy: AxisPolicySpec
    size_presets: dict[str, SizePresetSpec]
    special_layouts: dict[str, dict[str, Any]]
    qa_profiles: dict[str, dict[str, Any]]
    styles: dict[str, StyleContract]
    palettes: dict[str, PaletteContract]
    templates: dict[str, TemplateContract]
    validation_rules: dict[str, ValidationRuleContract]


__all__ = [
    "AnnotationContract",
    "AxisFrameContract",
    "AxisPolicySpec",
    "DefaultsSpec",
    "ExportContract",
    "GlobalFrameSpec",
    "PaletteContract",
    "PlotContract",
    "SizePresetSpec",
    "SpacingContract",
    "StrokeContract",
    "StyleContract",
    "TemplateContract",
    "TypographyContract",
    "ValidationRuleContract",
]
