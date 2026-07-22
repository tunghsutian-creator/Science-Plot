from __future__ import annotations

import math
import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_FIGURE_SIZE = "60x55"
WIDE_FIGURE_SIZE = "120x55"
STACKED_SPECTRUM_FIGURE_SIZE = "120x110"
JAMA_EDITORIAL_PALETTE_ID = "jama_editorial"
NPG_MODERN_PALETTE_ID = "npg_modern"
TOL_BRIGHT_PALETTE_ID = "tol_bright"
CONTROL_FIRST_BRIGHT_PALETTE_ID = "control_first_bright"
DEFAULT_PALETTE_PRESET = CONTROL_FIRST_BRIGHT_PALETTE_ID
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
# Ordinary plots use a stable positional contract: index 0 is the control in
# near-black, followed by six categorical colors in fixed order.  Heatmap,
# contour, and colorbar colors remain independently owned scientific semantics.
CONTROL_FIRST_BRIGHT_COLORS = (
    "#222222",
    "#3568C0",
    "#C83E4D",
    "#2A9D8F",
    "#D99A24",
    "#7C9ED9",
    "#7B61A8",
)
DEFAULT_PALETTE_COLORS = CONTROL_FIRST_BRIGHT_COLORS
DEFAULT_SCALAR_FIELD_COLORMAP_ID = "sciplot_cividis"
DEFAULT_SCALAR_FIELD_COLORS = (
    "#00204C",
    "#173F5F",
    "#365C6D",
    "#587273",
    "#7C8973",
    "#A59C74",
    "#CFB36F",
    "#F6D35B",
    "#FFEA46",
)

# One typography/stroke contract is shared by every SciPlot presentation.
# Templates may still choose semantic behavior (for example, log axes,
# markers-on, stacking, or a colorbar), but they do not get their own visual
# sizes or widths.
UNIFIED_FONT_FAMILY = "Arial"
UNIFIED_FONT_SIZE_PT = 7.0
UNIFIED_LEGEND_FONT_SIZE_PT = 6.0
UNIFIED_PANEL_LABEL_SIZE_PT = 7.0
UNIFIED_LINE_WIDTH_PT = 1.2
UNIFIED_AXIS_LINEWIDTH_PT = 0.8
UNIFIED_TICK_WIDTH_PT = 0.8
UNIFIED_TICK_LENGTH_PT = 2.8
UNIFIED_MINOR_TICK_WIDTH_PT = 0.8
UNIFIED_MINOR_TICK_LENGTH_PT = 1.5
UNIFIED_MARKER_SIZE_PT = 2.0
UNIFIED_MARKER_LINE_WIDTH_PT = 0.8
UNIFIED_FOREGROUND_COLOR = "#111111"
UNIFIED_LEFT_MARGIN_MM = 14.0
UNIFIED_RIGHT_MARGIN_MM = 4.5
UNIFIED_BOTTOM_MARGIN_MM = 11.0
UNIFIED_TOP_MARGIN_MM = 5.5
UNIFIED_HARD_OPTION_KEYS = frozenset(
    {
        "font_size_pt",
        "legend_font_size_pt",
        "axis_linewidth_pt",
        "tick_width_pt",
        "tick_length_pt",
        "minor_tick_width_pt",
        "minor_tick_length_pt",
        "line_width_pt",
        "marker_size",
        "marker_size_pt",
        "marker_line_width_pt",
        "contour_line_width_pt",
        "highlight_contour_line_width_pt",
    }
)

DEFAULT_LINE_STYLE_SEQUENCE = (
    "solid",
    "dashed",
    "dotted",
    "dash-dot",
    "dash-dot-dot",
    "dashed-fine",
    "dotted-fine",
)
DEFAULT_CURVE_LINE_STYLE_SEQUENCE = ("solid",)
FIGURE_SIZE_PRESETS = ("60x55", "120x55", "180x55", "60x110", "120x110", "180x110")

DEFAULT_EXPORT_FORMATS_POLICY = ("pdf", "tiff_300")
CANONICAL_EXPORT_FORMATS = frozenset(
    {"pdf", "svg", "png_300", "png_600", "tiff_300"}
)
EXPORT_FORMAT_ALIASES = {
    "pdf": "pdf",
    "svg": "svg",
    "png": "png_300",
    "png_300": "png_300",
    "png_600": "png_600",
    "tif_300": "tiff_300",
    "tiff": "tiff_300",
    "tiff_300": "tiff_300",
}
_LEGACY_RECORDED_EXPORT_ALIASES = {
    "tif": "tiff_300",
    "tiff300": "tiff_300",
    "tiff_300dpi": "tiff_300",
}
SUPPORTED_EXPORT_FORMATS = frozenset(EXPORT_FORMAT_ALIASES)


