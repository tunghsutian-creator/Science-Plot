"""Define the immutable data models and template-kind constants used by Studio rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
from sciplot_core.policy import (
    DEFAULT_PALETTE_COLORS,
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_FONT_FAMILY,
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_LEGEND_FONT_SIZE_PT,
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MINOR_TICK_LENGTH_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_TICK_LENGTH_PT,
    UNIFIED_TICK_WIDTH_PT,
    UNIFIED_RIGHT_MARGIN_MM,
    UNIFIED_BOTTOM_MARGIN_MM,
    UNIFIED_TOP_MARGIN_MM,
)


DEFAULT_PALETTE = DEFAULT_PALETTE_COLORS


STACKED_TEMPLATE_IDS = {"stacked_curve"}


CATEGORICAL_TEMPLATE_IDS = {"bar", "box", "box_strip"}


CATEGORICAL_SERIES_KINDS = {
    "categorical_replicates",
    "categorical_components",
    "categorical_grouped_replicates",
}


CATEGORICAL_POINT_LINE_KIND = "categorical_point_line"


IMPACT_POINT_LINE_SUMMARY_KIND = "impact_point_line_summary"


IMPACT_POINT_LINE_MARKER_KIND = "impact_point_line_summary_marker"


IMPACT_POINT_LINE_RAW_KIND = "impact_point_line_raw_points"


IMPACT_POINT_LINE_KINDS = {
    IMPACT_POINT_LINE_SUMMARY_KIND,
    IMPACT_POINT_LINE_MARKER_KIND,
    IMPACT_POINT_LINE_RAW_KIND,
}


SCALAR_FIELD_TEMPLATE_IDS = {"heatmap"}


POINT_LINE_MARKERS = ("circle", "square", "diamond", "triangle")


class StudioPreparationBlocked(ValueError):
    state = "needs_rule_repair"

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True)
class SeriesEncodingProvenance:
    """Explain which authority selected each resolved visual channel."""

    color_source: str = "unresolved_series"
    line_style_source: str = "unresolved_series"
    marker_source: str = "unresolved_series"
    marker_fill_source: str = "unresolved_series"
    marker_line_source: str = "unresolved_series"
    request_bound_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class StudioSeries:
    label: str
    x_name: str
    y_name: str
    x_values: tuple[float, ...]
    y_values: tuple[float, ...]
    color: str
    error_values: tuple[float, ...] = ()
    line_width: float | None = None
    marker: str | bool | None = None
    marker_size: float | None = None
    marker_alpha: float | None = None
    marker_fill_color: str | None = None
    marker_line_color: str | None = None
    marker_line_width: float | None = None
    line_style: str = "solid"
    presentation_kind: str = "curve"
    category_position: float | None = None
    component_labels: tuple[str, ...] = ()
    source_artifacts: tuple[tuple[str, str], ...] = ()
    encoding_provenance: SeriesEncodingProvenance = field(
        default_factory=SeriesEncodingProvenance
    )


@dataclass(frozen=True)
class StudioSourceFrame:
    label: str
    path: Path
    sha256: str
    frame: pd.DataFrame


@dataclass(frozen=True)
class _VeuszStyleContract:
    font_family: str = UNIFIED_FONT_FAMILY
    font_size_pt: float = UNIFIED_FONT_SIZE_PT
    legend_font_size_pt: float = UNIFIED_LEGEND_FONT_SIZE_PT
    axis_linewidth_pt: float = UNIFIED_AXIS_LINEWIDTH_PT
    tick_width_pt: float = UNIFIED_TICK_WIDTH_PT
    tick_length_pt: float = UNIFIED_TICK_LENGTH_PT
    minor_tick_width_pt: float = UNIFIED_MINOR_TICK_WIDTH_PT
    minor_tick_length_pt: float = UNIFIED_MINOR_TICK_LENGTH_PT
    line_width_pt: float = UNIFIED_LINE_WIDTH_PT
    line_alpha: float = 0.92
    marker_alpha: float = 0.95
    marker_size_pt: float = UNIFIED_MARKER_SIZE_PT
    marker_line_width_pt: float = UNIFIED_MARKER_LINE_WIDTH_PT
    axes_labelpad_pt: float = 2.0
    xtick_major_pad_pt: float = 1.4
    ytick_major_pad_pt: float = 1.4
    legend_inset_fraction: float = 0.025
    legend_frameon: bool = False
    left_margin_mm: float = UNIFIED_LEFT_MARGIN_MM
    right_margin_mm: float = UNIFIED_RIGHT_MARGIN_MM
    bottom_margin_mm: float = UNIFIED_BOTTOM_MARGIN_MM
    top_margin_mm: float = UNIFIED_TOP_MARGIN_MM


@dataclass(frozen=True)
class _VeuszAxisContract:
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    x_ticks: tuple[float, ...] = ()
    y_ticks: tuple[float, ...] = ()
