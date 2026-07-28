"""Define categorical geometry, color, mechanical labels, and point spread."""

from __future__ import annotations

import math
import re

from sciplot_core.policy.frame_export import (
    UNIFIED_LEGEND_KEY_LENGTH_MM,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_RIGHT_MARGIN_MM,
)

MIN_VISUAL_EXTENT_CLEARANCE_MM = 0.25


MAX_LEGEND_RESERVE_ITERATIONS = 6


MAX_LOG_LEGEND_RESERVE_DECADES = 0.70


MAX_LINEAR_LEGEND_RESERVE_FRACTION = 0.60


INSIDE_LEGEND_POSITIONS = ("upper_right", "lower_right", "upper_left", "lower_left")


REMOVED_OUTSIDE_LEGEND_POSITIONS = frozenset(
    {"outside", "outside_right", "right_outside"}
)


DEFAULT_CATEGORICAL_SUMMARY = "median_iqr"


CATEGORICAL_SUMMARY_OPTIONS = ("median_iqr", "raw_only")


DEFAULT_RAW_POINT_JITTER_FRACTION = 0.12


MAX_RAW_POINT_JITTER_FRACTION = 0.35


MIN_BOX_REPLICATES = 2


CATEGORICAL_FILL_COLORS_BY_BASE = {
    "#222222": "#B7B7B7",
    "#3568C0": "#AFC6ED",
    "#C83E4D": "#F0B4BA",
    "#2A9D8F": "#A7D9D2",
    "#D99A24": "#EED59F",
    "#7C9ED9": "#CCD9EF",
    "#7B61A8": "#D0C5E0",
}


CATEGORICAL_KEYLINE_COLORS_BY_BASE = {
    "#222222": "#696969",
    "#3568C0": "#7898D1",
    "#C83E4D": "#D97D87",
    "#2A9D8F": "#67B7AC",
    "#D99A24": "#E0B761",
    "#7C9ED9": "#A7BCE0",
    "#7B61A8": "#A999C2",
}


CATEGORICAL_BAR_WIDTH_FRACTION = 0.32


CATEGORICAL_GROUPED_BAR_WIDTH_FRACTION = 0.26


CATEGORICAL_GROUPED_BAR_CENTER_OFFSET = 0.16


CATEGORICAL_GROUPED_LEGEND_SWATCH_LEFT_FRACTION = 0.05


CATEGORICAL_GROUPED_LEGEND_SWATCH_WIDTH_FRACTION = 0.16


CATEGORICAL_GROUPED_LEGEND_LABEL_X_FRACTION = 0.23


CATEGORICAL_BOX_TO_BAR_WIDTH_RATIO = 4.0 / 3.0


CATEGORICAL_BOX_FILL_FRACTION = (
    CATEGORICAL_BAR_WIDTH_FRACTION * CATEGORICAL_BOX_TO_BAR_WIDTH_RATIO
)


CATEGORICAL_BOX_FILL_TRANSPARENCY = 0


CATEGORICAL_POINT_BAND_BASE_BOX_RATIO = 0.50


CATEGORICAL_POINT_BAND_LOG2_STEP = 0.12


CATEGORICAL_POINT_BAND_MAX_BOX_RATIO = 0.90


CATEGORICAL_BOX_MIN_PHYSICAL_ASPECT_RATIO = 0.72


CATEGORICAL_BOX_MIN_MARKER_DIAMETERS = 2.0


CATEGORICAL_KEYLINE_WIDTH_PT = 0.70


CATEGORICAL_BOX_LINE_WIDTH_PT = CATEGORICAL_KEYLINE_WIDTH_PT


CATEGORICAL_BAR_FILL_TRANSPARENCY = 0


CATEGORICAL_BAR_LINE_WIDTH_PT = CATEGORICAL_KEYLINE_WIDTH_PT


CATEGORICAL_BAR_TARGET_MEAN_FRACTION = 0.65


CATEGORICAL_BAR_MAX_ERROR_FRACTION = 0.78


IMPACT_POINT_LINE_CONDITION_OFFSET_FRACTION = 0.05


IMPACT_POINT_LINE_RAW_MARKER_SCALE = 0.875


IMPACT_POINT_LINE_RAW_MARKER_ALPHA = 0.50


IMPACT_POINT_LINE_MEAN_MARKER_EDGE_COLOR = "#FFFFFF"


IMPACT_POINT_LINE_MEAN_MARKER_EDGE_WIDTH_PT = 0.70


CATEGORICAL_STACK_TARGET_TOTAL_FRACTION = 0.88