def canonical_export_format(value: object, *, allow_legacy: bool = False) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    canonical = EXPORT_FORMAT_ALIASES.get(normalized)
    if canonical is None and allow_legacy:
        canonical = _LEGACY_RECORDED_EXPORT_ALIASES.get(normalized)
    if canonical is None:
        supported = ", ".join(sorted(SUPPORTED_EXPORT_FORMATS))
        raise ValueError(
            f"Unsupported export format {value!r}. Supported formats: {supported}."
        )
    return canonical


def canonical_figure_stem(path_value: object) -> str:
    """Return the shared PDF/TIFF pairing key for one exported figure."""

    stem = Path(str(path_value)).stem
    return re.sub(r"_\d+dpi$", "", stem, flags=re.IGNORECASE).casefold()


def normalize_export_formats(
    values: object,
    *,
    default: tuple[str, ...] = DEFAULT_EXPORT_FORMATS_POLICY,
) -> tuple[str, ...]:
    if not isinstance(values, list | tuple):
        return tuple(default)
    requested = [value for value in values if str(value).strip()]
    if not requested:
        return tuple(default)
    canonical = [canonical_export_format(value) for value in requested]
    if len(set(canonical)) != len(canonical):
        raise ValueError(
            "Export aliases that produce the same output artifact cannot be "
            "requested together. Choose one name for each format/DPI."
        )
    return tuple(canonical)
DEFAULT_LOG_TICK_FORMAT = "%Ve"
# Five subdivisions per decade give four visible minor ticks (2, 4, 6, 8),
# matching the sparse publication style used for rheology modulus axes.
DEFAULT_LOG_MINOR_TICK_COUNT = 5
DEFAULT_LOG_MINOR_MULTIPLIERS = (2.0, 4.0, 6.0, 8.0)
AUTO_LOG_BOUND_PADDING_FACTOR = 1.10
MAX_AUTO_LOG_EMPTY_RANGE_FACTOR = 2.0
LOG_NEAR_DECADE_RATIO = 1.05
DEFAULT_LINEAR_TARGET_MAJOR_TICKS = 5
DEFAULT_LINEAR_AXIS_PADDING_FRACTION = 0.02
DEFAULT_LEGEND_CURVE_CLEARANCE_MM = 2.0
DEFAULT_LEGEND_EDGE_PADDING_MM = 1.0
# Extra graph-local clearance beyond the physical marker/error-stroke envelope.
# Axis limits use data units while glyphs use points, so this reserve protects
# against vector stroke caps and raster rounding at the final physical size.
MIN_VISUAL_EXTENT_CLEARANCE_MM = 0.25
MAX_LEGEND_RESERVE_ITERATIONS = 6
MAX_LOG_LEGEND_RESERVE_DECADES = 0.70
MAX_LINEAR_LEGEND_RESERVE_FRACTION = 0.60
MAX_POINT_LINE_MARKERS_PER_SERIES = 32
INSIDE_LEGEND_POSITIONS = ("upper_right", "lower_right", "upper_left", "lower_left")
REMOVED_OUTSIDE_LEGEND_POSITIONS = frozenset(
    {"outside", "outside_right", "right_outside"}
)
DEFAULT_CATEGORICAL_SUMMARY = "median_iqr"
CATEGORICAL_SUMMARY_OPTIONS = ("median_iqr", "raw_only")
DEFAULT_RAW_POINT_JITTER_FRACTION = 0.12
MAX_RAW_POINT_JITTER_FRACTION = 0.35
MIN_BOX_REPLICATES = 2
CATEGORICAL_BOX_FILL_FRACTION = 0.36
CATEGORICAL_BOX_FILL_TRANSPARENCY = 72
CATEGORICAL_BOX_LINE_WIDTH_PT = UNIFIED_LINE_WIDTH_PT
CATEGORICAL_BAR_WIDTH_FRACTION = 0.36
CATEGORICAL_BAR_FILL_TRANSPARENCY = 15
CATEGORICAL_ERROR_CAP_TO_BAR_RATIO = 0.50
TENSILE_X_AXIS_LABEL = "Strain (%)"
TENSILE_Y_AXIS_LABEL = "Stress (MPa)"
TENSILE_AXIS_PADDING_FRACTION = 0.06

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
        "x_minor_tick_count",
        "y_minor_tick_count",
        "x_minor_ticks",
        "y_minor_ticks",
        "show_y_ticks",
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
        "zscale",
        "z_min",
        "z_max",
        "z_ticks",
        "z_tick_format",
        "z_label_override",
        "colormap_name",
        "colormap_colors",
        "color_invert",
        "field_mapping",
        "field_draw_mode",
        "field_transparency",
        "contour_levels",
        "contour_color",
        "contour_line_style",
        "contour_line_width_pt",
        "contour_labels",
        "highlight_contour_levels",
        "highlight_contour_color",
        "highlight_contour_line_style",
        "highlight_contour_line_width_pt",
        "colorbar_width_mm",
        "colorbar_height_mm",
        "colorbar_direction",
        "colorbar_manual_position",
        "colorbar_horz_manual",
        "colorbar_vert_manual",
        "colorbar_foreground_color",
        "colorbar_background_color",
        "colorbar_background_transparency",
        "colorbar_background_x_fraction",
        "colorbar_background_y_fraction",
        "colorbar_background_width_fraction",
        "colorbar_background_height_fraction",
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

