"""Resolve legend mode, columns, direct labels, anchors, and key visibility."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    normalize_legend_position,
)

from sciplot_core.studio_render.models import (
    STACKED_TEMPLATE_IDS,
    CATEGORICAL_TEMPLATE_IDS,
    SCALAR_FIELD_TEMPLATE_IDS,
    StudioSeries,
)


def _veusz_legend_mode(render_options: dict[str, Any], *, template_id: str) -> str:
    legend_position = normalize_legend_position(render_options.get("legend_position"))
    if legend_position in {"none", "hide", "hidden", "off"}:
        return "none"
    if legend_position in {
        "upper_right",
        "upper_left",
        "lower_left",
        "lower_right",
        "manual",
    }:
        return legend_position
    if template_id in STACKED_TEMPLATE_IDS:
        label_mode = str(render_options.get("series_label_mode") or "").casefold()
        return "none" if label_mode in {"inline", "edge"} else "upper_right"
    return "inside_best"


def _legend_columns(
    *,
    series_count: int,
    mode: str = "inside_best",
    max_label_length: int = 0,
    figure_width_mm: float | None = None,
) -> int:
    if series_count <= 4:
        return 1
    if (
        figure_width_mm is not None
        and figure_width_mm <= 60.5
        and max_label_length >= 22
    ):
        return 1
    return 2


def _show_veusz_direct_labels(
    *,
    template_id: str,
    render_options: dict[str, Any],
    series_count: int,
    show_key: bool,
) -> bool:
    if show_key or series_count <= 0 or template_id not in STACKED_TEMPLATE_IDS:
        return False
    label_mode = str(render_options.get("series_label_mode") or "").strip().casefold()
    if series_count == 1 and render_options.get("show_single_series_label") is not True:
        return False
    return label_mode in {"inline", "edge", "auto"}


def _series_label_anchor(
    item: StudioSeries, *, reverse_x: bool, side: str
) -> tuple[float, float] | None:
    points = sorted(
        (
            (float(x_value), float(y_value))
            for x_value, y_value in zip(item.x_values, item.y_values, strict=True)
            if math.isfinite(x_value) and math.isfinite(y_value)
        ),
        key=lambda pair: pair[0],
    )
    if not points:
        return None
    x_values = [point[0] for point in points]
    x_min = min(x_values)
    x_max = max(x_values)
    span = x_max - x_min
    if math.isclose(span, 0.0):
        target_x = x_min
    elif side == "left":
        target_x = x_max - span * 0.06 if reverse_x else x_min + span * 0.06
    else:
        target_x = x_min + span * 0.06 if reverse_x else x_max - span * 0.06
    nearest = min(points, key=lambda pair: abs(pair[0] - target_x))
    return nearest


def _show_veusz_key(
    *, template_id: str, render_options: dict[str, Any], series_count: int
) -> bool:
    categorical_segmented_legend = (
        render_options.get("_categorical_component_legend") is True
        or render_options.get("_categorical_grouped_legend") is True
    )
    if template_id in SCALAR_FIELD_TEMPLATE_IDS:
        return False
    if series_count <= 1:
        return categorical_segmented_legend
    if template_id in CATEGORICAL_TEMPLATE_IDS:
        if not categorical_segmented_legend:
            return False
        legend_position = (
            str(render_options.get("legend_position") or "auto").strip().casefold()
        )
        return legend_position not in {"none", "hide", "hidden", "off"}
    label_mode = (
        str(render_options.get("series_label_mode") or "legend").strip().casefold()
    )
    legend_position = (
        str(render_options.get("legend_position") or "auto").strip().casefold()
    )
    if template_id in STACKED_TEMPLATE_IDS and label_mode in {"inline", "edge", "auto"}:
        return False
    if legend_position in {"none", "hide", "hidden", "off"}:
        return False
    return True
