"""Expand axis bounds to preserve the physical extent of visible marks."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    CATEGORICAL_BAR_WIDTH_FRACTION,
    CATEGORICAL_BOX_FILL_FRACTION,
    CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
    MIN_VISUAL_EXTENT_CLEARANCE_MM,
)

from sciplot_core.studio_render.models import (
    CATEGORICAL_SERIES_KINDS,
    StudioSeries,
    _VeuszStyleContract,
    _VeuszAxisContract,
)

from sciplot_core.studio_render.domain_defaults import (
    _explicit_render_options,
)

from sciplot_core.studio_render.axis_scale import (
    _axis_scale,
)


def _expand_axis_for_visual_extents(
    axis_contract: _VeuszAxisContract,
    *,
    request: dict[str, Any],
    render_options: dict[str, Any],
    template_id: str,
    series: list[StudioSeries],
    categorical_contract: dict[str, Any] | None,
    style: _VeuszStyleContract,
    width_mm: float,
    height_mm: float,
) -> tuple[_VeuszAxisContract, dict[str, Any]]:
    """Reserve data-space bounds for point-sized plot glyphs before clipping."""

    point_to_mm = 25.4 / 72.0
    stroke_extent_mm = (
        max(style.line_width_pt, style.marker_line_width_pt) * 0.5 * point_to_mm
        + MIN_VISUAL_EXTENT_CLEARANCE_MM
    )
    marker_extent_mm = (
        style.marker_size_pt + style.marker_line_width_pt * 0.5
    ) * point_to_mm + MIN_VISUAL_EXTENT_CLEARANCE_MM
    x_values: list[float] = []
    y_values: list[float] = []
    x_extent_mm = stroke_extent_mm
    y_extent_mm = stroke_extent_mm
    categorical_kind = (
        str(categorical_contract.get("presentation_kind") or "")
        if isinstance(categorical_contract, dict)
        else ""
    )

    for item in series:
        finite_x = [float(value) for value in item.x_values if math.isfinite(value)]
        finite_y = [float(value) for value in item.y_values if math.isfinite(value)]
        x_values.extend(finite_x)
        y_values.extend(finite_y)
        marker = str(item.marker or "none").strip().casefold()
        if item.presentation_kind not in CATEGORICAL_SERIES_KINDS and marker != "none":
            item_marker_size = float(item.marker_size or style.marker_size_pt)
            item_extent_mm = (
                item_marker_size + style.marker_line_width_pt * 0.5
            ) * point_to_mm + MIN_VISUAL_EXTENT_CLEARANCE_MM
            x_extent_mm = max(x_extent_mm, item_extent_mm)
            y_extent_mm = max(y_extent_mm, item_extent_mm)

    if isinstance(categorical_contract, dict):
        visual_style = (
            categorical_contract.get("visual_style")
            if isinstance(categorical_contract.get("visual_style"), dict)
            else {}
        )
        groups = [
            group
            for group in categorical_contract.get("groups", [])
            if isinstance(group, dict)
        ]
        if categorical_kind == "point_line_raw_overlay":
            reference_width = float(
                visual_style.get(
                    "error_cap_reference_width_fraction",
                    CATEGORICAL_BAR_WIDTH_FRACTION,
                )
            )
            cap_ratio = float(
                visual_style.get(
                    "error_cap_to_bar_ratio",
                    CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
                )
            )
            error_width_pt = float(
                visual_style.get("error_line_width_pt", style.line_width_pt)
            )
            error_extent_mm = (
                error_width_pt * 0.5 * point_to_mm + MIN_VISUAL_EXTENT_CLEARANCE_MM
            )
            x_extent_mm = max(x_extent_mm, error_extent_mm)
            y_extent_mm = max(y_extent_mm, error_extent_mm)
            cap_half_width = reference_width * cap_ratio * 0.5
            for error_bar in categorical_contract.get("error_bars", []):
                if not isinstance(error_bar, dict):
                    continue
                position = float(error_bar["position"])
                x_values.extend((position - cap_half_width, position + cap_half_width))
                y_values.extend((float(error_bar["low"]), float(error_bar["high"])))
        elif categorical_kind in {"bar_error", "grouped_bar_error"}:
            bar_width = float(
                visual_style.get("bar_width_fraction", CATEGORICAL_BAR_WIDTH_FRACTION)
            )
            cap_ratio = float(
                visual_style.get(
                    "error_cap_to_bar_ratio", CATEGORICAL_ERROR_CAP_TO_BAR_RATIO
                )
            )
            error_width_pt = float(
                visual_style.get("error_line_width_pt", style.line_width_pt)
            )
            error_extent_mm = (
                error_width_pt * 0.5 * point_to_mm + MIN_VISUAL_EXTENT_CLEARANCE_MM
            )
            x_extent_mm = max(x_extent_mm, error_extent_mm)
            y_extent_mm = max(y_extent_mm, error_extent_mm)
            for group in groups:
                position = float(group["position"])
                half_width = max(bar_width * 0.5, bar_width * cap_ratio * 0.5)
                x_values.extend((position - half_width, position + half_width))
                mean = float(group["bar_mean"])
                error = float(group["bar_error"])
                y_values.extend((mean - error, mean + error))
        elif categorical_kind == "stacked_components":
            bar_width = float(
                visual_style.get(
                    "bar_width_fraction",
                    CATEGORICAL_BAR_WIDTH_FRACTION,
                )
            )
            for group in groups:
                position = float(group["position"])
                x_values.extend(
                    (
                        position - bar_width * 0.5,
                        position + bar_width * 0.5,
                    )
                )
                # The shared categorical baseline is the visible y=0 axis.
                # As with ordinary summary bars, reserve stroke clearance at
                # the data-bearing top edge without moving the honest zero
                # baseline below zero merely to clear the endpoint cap.
                y_values.append(float(group["stack_total"]))
        elif categorical_kind in {"box", "box_strip"}:
            box_width = float(
                visual_style.get("box_fill_fraction", CATEGORICAL_BOX_FILL_FRACTION)
            )
            for group in groups:
                position = float(group["position"])
                x_values.extend(
                    (position - box_width * 0.5, position + box_width * 0.5)
                )
            if categorical_kind == "box_strip":
                x_extent_mm = max(x_extent_mm, marker_extent_mm)
                y_extent_mm = max(y_extent_mm, marker_extent_mm)

    explicit = _explicit_render_options(request)
    diagnostics: dict[str, Any] = {
        "kind": "sciplot_physical_visual_extent_axis_clearance",
        "version": 1,
        "minimum_extra_clearance_mm": MIN_VISUAL_EXTENT_CLEARANCE_MM,
        "expanded_axes": [],
        "violations": [],
        "axes": {},
    }

    def expand_axis(
        axis: str,
        minimum: float | None,
        maximum: float | None,
        values: list[float],
        required_extent_mm: float,
        graph_size_mm: float,
    ) -> tuple[float | None, float | None]:
        if minimum is None or maximum is None or not values or graph_size_mm <= 0.0:
            return minimum, maximum
        reverse = minimum > maximum
        low, high = sorted((float(minimum), float(maximum)))
        scale = _axis_scale(render_options, axis)
        finite_values = [value for value in values if math.isfinite(value)]
        if scale == "log":
            finite_values = [value for value in finite_values if value > 0.0]
            if low <= 0.0 or not finite_values:
                return minimum, maximum
            transform = math.log10

            def inverse(value: float) -> float:
                return 10.0**value
        else:
            if not finite_values:
                return minimum, maximum
            transform = float
            inverse = float
        anchor_low = min(transform(value) for value in finite_values)
        anchor_high = max(transform(value) for value in finite_values)
        transformed_low = transform(low)
        transformed_high = transform(high)
        original = (low, high)
        fraction = min(max(required_extent_mm / graph_size_mm, 0.0), 0.20)
        lower_explicit = f"{axis}_min" in explicit
        upper_explicit = f"{axis}_max" in explicit
        for _ in range(4):
            span = transformed_high - transformed_low
            if span <= 0.0:
                break
            if not lower_explicit and anchor_low - transformed_low < fraction * span:
                transformed_low = min(
                    transformed_low,
                    (anchor_low - fraction * transformed_high) / (1.0 - fraction),
                )
            span = transformed_high - transformed_low
            if not upper_explicit and transformed_high - anchor_high < fraction * span:
                transformed_high = max(
                    transformed_high,
                    (anchor_high - fraction * transformed_low) / (1.0 - fraction),
                )
        low = inverse(transformed_low)
        high = inverse(transformed_high)
        span = transformed_high - transformed_low
        lower_clearance_mm = (
            (anchor_low - transformed_low) / span * graph_size_mm if span > 0.0 else 0.0
        )
        upper_clearance_mm = (
            (transformed_high - anchor_high) / span * graph_size_mm
            if span > 0.0
            else 0.0
        )
        expanded = not (
            math.isclose(low, original[0], rel_tol=1e-12, abs_tol=1e-12)
            and math.isclose(high, original[1], rel_tol=1e-12, abs_tol=1e-12)
        )
        if expanded:
            diagnostics["expanded_axes"].append(axis)
        diagnostics["axes"][axis] = {
            "scale": scale,
            "original_bounds": list(original),
            "final_bounds": [low, high],
            "visual_anchor_bounds": [min(finite_values), max(finite_values)],
            "required_extent_mm": required_extent_mm,
            "lower_clearance_mm": lower_clearance_mm,
            "upper_clearance_mm": upper_clearance_mm,
            "lower_bound_explicit": lower_explicit,
            "upper_bound_explicit": upper_explicit,
            "status": "safe",
        }
        tolerance = 1e-6
        for side, clearance, is_explicit in (
            ("lower", lower_clearance_mm, lower_explicit),
            ("upper", upper_clearance_mm, upper_explicit),
        ):
            if clearance + tolerance >= required_extent_mm:
                continue
            diagnostics["axes"][axis]["status"] = "unsafe_explicit_bound"
            diagnostics["violations"].append(
                {
                    "axis": axis,
                    "side": side,
                    "bound_explicit": is_explicit,
                    "required_extent_mm": required_extent_mm,
                    "measured_clearance_mm": clearance,
                }
            )
        return (high, low) if reverse else (low, high)

    graph_width_mm = max(width_mm - style.left_margin_mm - style.right_margin_mm, 1.0)
    graph_height_mm = max(height_mm - style.bottom_margin_mm - style.top_margin_mm, 1.0)
    x_min, x_max = expand_axis(
        "x",
        axis_contract.x_min,
        axis_contract.x_max,
        x_values,
        x_extent_mm,
        graph_width_mm,
    )
    y_min, y_max = expand_axis(
        "y",
        axis_contract.y_min,
        axis_contract.y_max,
        y_values,
        y_extent_mm,
        graph_height_mm,
    )
    return (
        _VeuszAxisContract(
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            x_ticks=axis_contract.x_ticks,
            y_ticks=axis_contract.y_ticks,
        ),
        diagnostics,
    )