# A validated rule certificate covers the rule's scientific rendering contract.
# Runtime requests may vary only these presentation-only fields while retaining
# automatic ready-to-use authority. Every other public render option must equal
# the certified rule/axis default or the request leaves the validated envelope.
VALIDATED_VISUAL_OVERRIDE_KEYS = frozenset(
    {
        "size",
        "x_tick_density",
        "y_tick_density",
        "x_tick_edge_labels",
        "y_tick_edge_labels",
        "minor_tick_count",
        "series_order",
        "series_styles",
        "line_style_sequence",
        "marker_sequence",
        "marker_size",
        "marker_fill_mode",
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
        "legend_position",
        "legend_curve_clearance_mm",
        "legend_edge_padding_mm",
        "series_label_mode",
        "colormap_name",
        "colormap_colors",
        "color_invert",
        "contour_color",
        "contour_line_style",
        "contour_line_width_pt",
        "contour_labels",
        "highlight_contour_color",
        "highlight_contour_line_style",
        "highlight_contour_line_width_pt",
        "colorbar_width_mm",
        "colorbar_height_mm",
        "colorbar_direction",
        "colorbar_manual_position",
        "colorbar_horz_manual",
        "colorbar_vert_manual",
        "colorbar_foreground_color",
        "colorbar_background_color",
        "colorbar_background_transparency",
        "colorbar_background_x_fraction",
        "colorbar_background_y_fraction",
        "colorbar_background_width_fraction",
        "colorbar_background_height_fraction",
        "style_preset",
        "palette_preset",
        "visual_theme_id",
    }
) - UNIFIED_HARD_OPTION_KEYS

DELIVERY_DIR = "delivery"
# The visible user handoff has three artifact groups plus one launcher.  PDF
# and TIFF are both figures and therefore share one directory.  DELIVERY_DIR
# remains the compatibility fallback for development callers that do not
# record an explicit visible delivery root.
DELIVERY_DATA_DIR = "data"
DELIVERY_FIGURES_DIR = "figures"
DELIVERY_PDF_DIR = DELIVERY_FIGURES_DIR
DELIVERY_TIFF_DIR = DELIVERY_FIGURES_DIR
DELIVERY_PROJECT_DIR = "project"
DELIVERY_LAUNCHER = "Open_in_Veusz.command"

# Kept as compatibility symbols for older manifests and callers.  They are no
# longer created inside the user-facing delivery package; runtime evidence
# stays in the ordinary run output instead.
DELIVERY_EDITABLE_DIR = "editable"
DELIVERY_INTERNAL_DIR = "_sciplot_internal"

