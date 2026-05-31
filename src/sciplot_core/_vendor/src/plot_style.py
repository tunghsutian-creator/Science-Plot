from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import matplotlib.pyplot as plt
import scienceplots  # noqa: F401
import seaborn as sns
from matplotlib.figure import Figure

from src import mpl_backend  # noqa: F401
from src.plot_contract import (
    load_plot_contract,
    normalize_style_alias,
    palette_names,
    public_style_names,
    style_names,
)

_CONTRACT = load_plot_contract()

MM_TO_INCH = 1 / 25.4
PANEL_WIDTH_MM = _CONTRACT.global_frame.panel_width_mm
PANEL_HEIGHT_MM = _CONTRACT.global_frame.panel_height_mm

# Keep a single physical axis frame across panel types so exported figures align
# cleanly when compared side-by-side or composed into a board.
LEFT_MARGIN_MM = _CONTRACT.global_frame.left_margin_mm
RIGHT_MARGIN_MM = _CONTRACT.global_frame.right_margin_mm
BOTTOM_MARGIN_MM = _CONTRACT.global_frame.bottom_margin_mm
TOP_MARGIN_MM = _CONTRACT.global_frame.top_margin_mm

DEFAULT_STYLE_PRESET = _CONTRACT.defaults.style_preset
DEFAULT_PALETTE_PRESET = _CONTRACT.defaults.palette_preset
_PUBLICATION_BASE_STYLE_STACK = ("science", "nature", "no-latex")


@dataclass(frozen=True)
class TypographySpec:
    font_family: tuple[str, ...]
    font_size_pt: float
    legend_font_size_pt: float
    panel_label_size_pt: float
    panel_label_weight: str


@dataclass(frozen=True)
class StrokeSpec:
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
class SpacingSpec:
    panel_width_mm: float
    panel_height_mm: float
    left_margin_mm: float
    right_margin_mm: float
    bottom_margin_mm: float
    top_margin_mm: float
    axes_labelpad: float
    xtick_major_pad: float
    ytick_major_pad: float
    legend_inset_fraction: float


@dataclass(frozen=True)
class AnnotationSpec:
    legend_frameon: bool
    legend_tightness: str
    label_tightness: str


@dataclass(frozen=True)
class AxisFrameSpec:
    left: bool
    bottom: bool
    top: bool
    right: bool


@dataclass(frozen=True)
class ExportSpec:
    figure_dpi: int
    savefig_dpi: int
    savefig_format: str
    pdf_fonttype: int
    ps_fonttype: int
    color_space: str
    vector_preferred: bool
    accessibility_note: str


@dataclass(frozen=True)
class JournalStyleSpec:
    name: str
    description: str
    hard_constraints: bool
    preset_note: str
    typography: TypographySpec
    stroke: StrokeSpec
    spacing: SpacingSpec
    annotation: AnnotationSpec
    axis_frame: AxisFrameSpec
    export: ExportSpec


@dataclass(frozen=True)
class PaletteSpec:
    name: str
    description: str
    categorical: tuple[str, ...]
    sequential: str
    diverging: str


def mm_to_inch(value_mm: float) -> float:
    return value_mm * MM_TO_INCH


def _margin_fraction(total_mm: float, edge_mm: float) -> float:
    return edge_mm / total_mm


def _style_from_contract(name: str) -> JournalStyleSpec:
    spec = _CONTRACT.styles[name]
    return JournalStyleSpec(
        name=name,
        description=spec.description,
        hard_constraints=spec.hard_constraints,
        preset_note=spec.preset_note,
        typography=TypographySpec(
            font_family=spec.typography.font_family,
            font_size_pt=spec.typography.font_size_pt,
            legend_font_size_pt=spec.typography.legend_font_size_pt,
            panel_label_size_pt=spec.typography.panel_label_size_pt,
            panel_label_weight=spec.typography.panel_label_weight,
        ),
        stroke=StrokeSpec(**spec.stroke.__dict__),
        spacing=SpacingSpec(
            panel_width_mm=PANEL_WIDTH_MM,
            panel_height_mm=PANEL_HEIGHT_MM,
            left_margin_mm=LEFT_MARGIN_MM,
            right_margin_mm=RIGHT_MARGIN_MM,
            bottom_margin_mm=BOTTOM_MARGIN_MM,
            top_margin_mm=TOP_MARGIN_MM,
            axes_labelpad=spec.spacing.axes_labelpad,
            xtick_major_pad=spec.spacing.xtick_major_pad,
            ytick_major_pad=spec.spacing.ytick_major_pad,
            legend_inset_fraction=spec.spacing.legend_inset_fraction,
        ),
        annotation=AnnotationSpec(**spec.annotation.__dict__),
        axis_frame=AxisFrameSpec(**spec.axis_frame.__dict__),
        export=ExportSpec(**spec.export.__dict__),
    )


def _palette_from_contract(name: str) -> PaletteSpec:
    spec = _CONTRACT.palettes[name]
    return PaletteSpec(
        name=name,
        description=spec.description,
        categorical=spec.categorical,
        sequential=spec.sequential,
        diverging=spec.diverging,
    )


