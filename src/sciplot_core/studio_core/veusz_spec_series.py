"""Serialize Studio series into renderer-neutral Veusz contracts."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_render.models import (
    IMPACT_POINT_LINE_MARKER_KIND,
    IMPACT_POINT_LINE_RAW_KIND,
    StudioSeries,
    _VeuszStyleContract,
)

from sciplot_core.studio_core.series_encoding_contract import (
    build_series_encoding_resolution,
)


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
    raw_points_visible = _raw_points_visible(item, categorical_contract)
    encoding = build_series_encoding_resolution(
        item,
        template_id=template_id,
        categorical_visual_style=categorical_visual_style,
        style=style,
        raw_points_visible=raw_points_visible,
    )
    line = encoding["line"]
    marker = encoding["marker"]
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
        "encoding": encoding,
        "color": line["color"],
        "line_width_pt": line["width_pt"],
        "line_style": line["style"],
        "marker": marker["shape"],
        "marker_size_pt": marker["size_pt"],
        "marker_thin_factor": marker["thin_factor"],
        "marker_fill_color": marker["fill_color"],
        "marker_line_color": marker["line_color"],
        "marker_line_width_pt": marker["line_width_pt"],
        "marker_alpha": marker["fill_alpha"],
        "presentation_kind": item.presentation_kind,
        "category_position": item.category_position,
        "component_labels": list(item.component_labels),
        "plot_line_hide": not line["visible"],
        "marker_line_hide": not marker["line_visible"],
        "raw_points_visible": raw_points_visible,
        "source_artifacts": [
            {"path": path, "sha256": digest} for path, digest in item.source_artifacts
        ],
    }


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
