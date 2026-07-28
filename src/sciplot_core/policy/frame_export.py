"""Declare shared frame typography, export formats, and legend geometry."""

from __future__ import annotations

import re
from pathlib import Path


SCIENTIFIC_UNIT_EXPRESSION_CONTRACT_VERSION = 1


SCIENTIFIC_UNIT_FACTOR_SEPARATOR = " "


SCIENTIFIC_UNIT_DIVISION_STYLE = "negative_exponent_product"


SCIENTIFIC_UNIT_EXPONENT_STYLE = "unicode_superscript"


SCIENTIFIC_UNIT_SOLIDUS_ALLOWED = False


UNIFIED_FONT_FAMILY = "Arial"


UNIFIED_FONT_SIZE_PT = 7.0


UNIFIED_LEGEND_FONT_SIZE_PT = 6.0


UNIFIED_LEGEND_KEY_LENGTH_MM = 4.0


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


CANONICAL_EXPORT_FORMATS = frozenset({"pdf", "svg", "png_300", "png_600", "tiff_300"})


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


DEFAULT_LOG_MINOR_TICK_COUNT = 5


DEFAULT_LOG_MINOR_MULTIPLIERS = (2.0, 4.0, 6.0, 8.0)


AUTO_LOG_BOUND_PADDING_FACTOR = 1.10


MAX_AUTO_LOG_EMPTY_RANGE_FACTOR = 2.0


LOG_NEAR_DECADE_RATIO = 1.05


DEFAULT_LINEAR_TARGET_MAJOR_TICKS = 5


DEFAULT_LINEAR_AXIS_PADDING_FRACTION = 0.02


DEFAULT_LEGEND_CURVE_CLEARANCE_MM = 2.0


DEFAULT_LEGEND_EDGE_PADDING_MM = 1.0