def _style_with_overrides(
    style_spec: JournalStyleSpec,
    overrides: Mapping[str, Mapping[str, object]] | None,
) -> JournalStyleSpec:
    if not overrides:
        return style_spec
    typography = style_spec.typography
    stroke = style_spec.stroke
    spacing = style_spec.spacing
    annotation = style_spec.annotation
    for group, values in overrides.items():
        if group == "typography":
            typography = replace(typography, **cast(Any, dict(values)))
        elif group == "stroke":
            stroke = replace(stroke, **cast(Any, dict(values)))
        elif group == "spacing":
            spacing = replace(spacing, **cast(Any, dict(values)))
        elif group == "annotation":
            annotation = replace(annotation, **cast(Any, dict(values)))
    return replace(
        style_spec,
        typography=typography,
        stroke=stroke,
        spacing=spacing,
        annotation=annotation,
    )


STYLE_PRESETS: dict[str, JournalStyleSpec] = {
    name: _style_from_contract(name)
    for name in style_names()
}


PALETTE_PRESETS: dict[str, PaletteSpec] = {
    name: _palette_from_contract(name)
    for name in palette_names()
}


_CURRENT_STYLE_PRESET = DEFAULT_STYLE_PRESET
_CURRENT_PALETTE_PRESET = DEFAULT_PALETTE_PRESET
_CURRENT_CUSTOM_PALETTE_COLORS: tuple[str, ...] | None = None


def normalize_style_preset(style_preset: str | None) -> str:
    return normalize_style_alias(style_preset)


def get_style_spec(style_preset: str | None = None) -> JournalStyleSpec:
    preset = normalize_style_preset(style_preset or _CURRENT_STYLE_PRESET)
    try:
        return STYLE_PRESETS[preset]
    except KeyError as exc:
        raise ValueError(f"Unknown style preset: {preset}.") from exc


def get_palette_spec(palette_preset: str | None = None) -> PaletteSpec:
    preset = palette_preset or _CURRENT_PALETTE_PRESET
    try:
        return PALETTE_PRESETS[preset]
    except KeyError as exc:
        raise ValueError(f"Unknown palette preset: {preset}.") from exc


def list_style_presets() -> tuple[str, ...]:
    return style_names()


def list_public_style_presets() -> tuple[str, ...]:
    return public_style_names()


def list_palette_presets() -> tuple[str, ...]:
    return palette_names()


def current_style_preset() -> str:
    return _CURRENT_STYLE_PRESET


def current_palette_preset() -> str:
    return _CURRENT_PALETTE_PRESET


def get_style_description(style_preset: str | None = None) -> str:
    spec = get_style_spec(style_preset)
    return spec.description


def get_palette_description(palette_preset: str | None = None) -> str:
    spec = get_palette_spec(palette_preset)
    return spec.description


def get_style_note(style_preset: str | None = None) -> str:
    spec = get_style_spec(style_preset)
    return spec.preset_note


def get_palette_swatches(palette_preset: str | None = None, limit: int = 6) -> tuple[str, ...]:
    spec = get_palette_spec(palette_preset)
    return spec.categorical[:limit]


def get_categorical_palette(
    palette_preset: str | None = None,
    *,
    n_colors: int | None = None,
) -> list[tuple[float, float, float]]:
    if _CURRENT_CUSTOM_PALETTE_COLORS and (
        palette_preset is None or palette_preset == _CURRENT_PALETTE_PRESET
    ):
        colors = _CURRENT_CUSTOM_PALETTE_COLORS
        if n_colors is None or n_colors <= len(colors):
            return sns.color_palette(colors, n_colors=n_colors)
        return sns.color_palette(colors, n_colors=n_colors)
    spec = get_palette_spec(palette_preset)
    colors = spec.categorical
    if n_colors is None or n_colors <= len(colors):
        return sns.color_palette(colors, n_colors=n_colors)
    return sns.color_palette(colors, n_colors=n_colors)


def get_sequential_cmap(palette_preset: str | None = None) -> str:
    return get_palette_spec(palette_preset).sequential


def get_diverging_cmap(palette_preset: str | None = None) -> str:
    return get_palette_spec(palette_preset).diverging


def current_spacing() -> SpacingSpec:
    return get_style_spec().spacing


def current_stroke() -> StrokeSpec:
    return get_style_spec().stroke


def current_typography() -> TypographySpec:
    return get_style_spec().typography


