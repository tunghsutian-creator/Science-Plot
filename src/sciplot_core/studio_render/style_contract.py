"""Build and validate the immutable Veusz style contract."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_FONT_FAMILY,
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_LEGEND_FONT_SIZE_PT,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MINOR_TICK_LENGTH_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_TICK_LENGTH_PT,
    UNIFIED_TICK_WIDTH_PT,
)
from sciplot_core.studio_render.models import (
    _VeuszStyleContract,
)


def _veusz_style_contract(render_options: dict[str, Any]) -> _VeuszStyleContract:
    requested_dimensions = {
        key: render_options.get(key)
        for key in (
            "font_size_pt",
            "legend_font_size_pt",
            "axis_linewidth_pt",
            "tick_width_pt",
            "tick_length_pt",
            "minor_tick_width_pt",
            "minor_tick_length_pt",
            "line_width_pt",
            "marker_line_width_pt",
        )
    }
    requested_dimensions["marker_size_pt"] = (
        render_options.get("marker_size_pt")
        if render_options.get("marker_size_pt") is not None
        else render_options.get("marker_size")
    )
    invalid_requested_dimensions: list[str] = []
    for name, value in requested_dimensions.items():
        if value is None:
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            invalid_requested_dimensions.append(name)
            continue
        if not math.isfinite(numeric_value) or numeric_value <= 0.0:
            invalid_requested_dimensions.append(name)
    if invalid_requested_dimensions:
        raise ValueError(
            "Veusz typography and stroke requests must be finite and positive: "
            f"{invalid_requested_dimensions}."
        )

    style_id = str(render_options.get("style_preset") or "nature")
    try:
        from sciplot_core.contract import load_plot_contract, normalize_style_alias

        contract = load_plot_contract()
        style = contract.styles.get(normalize_style_alias(style_id))
        if style is None:
            base = _VeuszStyleContract()
        else:
            base = _VeuszStyleContract(
                # Typography and physical strokes are deliberately not read from
                # template/style overrides.  They are the project-wide hard
                # contract; style presets remain only for semantic/layout
                # compatibility and palette/theme selection.
                font_family=UNIFIED_FONT_FAMILY,
                font_size_pt=UNIFIED_FONT_SIZE_PT,
                legend_font_size_pt=UNIFIED_LEGEND_FONT_SIZE_PT,
                axis_linewidth_pt=UNIFIED_AXIS_LINEWIDTH_PT,
                tick_width_pt=UNIFIED_TICK_WIDTH_PT,
                tick_length_pt=UNIFIED_TICK_LENGTH_PT,
                minor_tick_width_pt=UNIFIED_MINOR_TICK_WIDTH_PT,
                minor_tick_length_pt=UNIFIED_MINOR_TICK_LENGTH_PT,
                line_width_pt=UNIFIED_LINE_WIDTH_PT,
                line_alpha=float(style.stroke.line_alpha),
                marker_alpha=float(style.stroke.marker_alpha),
                marker_size_pt=UNIFIED_MARKER_SIZE_PT,
                marker_line_width_pt=UNIFIED_MARKER_LINE_WIDTH_PT,
                axes_labelpad_pt=float(style.spacing.axes_labelpad),
                xtick_major_pad_pt=float(style.spacing.xtick_major_pad),
                ytick_major_pad_pt=float(style.spacing.ytick_major_pad),
                legend_inset_fraction=float(style.spacing.legend_inset_fraction),
                legend_frameon=bool(style.annotation.legend_frameon),
                left_margin_mm=float(contract.global_frame.left_margin_mm),
                right_margin_mm=float(contract.global_frame.right_margin_mm),
                bottom_margin_mm=float(contract.global_frame.bottom_margin_mm),
                top_margin_mm=float(contract.global_frame.top_margin_mm),
            )
    except Exception:
        base = _VeuszStyleContract()
    required_visible_dimensions = {
        "font_size_pt": base.font_size_pt,
        "axis_linewidth_pt": base.axis_linewidth_pt,
        "tick_width_pt": base.tick_width_pt,
        "tick_length_pt": base.tick_length_pt,
        "minor_tick_width_pt": base.minor_tick_width_pt,
        "minor_tick_length_pt": base.minor_tick_length_pt,
    }
    invalid = [
        name
        for name, value in required_visible_dimensions.items()
        if not math.isfinite(float(value)) or float(value) <= 0.0
    ]
    if invalid:
        raise ValueError(
            "Veusz axis and colorbar visibility dimensions must be finite and "
            f"positive: {invalid}."
        )
    # Explicit request-level typography/stroke values are intentionally
    # ignored.  Veusz editing remains available after generation, but every
    # generated template starts from the same SciPlot hard standard.
    return base