CATEGORICAL_STACK_MAX_COMPONENTS = 5


CATEGORICAL_STACK_MAX_LIGHTEN_FRACTION = 0.35


CATEGORICAL_COMPONENT_LEGEND_SWATCH_LEFT_FRACTION = 0.73


CATEGORICAL_COMPONENT_LEGEND_SWATCH_WIDTH_FRACTION = 0.12


CATEGORICAL_COMPONENT_LEGEND_SWATCH_HEIGHT_FRACTION = 0.05


CATEGORICAL_COMPONENT_LEGEND_TOP_FRACTION = 0.92


CATEGORICAL_COMPONENT_LEGEND_ROW_GAP_FRACTION = 0.08


CATEGORICAL_COMPONENT_LEGEND_LABEL_X_FRACTION = 0.875


FACTOR_CURVE_LEGEND_TITLE_X_FRACTION = 0.28


FACTOR_CURVE_LEGEND_TITLE_Y_FRACTION = 0.27


FACTOR_CURVE_LEGEND_ENTRY_Y_FRACTIONS = (0.18, 0.18)


FACTOR_CURVE_LEGEND_CONDITION_SWATCH_X = (
    (0.28, 0.40),
    (0.754, 0.874),
)


FACTOR_CURVE_LEGEND_CONDITION_SWATCH_HEIGHT_FRACTION = 0.035


FACTOR_CURVE_LEGEND_CONDITION_LABEL_X_FRACTIONS = (0.415, 0.991)


FACTOR_CURVE_LEGEND_CONDITION_LABEL_ALIGNS = ("left", "right")


FACTOR_CURVE_LEGEND_FORMULA_ENTRY_Y_FRACTION = 0.08


FACTOR_CURVE_LEGEND_FORMULA_COLUMN_X_FRACTIONS = (0.28, 0.46, 0.64, 0.82)


FACTOR_CURVE_LEGEND_FORMULA_SWATCH_LENGTH_FRACTION = UNIFIED_LEGEND_KEY_LENGTH_MM / (
    60.0 - UNIFIED_LEFT_MARGIN_MM - UNIFIED_RIGHT_MARGIN_MM
)


FACTOR_CURVE_LEGEND_FORMULA_LABEL_GAP_FRACTION = 0.012


CATEGORICAL_ERROR_CAP_TO_BAR_RATIO = 0.50


MECHANICAL_STRAIN_AXIS_LABEL = "Strain (%)"


TENSILE_X_AXIS_LABEL = MECHANICAL_STRAIN_AXIS_LABEL


TENSILE_Y_AXIS_LABEL = "Tensile stress (MPa)"


COMPRESSION_X_AXIS_LABEL = MECHANICAL_STRAIN_AXIS_LABEL


COMPRESSION_Y_AXIS_LABEL = "Compressive stress (MPa)"


FLEXURAL_X_AXIS_LABEL = MECHANICAL_STRAIN_AXIS_LABEL


FLEXURAL_Y_AXIS_LABEL = "Flexural stress (MPa)"


MECHANICAL_AXIS_LABELS = {
    "tensile_curve": (TENSILE_X_AXIS_LABEL, TENSILE_Y_AXIS_LABEL),
    "compression_curve": (COMPRESSION_X_AXIS_LABEL, COMPRESSION_Y_AXIS_LABEL),
    "flexural_curve": (FLEXURAL_X_AXIS_LABEL, FLEXURAL_Y_AXIS_LABEL),
}


TENSILE_AXIS_PADDING_FRACTION = 0.06


def mechanical_axis_labels(rule_id: object) -> tuple[str, str] | None:
    """Return the normative strain/stress labels for a mechanical test."""

    return MECHANICAL_AXIS_LABELS.get(str(rule_id or "").strip())


def categorical_slot_width_mm(*, category_count: int, figure_width_mm: float) -> float:
    """Return the physical width allocated to one categorical sample."""

    count = max(int(category_count), 1)
    graph_width_mm = max(
        float(figure_width_mm) - UNIFIED_LEFT_MARGIN_MM - UNIFIED_RIGHT_MARGIN_MM,
        1.0,
    )
    return graph_width_mm / float(count)


def categorical_box_width_mm(*, category_count: int, figure_width_mm: float) -> float:
    """Return a box width one third wider than the shared categorical bar.

    Category count determines the physical slot width. Replicate count is
    intentionally excluded because ordinary equal-width boxplots do not encode
    sample size through box width.
    """

    return (
        categorical_slot_width_mm(
            category_count=category_count,
            figure_width_mm=figure_width_mm,
        )
        * CATEGORICAL_BOX_FILL_FRACTION
    )