DEFAULT_RENDER_OPTIONS: dict[str, Any] = {
    "legend_position": "auto",
    "series_label_mode": "legend",
    "visual_theme_id": "clean_light",
    "style_preset": "nature",
    "size": DEFAULT_FIGURE_SIZE,
    "palette_preset": DEFAULT_PALETTE_PRESET,
    "font_size_pt": UNIFIED_FONT_SIZE_PT,
    "legend_font_size_pt": UNIFIED_LEGEND_FONT_SIZE_PT,
    "axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
    "tick_width_pt": UNIFIED_TICK_WIDTH_PT,
    "tick_length_pt": UNIFIED_TICK_LENGTH_PT,
    "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
    "minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
    "line_width_pt": UNIFIED_LINE_WIDTH_PT,
    "marker_size": UNIFIED_MARKER_SIZE_PT,
    "marker_line_width_pt": UNIFIED_MARKER_LINE_WIDTH_PT,
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
        raise ValueError(
            "Raw-point jitter fraction must be a finite number between 0 and 0.35."
        ) from exc
    if (
        not math.isfinite(normalized)
        or not 0.0 <= normalized <= MAX_RAW_POINT_JITTER_FRACTION
    ):
        raise ValueError(
            "Raw-point jitter fraction must be a finite number between 0 and 0.35."
        )
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
    if upper_exponent > lower_exponent:
        preceding_decade = 10.0 ** (upper_exponent - 1)
        if maximum / preceding_decade <= LOG_NEAR_DECADE_RATIO:
            upper_exponent -= 1
    ticks = [10.0**exponent for exponent in range(lower_exponent, upper_exponent + 1)]
    if len(ticks) == 1 and maximum > minimum:
        only = ticks[0]
        ticks = [only / 10.0, only] if only >= maximum else [only, only * 10.0]
    return tuple(ticks)


def compact_linear_axis(
    values: Iterable[object],
    *,
    target_major_ticks: int = DEFAULT_LINEAR_TARGET_MAJOR_TICKS,
    padding_fraction: float = DEFAULT_LINEAR_AXIS_PADDING_FRACTION,
) -> tuple[float, float, tuple[float, ...]] | None:
    """Build a compact linear range with four to six readable major ticks."""

    finite: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            finite.append(number)
    if not finite:
        return None
    data_min = min(finite)
    data_max = max(finite)
    if math.isclose(data_min, data_max):
        half_span = max(abs(data_min) * 0.05, 1.0)
        data_min -= half_span
        data_max += half_span
    span = data_max - data_min
    padding = span * max(float(padding_fraction), 0.0)
    display_min = data_min - padding
    display_max = data_max + padding
    desired_count = max(int(target_major_ticks), 2)
    raw_step = span / max(desired_count - 1, 1)
    exponent = math.floor(math.log10(raw_step))
    steps = sorted(
        {
            mantissa * 10.0**candidate_exponent
            for candidate_exponent in range(exponent - 1, exponent + 2)
            for mantissa in (1.0, 2.0, 2.5, 5.0, 10.0)
        }
    )
    candidates: list[tuple[tuple[float, ...], tuple[float, ...]]] = []
    for step in steps:
        start_index = math.ceil(display_min / step - 1e-12)
        end_index = math.floor(display_max / step + 1e-12)
        if end_index < start_index:
            continue
        ticks = tuple(
            round(index * step, 12) for index in range(start_index, end_index + 1)
        )
        if len(ticks) < 2:
            continue
        count_penalty = 0.0 if 4 <= len(ticks) <= 6 else 100.0
        score = (
            count_penalty,
            float(abs(len(ticks) - desired_count)),
            abs(math.log(step / raw_step)),
        )
        candidates.append((score, ticks))
    ticks = (
        min(candidates, key=lambda item: item[0])[1]
        if candidates
        else (data_min, data_max)
    )
    return float(display_min), float(display_max), ticks


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
    if (
        "complex modulus" in folded
        or "g*" in folded
        or "g∗" in folded
        or token == "complexmodulus"
    ):
        return RHEOLOGY_METRIC_AXIS_LABELS["complex_modulus"]
    if (
        "loss modulus" in folded
        or "g″" in folded
        or 'g"' in folded
        or "g''" in folded
        or token == "lossmodulus"
    ):
        return RHEOLOGY_METRIC_AXIS_LABELS["loss_modulus"]
    if (
        "storage modulus" in folded
        or "g′" in folded
        or "g'" in folded
        or token == "storagemodulus"
    ):
        return RHEOLOGY_METRIC_AXIS_LABELS["storage_modulus"]
    return RHEOLOGY_METRIC_AXIS_LABELS.get(token)


CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS: dict[str, Any] = {
    **DEFAULT_RENDER_OPTIONS,
    "legend_position": "none",
    "series_label_mode": "none",
    "marker_sequence": ["circle"],
    "marker_fill_mode": "filled",
    "raw_point_jitter_fraction": 0.18,
    "palette_preset": DEFAULT_PALETTE_PRESET,
    "line_alpha": 1.0,
    "marker_alpha": 0.78,
}


CURVE_RENDER_OPTIONS: dict[str, Any] = {
    **DEFAULT_RENDER_OPTIONS,
    "palette_preset": JAMA_EDITORIAL_PALETTE_ID,
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
    "x_min": 400.0,
    "x_max": 4000.0,
    "x_tick_density": "auto",
}


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
__all__ = [
    "CANONICAL_EXPORT_FORMATS",
    "CONTROL_FIRST_BRIGHT_COLORS",
    "CONTROL_FIRST_BRIGHT_PALETTE_ID",
    "DEFAULT_EXPORT_FORMATS_POLICY",
    "EXPORT_FORMAT_ALIASES",
    "AUTO_LOG_BOUND_PADDING_FACTOR",
    "UNIFIED_AXIS_LINEWIDTH_PT",
    "UNIFIED_FONT_FAMILY",
    "UNIFIED_FONT_SIZE_PT",
    "UNIFIED_FOREGROUND_COLOR",
    "UNIFIED_HARD_OPTION_KEYS",
    "UNIFIED_LEGEND_FONT_SIZE_PT",
    "UNIFIED_LEFT_MARGIN_MM",
    "UNIFIED_LINE_WIDTH_PT",
    "UNIFIED_MARKER_LINE_WIDTH_PT",
    "UNIFIED_MARKER_SIZE_PT",
    "UNIFIED_MINOR_TICK_LENGTH_PT",
    "UNIFIED_MINOR_TICK_WIDTH_PT",
    "UNIFIED_PANEL_LABEL_SIZE_PT",
    "UNIFIED_RIGHT_MARGIN_MM",
    "UNIFIED_BOTTOM_MARGIN_MM",
    "UNIFIED_TOP_MARGIN_MM",
    "UNIFIED_TICK_LENGTH_PT",
    "UNIFIED_TICK_WIDTH_PT",
    "TENSILE_AXIS_PADDING_FRACTION",
    "TENSILE_X_AXIS_LABEL",
    "TENSILE_Y_AXIS_LABEL",
    "DEFAULT_FIGURE_SIZE",
    "DEFAULT_LAYOUT_POLICY",
    "DEFAULT_LOG_MINOR_MULTIPLIERS",
    "DEFAULT_LOG_MINOR_TICK_COUNT",
    "DEFAULT_LOG_TICK_FORMAT",
    "MIN_VISUAL_EXTENT_CLEARANCE_MM",
    "DEFAULT_PALETTE_COLORS",
    "DEFAULT_PALETTE_PRESET",
    "DEFAULT_RENDER_OPTIONS",
    "DEFAULT_SCALAR_FIELD_COLORS",
    "DEFAULT_SCALAR_FIELD_COLORMAP_ID",
    "CURVE_RENDER_OPTIONS",
    "DELIVERY_DIR",
    "DELIVERY_DATA_DIR",
    "DELIVERY_EDITABLE_DIR",
    "DELIVERY_FIGURES_DIR",
    "DELIVERY_INTERNAL_DIR",
    "DELIVERY_LAUNCHER",
    "DELIVERY_PDF_DIR",
    "DELIVERY_PROJECT_DIR",
    "DELIVERY_TIFF_DIR",
    "FIGURE_SIZE_PRESETS",
    "FTIR_SPECTRUM_RENDER_OPTIONS",
    "FTIR_LAYOUT_POLICY",
    "JAMA_EDITORIAL_COLORS",
    "JAMA_EDITORIAL_PALETTE_ID",
    "LAYOUT_POLICIES",
    "LayoutPolicy",
    "MAX_LEGEND_RESERVE_ITERATIONS",
    "MAX_AUTO_LOG_EMPTY_RANGE_FACTOR",
    "MAX_LINEAR_LEGEND_RESERVE_FRACTION",
    "MAX_LOG_LEGEND_RESERVE_DECADES",
    "NPG_MODERN_COLORS",
    "NPG_MODERN_PALETTE_ID",
    "STACKED_SPECTRUM_FIGURE_SIZE",
    "SPECTRUM_STACK_RENDER_OPTIONS",
    "STRESS_RELAXATION_LAYOUT_POLICY",
    "SUPPORTED_EXPORT_FORMATS",
    "StrokePolicy",
    "TORQUE_CURVE_RENDER_OPTIONS",
    "TORQUE_LAYOUT_POLICY",
    "TORQUE_OFFSET_STACK_RENDER_OPTIONS",
    "TOL_BRIGHT_COLORS",
    "TOL_BRIGHT_PALETTE_ID",
    "VALIDATED_VISUAL_OVERRIDE_KEYS",
    "WIDE_FIGURE_SIZE",
    "anchored_log_decade_ticks",
    "canonical_export_format",
    "canonical_figure_stem",
    "compact_linear_axis",
    "layout_policy_for_semantic",
    "layout_policy_payload",
    "normalize_export_formats",
    "rheology_metric_axis_label",
]
