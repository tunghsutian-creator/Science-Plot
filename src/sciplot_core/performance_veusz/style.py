"""Convert performance dimensions, text, axes, and base style into Veusz values."""

from __future__ import annotations

import math
import re
from typing import Any
from sciplot_core.materials_rules import format_plot_text_units
from sciplot_core.policy import (
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_FONT_FAMILY,
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LEGEND_FONT_SIZE_PT,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MINOR_TICK_LENGTH_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_TICK_LENGTH_PT,
    UNIFIED_TICK_WIDTH_PT,
)


_RADAR_AXIS_LIMIT = 1.12


_RADAR_LABEL_HORIZONTAL_RADIUS_LEFT = 0.78


_RADAR_LABEL_HORIZONTAL_RADIUS_RIGHT = 1.06


_RADAR_LABEL_VERTICAL_RADIUS = 1.15


_RADAR_ENDPOINT_LABEL_RADIUS = 1.06


_RADAR_RING_LEVELS = (0.25, 0.50, 0.75, 1.00)


_RADAR_FIVE_AXIS_ANGLES = (90.0, 162.0, 234.0, 306.0, 18.0)


_RADAR_FIVE_AXIS_TITLE_X_MM = (28.75, 9.0, 13.8, 46.2, 51.9)


_RADAR_FIVE_AXIS_TITLE_CENTRE_Y_MM = (2.9, 13.4, 48.4, 48.4, 13.4)


_RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM = 2.6


_RADAR_FIVE_AXIS_ENDPOINT_OFFSETS_MM = (1.7, 2.0, 2.7, 2.7, 2.7)


_LEGEND_PAIRED_SLOT_OFFSET_MM = 22.0


def _pt(value: float) -> str:
    return f"{float(value):g}pt"


def _cm_from_mm(value: float) -> str:
    return f"{float(value) / 10.0:g}cm"


def _literal_text(value: object) -> str:
    text = format_plot_text_units(value).replace("\\", "\ue000")
    text = re.sub(r"([_\^\[\]\{\}])", r"\\\1", text)
    return text.replace("\ue000", "{\\backslash}")


def _style_payload(margins: dict[str, Any]) -> dict[str, Any]:
    return {
        "font_family": UNIFIED_FONT_FAMILY,
        "font_size_pt": UNIFIED_FONT_SIZE_PT,
        "legend_font_size_pt": UNIFIED_LEGEND_FONT_SIZE_PT,
        "axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "tick_width_pt": UNIFIED_TICK_WIDTH_PT,
        "tick_length_pt": UNIFIED_TICK_LENGTH_PT,
        "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
        "minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
        "line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "line_alpha": 0.92,
        "marker_alpha": 0.95,
        "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
        "marker_line_width_pt": UNIFIED_MARKER_LINE_WIDTH_PT,
        "axes_labelpad_pt": 2.0,
        "xtick_major_pad_pt": 1.4,
        "ytick_major_pad_pt": 1.4,
        "legend_frameon": False,
        "margins_mm": {
            side: float(margins[side]) for side in ("left", "right", "bottom", "top")
        },
    }


def _axis_payload(
    *,
    label: str,
    minimum: float,
    maximum: float,
    hidden: bool,
) -> dict[str, Any]:
    return {
        "label": label,
        "scale": "linear",
        "tick_format": "Auto",
        "minor_tick_count": 20,
        "minor_ticks": [],
        "min": float(minimum),
        "max": float(maximum),
        "ticks": [],
        "reverse": False,
        "foreground_color": UNIFIED_FOREGROUND_COLOR,
        "label_size_pt": UNIFIED_FONT_SIZE_PT,
        "tick_label_size_pt": UNIFIED_FONT_SIZE_PT,
        "line_width_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "major_tick_width_pt": UNIFIED_TICK_WIDTH_PT,
        "major_tick_length_pt": UNIFIED_TICK_LENGTH_PT,
        "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
        "minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
        "mode": "numeric",
        "show_ticks": not hidden,
        "hidden": hidden,
    }


def _expanded_axis_bounds(
    payload: dict[str, Any],
    request: dict[str, Any],
    *,
    axis: str,
) -> tuple[float, float]:
    bounds = payload[f"{axis}_bounds"]
    minimum = float(bounds[0])
    maximum = float(bounds[1])
    if payload["layout"]["legend_uses_reserved_panel"]:
        return minimum, maximum
    options = _performance_render_options(payload, request)
    requested_minimum = options.get(f"{axis}_min")
    requested_maximum = options.get(f"{axis}_max")
    if isinstance(requested_minimum, int | float) and math.isfinite(
        float(requested_minimum)
    ):
        minimum = min(minimum, float(requested_minimum))
    if isinstance(requested_maximum, int | float) and math.isfinite(
        float(requested_maximum)
    ):
        maximum = max(maximum, float(requested_maximum))
    return minimum, maximum


def _performance_render_options(
    payload: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    options = (
        dict(request.get("render_options"))
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    resolved = payload.get("inside_legend_render_options")
    if isinstance(resolved, dict):
        options.update(resolved)
    return options


def _inside_legend_contract(
    payload: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    use_reserved_panel = bool(payload["layout"]["legend_uses_reserved_panel"])
    if use_reserved_panel:
        return {
            "show": False,
            "mode": "reserved_reference_panel",
            "outside_legend": False,
            "reference_panel_used": True,
        }
    options = _performance_render_options(payload, request)
    return {
        "show": True,
        "mode": str(options.get("legend_position") or "inside_best"),
        "columns": 1,
        "presentation_kind": "performance_group_summary",
        "outside_legend": False,
        "reference_panel_used": False,
        "horz_position": options.get("legend_horz_position"),
        "vert_position": options.get("legend_vert_position"),
        "horz_manual": options.get("legend_horz_manual"),
        "vert_manual": options.get("legend_vert_manual"),
        "placement_diagnostics": options.get("_legend_placement_diagnostics"),
    }
