"""Build reference-guide, axis, direct-label, and categorical-label contracts."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    DEFAULT_LINE_STYLE_SEQUENCE,
    DEFAULT_LOG_MINOR_TICK_COUNT,
    DEFAULT_LOG_TICK_FORMAT,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LINE_WIDTH_PT,
)

from sciplot_core.studio_render.models import (
    StudioSeries,
    _VeuszStyleContract,
    _VeuszAxisContract,
)

from sciplot_core.studio_render.axis_scale import (
    _axis_scale,
)

from sciplot_core.studio_render.legend_visibility import (
    _series_label_anchor,
)

from sciplot_core.studio_render.value_parsing import (
    _optional_float,
    _float_tuple,
    _log_minor_ticks,
)


def _reference_guides_contract(render_options: dict[str, Any]) -> list[dict[str, Any]]:
    value = render_options.get("reference_guides")
    if value is None:
        return []
    if not isinstance(value, list | tuple):
        raise ValueError("reference_guides must be a list of guide objects.")
    guides: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Reference guide {index} must be an object.")
        kind = str(item.get("kind") or "band").strip().casefold()
        axis = (
            str(item.get("axis_target") or item.get("axis") or "x").strip().casefold()
        )
        if kind not in {"band", "line"} or axis not in {"x", "y"}:
            raise ValueError(
                f"Reference guide {index} must be a band or line on x or y."
            )
        start = _optional_float(item.get("start"))
        end = _optional_float(item.get("end"))
        value_number = _optional_float(item.get("value"))
        if kind == "line":
            if value_number is not None:
                start = value_number
                end = value_number
            elif (
                start is None
                or end is None
                or not math.isclose(start, end, rel_tol=0.0, abs_tol=1e-12)
            ):
                raise ValueError(f"Reference line {index} requires one exact value.")
        if start is None or end is None:
            raise ValueError(
                f"Reference guide {index} requires finite start and end values."
            )
        transparency_value = item.get("transparency")
        try:
            transparency = int(
                86
                if transparency_value is None and kind == "band"
                else 35
                if transparency_value is None
                else transparency_value
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Reference guide {index} transparency must be an integer."
            ) from exc
        minimum_transparency = 0
        if not minimum_transparency <= transparency <= 95:
            raise ValueError(
                f"Reference guide {index} transparency must be between "
                f"{minimum_transparency} and 95."
            )
        guide_contract: dict[str, Any] = {
            "id": str(item.get("id") or f"guide_{index}"),
            "kind": kind,
            "axis": axis,
            "start": min(start, end),
            "end": max(start, end),
            "color": str(item.get("color") or "#6B7280"),
            "transparency": transparency,
        }
        if kind == "line":
            line_width_value = item.get("line_width_pt")
            try:
                line_width_pt = float(
                    UNIFIED_LINE_WIDTH_PT
                    if line_width_value is None
                    else line_width_value
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Reference line {index} width must be numeric."
                ) from exc
            if not math.isfinite(line_width_pt) or not 0.0 < line_width_pt <= 5.0:
                raise ValueError(
                    f"Reference line {index} width must be finite and "
                    "between 0 and 5 pt."
                )
            line_style = str(item.get("line_style") or "dashed").strip().casefold()
            if line_style not in DEFAULT_LINE_STYLE_SEQUENCE:
                raise ValueError(
                    f"Reference line {index} uses an unsupported line style."
                )
            guide_contract.update(
                {
                    # Validate the request above, then keep generated reference
                    # lines on the same project-wide physical stroke contract.
                    "line_width_pt": UNIFIED_LINE_WIDTH_PT,
                    "line_style": line_style,
                }
            )
        guides.append(guide_contract)
    return guides


def _veusz_axes_spec(
    *,
    render_options: dict[str, Any],
    axis_info: dict[str, Any],
    axis_contract: _VeuszAxisContract,
    categorical_contract: dict[str, Any] | None,
    style: _VeuszStyleContract,
) -> dict[str, dict[str, Any]]:
    x_scale = _axis_scale(render_options, "x")
    y_scale = _axis_scale(render_options, "y")
    explicit_x_minor_ticks = list(_float_tuple(render_options.get("x_minor_ticks")))
    explicit_y_minor_ticks = list(_float_tuple(render_options.get("y_minor_ticks")))
    return {
        "x": {
            "label": axis_info["x_label"],
            "scale": x_scale,
            "tick_format": str(
                render_options.get("x_tick_format")
                or (DEFAULT_LOG_TICK_FORMAT if x_scale == "log" else "Auto")
            ),
            "minor_tick_count": int(
                render_options.get("x_minor_tick_count")
                or render_options.get("minor_tick_count")
                or (DEFAULT_LOG_MINOR_TICK_COUNT if x_scale == "log" else 20)
            ),
            "minor_ticks": (
                explicit_x_minor_ticks
                if explicit_x_minor_ticks
                else _log_minor_ticks(
                    axis_contract.x_min,
                    axis_contract.x_max,
                    scale=x_scale,
                    major_ticks=axis_contract.x_ticks,
                )
            ),
            "min": axis_contract.x_min,
            "max": axis_contract.x_max,
            "ticks": list(axis_contract.x_ticks),
            "reverse": render_options.get("reverse_x") is True,
            "foreground_color": UNIFIED_FOREGROUND_COLOR,
            "label_size_pt": style.font_size_pt,
            "tick_label_size_pt": style.font_size_pt,
            "line_width_pt": style.axis_linewidth_pt,
            "major_tick_width_pt": style.tick_width_pt,
            "major_tick_length_pt": style.tick_length_pt,
            "minor_tick_width_pt": style.minor_tick_width_pt,
            "minor_tick_length_pt": style.minor_tick_length_pt,
            "mode": ("labels" if categorical_contract is not None else "numeric"),
            "category_labels": list(axis_info.get("category_labels") or []),
            "category_positions": list(axis_info.get("category_positions") or []),
        },
        "y": {
            "label": axis_info["y_label"],
            "scale": y_scale,
            "tick_format": str(
                render_options.get("y_tick_format")
                or (DEFAULT_LOG_TICK_FORMAT if y_scale == "log" else "Auto")
            ),
            "minor_tick_count": int(
                render_options.get("y_minor_tick_count")
                or render_options.get("minor_tick_count")
                or (DEFAULT_LOG_MINOR_TICK_COUNT if y_scale == "log" else 20)
            ),
            "minor_ticks": (
                explicit_y_minor_ticks
                if explicit_y_minor_ticks
                else _log_minor_ticks(
                    axis_contract.y_min,
                    axis_contract.y_max,
                    scale=y_scale,
                    major_ticks=axis_contract.y_ticks,
                )
            ),
            "min": axis_contract.y_min,
            "max": axis_contract.y_max,
            "ticks": list(axis_contract.y_ticks),
            "show_ticks": render_options.get("show_y_ticks") is not False,
            "foreground_color": UNIFIED_FOREGROUND_COLOR,
            "label_size_pt": style.font_size_pt,
            "tick_label_size_pt": style.font_size_pt,
            "line_width_pt": style.axis_linewidth_pt,
            "major_tick_width_pt": style.tick_width_pt,
            "major_tick_length_pt": style.tick_length_pt,
            "minor_tick_width_pt": style.minor_tick_width_pt,
            "minor_tick_length_pt": style.minor_tick_length_pt,
        },
    }


def _direct_label_contracts(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
    axis_contract: _VeuszAxisContract,
    style: _VeuszStyleContract,
    show_direct_labels: bool,
) -> list[dict[str, Any]]:
    """Derive the complete, source-bound native direct-label inventory."""

    if not show_direct_labels:
        return []
    side = str(render_options.get("series_label_side") or "auto").strip().casefold()
    reverse_x = render_options.get("reverse_x") is True
    if side not in {"left", "right"}:
        side = "left" if reverse_x else "right"
    align = "left" if side == "left" else "right"
    label_size = style.font_size_pt
    y_span = (
        axis_contract.y_max - axis_contract.y_min
        if axis_contract.y_max is not None and axis_contract.y_min is not None
        else 0.0
    )
    offset_value = render_options.get("series_label_offset_fraction")
    try:
        offset_fraction = float(0.0 if offset_value is None else offset_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Direct-label offset fraction must be numeric.") from exc
    if not math.isfinite(offset_fraction) or offset_fraction < 0.0:
        raise ValueError(
            "Direct-label offset fraction must be finite and non-negative."
        )
    y_offset = y_span * offset_fraction
    valign = (
        str(render_options.get("series_label_vertical_align") or "centre")
        .strip()
        .casefold()
    )
    if valign not in {"top", "bottom", "centre", "center"}:
        raise ValueError(
            "Direct-label vertical alignment must be top, bottom, or centre."
        )
    if valign == "center":
        valign = "centre"
    labels: list[dict[str, Any]] = []
    for index, item in enumerate(series, start=1):
        anchor = _series_label_anchor(
            item,
            reverse_x=reverse_x,
            side=side,
        )
        if anchor is None:
            continue
        x_pos, y_pos = anchor
        y_pos += y_offset
        labels.append(
            {
                "name": f"label_{index}",
                "label": item.label,
                "positioning": "axes",
                "x_axis": "x",
                "y_axis": "y",
                "x": x_pos,
                "y": y_pos,
                "align": align,
                "valign": valign,
                "angle_degrees": 0.0,
                "margin_pt": 1.0 if valign == "bottom" else 0.0,
                "clip": True,
                "text_size_pt": label_size,
                "text_color": item.color,
                "text_hide": False,
                "background_color": "white",
                "background_transparency": 0,
                "background_hide": True,
                "border_color": UNIFIED_FOREGROUND_COLOR,
                "border_width_pt": style.axis_linewidth_pt,
                "border_style": "solid",
                "border_transparency": 0,
                "border_hide": True,
            }
        )
    return labels


def _categorical_axis_label_contracts(
    categorical_contract: dict[str, Any] | None,
    *,
    axis_contract: _VeuszAxisContract,
    style: _VeuszStyleContract,
) -> list[dict[str, Any]]:
    """Categorical labels are owned by the shared native Veusz x-axis."""

    return []