def apply_style(
    style_preset: str = DEFAULT_STYLE_PRESET,
    palette_preset: str = DEFAULT_PALETTE_PRESET,
    *,
    hard_overrides: Mapping[str, Mapping[str, object]] | None = None,
    palette_colors: tuple[str, ...] | list[str] | None = None,
    soft_overrides: Mapping[str, object] | None = None,
) -> None:
    global _CURRENT_CUSTOM_PALETTE_COLORS, _CURRENT_PALETTE_PRESET, _CURRENT_STYLE_PRESET

    normalized_style = normalize_style_preset(style_preset)
    style_spec = _style_with_overrides(get_style_spec(normalized_style), hard_overrides)
    palette_spec = get_palette_spec(palette_preset)
    resolved_palette = list(palette_colors) if palette_colors else palette_spec.categorical

    _CURRENT_STYLE_PRESET = normalized_style
    _CURRENT_PALETTE_PRESET = palette_preset
    _CURRENT_CUSTOM_PALETTE_COLORS = tuple(palette_colors) if palette_colors else None

    # The contract owns the public publication profiles. Hard style metrics live
    # here, while visual themes remain the soft-variation layer on top.
    plt.style.use(list(_PUBLICATION_BASE_STYLE_STACK))
    sns.set_theme(
        context="paper",
        style="ticks",
        palette=resolved_palette,
        rc={
            "figure.dpi": style_spec.export.figure_dpi,
            "savefig.dpi": style_spec.export.savefig_dpi,
            "savefig.format": style_spec.export.savefig_format,
            "savefig.bbox": None,
            "pdf.fonttype": style_spec.export.pdf_fonttype,
            "ps.fonttype": style_spec.export.ps_fonttype,
            "font.family": "sans-serif",
            "font.sans-serif": list(style_spec.typography.font_family),
            "mathtext.fontset": "custom",
            "mathtext.default": "regular",
            "mathtext.rm": "Arial",
            "mathtext.it": "Arial:italic",
            "mathtext.bf": "Arial:bold",
            "mathtext.sf": "Arial",
            "font.size": style_spec.typography.font_size_pt,
            "axes.labelsize": style_spec.typography.font_size_pt,
            "axes.titlesize": style_spec.typography.font_size_pt,
            "axes.labelpad": style_spec.spacing.axes_labelpad,
            "xtick.labelsize": style_spec.typography.font_size_pt,
            "ytick.labelsize": style_spec.typography.font_size_pt,
            "xtick.major.pad": style_spec.spacing.xtick_major_pad,
            "ytick.major.pad": style_spec.spacing.ytick_major_pad,
            "legend.fontsize": style_spec.typography.legend_font_size_pt,
            "axes.labelweight": "normal",
            "axes.titleweight": "normal",
            "axes.linewidth": style_spec.stroke.axis_linewidth_pt,
            "axes.spines.left": style_spec.axis_frame.left,
            "axes.spines.bottom": style_spec.axis_frame.bottom,
            "axes.spines.top": style_spec.axis_frame.top,
            "axes.spines.right": style_spec.axis_frame.right,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "xtick.major.width": style_spec.stroke.tick_width_pt,
            "ytick.major.width": style_spec.stroke.tick_width_pt,
            "xtick.major.size": style_spec.stroke.tick_length_pt,
            "ytick.major.size": style_spec.stroke.tick_length_pt,
            "xtick.minor.width": style_spec.stroke.minor_tick_width_pt,
            "ytick.minor.width": style_spec.stroke.minor_tick_width_pt,
            "xtick.minor.size": style_spec.stroke.minor_tick_length_pt,
            "ytick.minor.size": style_spec.stroke.minor_tick_length_pt,
            "lines.linewidth": style_spec.stroke.line_width_pt,
            "lines.markersize": style_spec.stroke.marker_size_pt,
            "legend.frameon": style_spec.annotation.legend_frameon,
        },
    )
    if soft_overrides:
        plt.rcParams.update(dict(soft_overrides))


def use_nature_style() -> None:
    apply_style("nature", DEFAULT_PALETTE_PRESET)


def create_panel_figure(
    width_mm: float | None = None,
    height_mm: float | None = None,
    *,
    left_margin_mm: float | None = None,
    right_margin_mm: float | None = None,
    bottom_margin_mm: float | None = None,
    top_margin_mm: float | None = None,
) -> tuple[Figure, plt.Axes]:
    spacing = current_spacing()
    panel_width_mm = spacing.panel_width_mm if width_mm is None else width_mm
    panel_height_mm = spacing.panel_height_mm if height_mm is None else height_mm
    left_mm = spacing.left_margin_mm if left_margin_mm is None else left_margin_mm
    right_mm = spacing.right_margin_mm if right_margin_mm is None else right_margin_mm
    bottom_mm = spacing.bottom_margin_mm if bottom_margin_mm is None else bottom_margin_mm
    top_mm = spacing.top_margin_mm if top_margin_mm is None else top_margin_mm

    fig, ax = plt.subplots(
        figsize=(mm_to_inch(panel_width_mm), mm_to_inch(panel_height_mm)),
        constrained_layout=False,
    )
    fig.subplots_adjust(
        left=_margin_fraction(panel_width_mm, left_mm),
        right=1 - _margin_fraction(panel_width_mm, right_mm),
        bottom=_margin_fraction(panel_height_mm, bottom_mm),
        top=1 - _margin_fraction(panel_height_mm, top_mm),
    )
    return fig, ax


def save_pdf(fig: plt.Figure, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format="pdf", bbox_inches=None, pad_inches=0.0)
    return path


apply_style(DEFAULT_STYLE_PRESET, DEFAULT_PALETTE_PRESET)
