"""Serialize Studio series into renderer-neutral Veusz contracts."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_render.models import (
    CATEGORICAL_SERIES_KINDS,
    IMPACT_POINT_LINE_MARKER_KIND,
    IMPACT_POINT_LINE_RAW_KIND,
    StudioSeries,
    _VeuszStyleContract,
)

from sciplot_core.studio_core.models import MARKER_MAP
from sciplot_core.studio_core.series_request import _marker_thin_factor


def build_veusz_series_specs(
    *,
    series: list[StudioSeries],
    template_id: str,
    render_options: dict[str, Any],
    categorical_contract: dict[str, Any] | None,
    categorical_visual_style: dict[str, Any],
    style: _VeuszStyleContract,
) -> list[dict[str, Any]]:
    """Convert typed Studio series into serializable Veusz series entries."""

    return [
        _build_veusz_series_spec(
            item,
            index=index,
            template_id=template_id,
            render_options=render_options,
            categorical_contract=categorical_contract,
            categorical_visual_style=categorical_visual_style,
            style=style,
        )
        for index, item in enumerate(series, start=1)
        if item.presentation_kind != "scalar_field"
    ]


def _build_veusz_series_spec(
    item: StudioSeries,
    *,
    index: int,
    template_id: str,
    render_options: dict[str, Any],
    categorical_contract: dict[str, Any] | None,
    categorical_visual_style: dict[str, Any],
    style: _VeuszStyleContract,
) -> dict[str, Any]:
    return {
        "name": f"series_{index}",
        "label": item.label,
        "legend_key": (
            ""
            if item.presentation_kind
            in {
                "categorical_components",
                IMPACT_POINT_LINE_MARKER_KIND,
                IMPACT_POINT_LINE_RAW_KIND,
            }
            else item.label
        ),
        "x_name": item.x_name,
        "y_name": item.y_name,
        "x_values": list(item.x_values),
        "y_values": list(item.y_values),
        "error_values": list(item.error_values),
        "color": item.color,
        "line_width_pt": item.line_width,
        "line_style": item.line_style,
        "marker": str(MARKER_MAP.get(item.marker, item.marker or "none")),
        "marker_size_pt": item.marker_size,
        "marker_thin_factor": _marker_thin_factor(item, template_id=template_id),
        "marker_fill_color": _marker_fill_color(item, render_options),
        "marker_line_color": item.marker_line_color or item.color,
        "marker_line_width_pt": (
            item.marker_line_width
            if item.marker_line_width is not None
            else style.marker_line_width_pt
        ),
        "marker_alpha": _marker_alpha(
            item,
            categorical_visual_style=categorical_visual_style,
            style=style,
        ),
        "presentation_kind": item.presentation_kind,
        "category_position": item.category_position,
        "component_labels": list(item.component_labels),
        "plot_line_hide": item.presentation_kind
        in (
            CATEGORICAL_SERIES_KINDS
            | {
                IMPACT_POINT_LINE_MARKER_KIND,
                IMPACT_POINT_LINE_RAW_KIND,
            }
        ),
        "marker_line_hide": item.presentation_kind
        in (CATEGORICAL_SERIES_KINDS | {IMPACT_POINT_LINE_RAW_KIND}),
        "raw_points_visible": _raw_points_visible(item, categorical_contract),
        "source_artifacts": [
            {"path": path, "sha256": digest} for path, digest in item.source_artifacts
        ],
    }


def _marker_fill_color(
    item: StudioSeries,
    render_options: dict[str, Any],
) -> str:
    if item.presentation_kind == "categorical_replicates":
        return item.color
    if str(render_options.get("marker_fill_mode") or "filled").casefold() == "open":
        return "white"
    return item.color


def _marker_alpha(
    item: StudioSeries,
    *,
    categorical_visual_style: dict[str, Any],
    style: _VeuszStyleContract,
) -> float:
    if item.marker_alpha is not None:
        return item.marker_alpha
    if item.presentation_kind == "categorical_replicates":
        return float(
            categorical_visual_style.get("raw_point_alpha", style.marker_alpha)
        )
    return style.marker_alpha


def _raw_points_visible(
    item: StudioSeries,
    categorical_contract: dict[str, Any] | None,
) -> bool:
    return next(
        (
            bool(group["raw_points_visible"])
            for group in (categorical_contract or {}).get("groups", [])
            if group.get("label") == item.label
        ),
        True,
    )
