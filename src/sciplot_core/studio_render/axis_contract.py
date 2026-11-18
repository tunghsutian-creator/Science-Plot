"""Build the final Veusz axis contract from request and series evidence."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    AUTO_LOG_BOUND_PADDING_FACTOR,
    MAX_AUTO_LOG_EMPTY_RANGE_FACTOR,
    anchored_log_decade_ticks,
)

from sciplot_core.studio_render.models import (
    STACKED_TEMPLATE_IDS,
    StudioSeries,
    _VeuszAxisContract,
)

from sciplot_core.studio_render.axis_scale import (
    _axis_scale,
    _trim_empty_terminal_log_decades,
)
from sciplot_core.studio_render.axis_limits import compute_axis_limits

from sciplot_core.studio_render.legend_visibility import (
    _veusz_legend_mode,
)

from sciplot_core.studio_render.value_parsing import (
    _optional_float,
    _float_tuple,
)


def _veusz_axis_contract(
    render_options: dict[str, Any],
    *,
    template_id: str,
    series: list[StudioSeries],
    explicit_render_options: dict[str, Any] | None = None,
) -> _VeuszAxisContract:
    compact_auto_log_bounds = explicit_render_options is not None
    explicit_keys = (
        set(render_options)
        if explicit_render_options is None
        else set(explicit_render_options)
    )
    explicit_x_min = "x_min" in explicit_keys
    explicit_x_max = "x_max" in explicit_keys
    explicit_y_min = "y_min" in explicit_keys
    explicit_y_max = "y_max" in explicit_keys
    x_min = _optional_float(render_options.get("x_min"))
    x_max = _optional_float(render_options.get("x_max"))
    y_min = _optional_float(render_options.get("y_min"))
    y_max = _optional_float(render_options.get("y_max"))
    x_ticks = _float_tuple(render_options.get("x_ticks"))
    y_ticks = _float_tuple(render_options.get("y_ticks"))
    explicit_x_ticks = bool(x_ticks) and "x_ticks" in explicit_keys
    explicit_y_ticks = bool(y_ticks) and "y_ticks" in explicit_keys
    placement_diagnostics = render_options.get("_legend_placement_diagnostics")
    legend_axis_reserve = (
        placement_diagnostics.get("axis_reserve")
        if isinstance(placement_diagnostics, dict)
        else None
    )
    legend_reserves_y_min = (
        isinstance(legend_axis_reserve, dict)
        and legend_axis_reserve.get("side") == "bottom"
    )
    legend_reserves_y_max = (
        isinstance(legend_axis_reserve, dict)
        and legend_axis_reserve.get("side") == "top"
    )

    if series:
        try:
            limits = compute_axis_limits(
                [item.y_values for item in series],
                kind="line",
                axis_mode=str(render_options.get("axis_mode") or "auto"),
                legend_mode=_veusz_legend_mode(render_options, template_id=template_id),
                x_values=[item.x_values for item in series],
                xscale=_axis_scale(render_options, "x"),
                yscale=_axis_scale(render_options, "y"),
                x_padding=_optional_float(render_options.get("x_padding_fraction"))
                or 0.02,
                y_padding_top=_optional_float(render_options.get("y_padding_top"))
                or (0.08 if template_id in STACKED_TEMPLATE_IDS else 0.18),
                y_padding_bottom=_optional_float(render_options.get("y_padding_bottom"))
                or (0.04 if template_id in STACKED_TEMPLATE_IDS else 0.06),
            )
            if x_min is None:
                x_min = float(limits.xlim[0])
            if x_max is None:
                x_max = float(limits.xlim[1])
            if y_min is None:
                y_min = float(limits.ylim[0])
            if y_max is None:
                y_max = float(limits.ylim[1])
            if not x_ticks and limits.x_tick_policy is not None:
                x_ticks = tuple(
                    float(value) for value in limits.x_tick_policy.major_ticks
                )
            if not y_ticks and limits.y_tick_policy is not None:
                y_ticks = tuple(
                    float(value) for value in limits.y_tick_policy.major_ticks
                )
        except Exception:
            pass

    if series and _axis_scale(render_options, "x") == "log" and not explicit_x_ticks:
        positive_x_values = [
            value
            for item in series
            for value in item.x_values
            if math.isfinite(value) and value > 0
        ]
        x_ticks = anchored_log_decade_ticks(positive_x_values)
        if x_ticks and compact_auto_log_bounds:
            data_min = min(positive_x_values)
            data_max = max(positive_x_values)
            if not explicit_x_min:
                compact_min = min(x_ticks[0], data_min / AUTO_LOG_BOUND_PADDING_FACTOR)
                x_min = float(x_min) if x_min is not None else compact_min
                if x_min < compact_min / MAX_AUTO_LOG_EMPTY_RANGE_FACTOR:
                    x_min = compact_min
            if not explicit_x_max:
                x_ticks, compact_max = _trim_empty_terminal_log_decades(
                    x_ticks,
                    data_max=data_max,
                )
                if compact_max is not None:
                    x_max = compact_max
                else:
                    compact_max = max(
                        x_ticks[-1], data_max * AUTO_LOG_BOUND_PADDING_FACTOR
                    )
                    x_max = float(x_max) if x_max is not None else compact_max
                    if x_max > compact_max * MAX_AUTO_LOG_EMPTY_RANGE_FACTOR:
                        x_max = compact_max
    if series and _axis_scale(render_options, "y") == "log" and not explicit_y_ticks:
        positive_y_values = [
            value
            for item in series
            for value in item.y_values
            if math.isfinite(value) and value > 0
        ]
        y_ticks = anchored_log_decade_ticks(positive_y_values)
        if y_ticks and compact_auto_log_bounds:
            data_min = min(positive_y_values)
            data_max = max(positive_y_values)
            if not explicit_y_min and not legend_reserves_y_min:
                compact_min = min(y_ticks[0], data_min / AUTO_LOG_BOUND_PADDING_FACTOR)
                y_min = float(y_min) if y_min is not None else compact_min
                if y_min < compact_min / MAX_AUTO_LOG_EMPTY_RANGE_FACTOR:
                    y_min = compact_min
            if not explicit_y_max and not legend_reserves_y_max:
                y_ticks, compact_max = _trim_empty_terminal_log_decades(
                    y_ticks,
                    data_max=data_max,
                )
                if compact_max is not None:
                    y_max = compact_max
                else:
                    compact_max = max(
                        y_ticks[-1], data_max * AUTO_LOG_BOUND_PADDING_FACTOR
                    )
                    y_max = float(y_max) if y_max is not None else compact_max
                    if y_max > compact_max * MAX_AUTO_LOG_EMPTY_RANGE_FACTOR:
                        y_max = compact_max
    if x_ticks:
        if not explicit_x_min:
            x_min = (
                min(float(x_min), min(x_ticks)) if x_min is not None else min(x_ticks)
            )
        if not explicit_x_max:
            x_max = (
                max(float(x_max), max(x_ticks)) if x_max is not None else max(x_ticks)
            )
    if y_ticks:
        if not explicit_y_min:
            y_min = (
                min(float(y_min), min(y_ticks)) if y_min is not None else min(y_ticks)
            )
        if not explicit_y_max:
            y_max = (
                max(float(y_max), max(y_ticks)) if y_max is not None else max(y_ticks)
            )

    reverse_x = render_options.get("reverse_x") is True
    if reverse_x and x_min is not None and x_max is not None:
        x_min, x_max = x_max, x_min
    if x_ticks and x_min is not None and x_max is not None:
        low = min(x_min, x_max)
        high = max(x_min, x_max)
        deduped: list[float] = []
        for value in x_ticks:
            if value < low - 1e-9 or value > high + 1e-9:
                continue
            if not any(math.isclose(value, existing) for existing in deduped):
                deduped.append(value)
        x_ticks = tuple(sorted(deduped, reverse=x_min > x_max))
    if y_ticks and y_min is not None and y_max is not None:
        low = min(y_min, y_max)
        high = max(y_min, y_max)
        y_ticks = tuple(
            value
            for value in sorted(set(y_ticks))
            if low - 1e-9 <= value <= high + 1e-9
        )
    return _VeuszAxisContract(
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
    )