def categorical_box_native_fill_scale(*, category_count: int) -> float:
    """Convert a slot-relative target into Veusz boxplot fillfraction units."""

    return 2.0 / float(max(int(category_count), 1))


def categorical_raw_point_half_spread(
    *,
    box_fill_fraction: float,
    replicate_count: int,
    category_slot_width_mm: float | None = None,
    marker_size_pt: float = UNIFIED_MARKER_SIZE_PT,
) -> float:
    """Return half of a replicate-aware point band contained by the box.

    The full marker band grows logarithmically from the box centre as
    replicates increase and is capped at 90% of the box width. When physical
    slot width is known, the cap also reserves one full Veusz marker diameter
    so the complete marker glyphs stay inside the visible box edges.
    """

    count = max(int(replicate_count), 0)
    if count <= 1:
        return 0.0
    box_ratio = min(
        CATEGORICAL_POINT_BAND_BASE_BOX_RATIO
        + CATEGORICAL_POINT_BAND_LOG2_STEP * math.log2(float(count)),
        CATEGORICAL_POINT_BAND_MAX_BOX_RATIO,
    )
    half_spread = min(
        0.5 * max(float(box_fill_fraction), 0.0) * box_ratio,
        MAX_RAW_POINT_JITTER_FRACTION,
    )
    if category_slot_width_mm is None or float(category_slot_width_mm) <= 0.0:
        return half_spread
    slot_width_mm = float(category_slot_width_mm)
    marker_diameter_mm = 2.0 * max(float(marker_size_pt), 0.0) * 25.4 / 72.0
    glyph_safe_band_mm = max(
        max(float(box_fill_fraction), 0.0) * slot_width_mm - marker_diameter_mm,
        0.0,
    )
    return min(half_spread, glyph_safe_band_mm / (2.0 * slot_width_mm))


def categorical_fill_color(value: object) -> str:
    """Return the opaque light-role colour for one categorical palette root."""

    text = str(value or "").strip()
    normalized = text.upper()
    mapped = CATEGORICAL_FILL_COLORS_BY_BASE.get(normalized)
    if mapped is not None:
        return mapped
    match = re.fullmatch(r"#([0-9A-F]{6})", normalized)
    if match is None:
        return text
    packed = match.group(1)
    channels = [int(packed[index : index + 2], 16) for index in (0, 2, 4)]
    lightened = [round(channel * 0.45 + 255.0 * 0.55) for channel in channels]
    return "#{:02X}{:02X}{:02X}".format(*lightened)


def categorical_keyline_color(value: object) -> str:
    """Return the mid-tone edge role for one categorical palette root."""

    text = str(value or "").strip()
    normalized = text.upper()
    mapped = CATEGORICAL_KEYLINE_COLORS_BY_BASE.get(normalized)
    if mapped is not None:
        return mapped
    match = re.fullmatch(r"#([0-9A-F]{6})", normalized)
    if match is None:
        return text
    packed = match.group(1)
    channels = [int(packed[index : index + 2], 16) for index in (0, 2, 4)]
    softened = [round(channel * 0.65 + 255.0 * 0.35) for channel in channels]
    return "#{:02X}{:02X}{:02X}".format(*softened)


def categorical_component_fill_color(
    value: object,
    *,
    component_index: int,
    component_count: int,
) -> str:
    """Return an opaque same-hue tone for one ordered stacked component.

    Samples retain their categorical root colour. Components within each
    sample progress only in lightness, from the root colour at the bottom to a
    moderately lighter solid colour at the top. The maximum white blend is
    deliberately capped so adjacent components remain related rather than
    reading as unrelated categories.
    """

    text = str(value or "").strip()
    normalized = text.upper()
    match = re.fullmatch(r"#([0-9A-F]{6})", normalized)
    if match is None:
        return text
    count = max(int(component_count), 1)
    index = min(max(int(component_index), 0), count - 1)
    fraction = (
        0.0
        if count == 1
        else CATEGORICAL_STACK_MAX_LIGHTEN_FRACTION * index / float(count - 1)
    )
    packed = match.group(1)
    channels = [int(packed[offset : offset + 2], 16) for offset in (0, 2, 4)]
    lightened = [
        round(channel * (1.0 - fraction) + 255.0 * fraction) for channel in channels
    ]
    return "#{:02X}{:02X}{:02X}".format(*lightened)
