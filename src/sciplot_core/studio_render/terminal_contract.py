"""Derive the terminal render-data contract from a confirmed plotting request."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.scalar_visual import (
    scalar_visual_contract,
)

from sciplot_core.studio_render.models import (
    CATEGORICAL_SERIES_KINDS,
    StudioSourceFrame,
)

from sciplot_core.studio_render.series_domain import (
    _resolved_domain_render_options,
)

from sciplot_core.studio_render.frame_series import (
    _series_from_frame_records,
)

from sciplot_core.studio_render.categorical_values import (
    _veusz_axis_label,
)

from sciplot_core.studio_render.categorical_series import (
    _reindex_categorical_series,
)

from sciplot_core.studio_render.table_io import (
    _read_source_frame_records,
)

from sciplot_core.studio_render.style_contract import (
    _veusz_style_contract,
)
from sciplot_core.studio_render.domain_defaults import (
    _explicit_render_options,
)

from sciplot_core.studio_render.label_density import (
    _compact_replicate_series_labels,
)

from sciplot_core.studio_render.categorical_layout import (
    _apply_categorical_box_aspect_width,
)

from sciplot_core.studio_render.readability_defaults import (
    _apply_readability_render_defaults,
)

from sciplot_core.studio_render.template_resolution import (
    _request_template,
)

from sciplot_core.studio_render.categorical_plot_spec import (
    _categorical_plot_contract,
)

from sciplot_core.studio_render.scalar_plot_spec import (
    _scalar_field_plot_contract,
)

from sciplot_core.studio_render.axes_spec import (
    _reference_guides_contract,
    _veusz_axes_spec,
    _direct_label_contracts,
    _categorical_axis_label_contracts,
)

from sciplot_core.studio_render.axis_extent import (
    _expand_axis_for_visual_extents,
)

from sciplot_core.studio_render.axis_contract import (
    _veusz_axis_contract,
)

from sciplot_core.studio_render.legend_visibility import (
    _show_veusz_direct_labels,
    _show_veusz_key,
)

from sciplot_core.studio_render.value_parsing import (
    _size_mm,
)


def derive_terminal_render_data_contract(
    *,
    request: dict[str, Any],
    terminal_sources: list[Path],
) -> dict[str, Any]:
    """Replay terminal tables into the numeric units the renderer must consume."""

    resolved_sources = [source.expanduser().resolve() for source in terminal_sources]
    if not resolved_sources or len(resolved_sources) != len(set(resolved_sources)):
        raise ValueError("Terminal render-data derivation needs unique source files.")
    frames: list[StudioSourceFrame] = []
    for source in resolved_sources:
        if not source.is_file():
            raise FileNotFoundError(f"Terminal plotted source is not a file: {source}")
        frames.extend(_read_source_frame_records(source, request=request))
    series, axis_info = _series_from_frame_records(request, frames=frames)
    series, _legend_label_mapping = _compact_replicate_series_labels(series)
    render_options = _resolved_domain_render_options(
        request=request,
        axis_info=axis_info,
        series=series,
    )
    template_id = _request_template(request)
    render_options = _apply_readability_render_defaults(
        render_options,
        request=request,
        axis_info=axis_info,
        series=series,
        template_id=template_id,
    )
    categorical = _categorical_plot_contract(
        series,
        template_id=template_id,
        render_options=render_options,
    )
    style = _veusz_style_contract(render_options)
    scalar_contract = _scalar_field_plot_contract(
        axis_info,
        render_options=render_options,
        template_id=template_id,
        style=style,
    )
    axis_info = dict(axis_info)
    axis_info["x_label"] = _veusz_axis_label(
        render_options.get("x_label_override") or axis_info["x_label"]
    )
    axis_info["y_label"] = _veusz_axis_label(
        render_options.get("y_label_override") or axis_info["y_label"]
    )
    base_axis_contract = _veusz_axis_contract(
        render_options,
        template_id=template_id,
        series=series,
        explicit_render_options=_explicit_render_options(request),
    )
    width, height = _size_mm(str(render_options.get("size") or "60x55"))
    axis_contract, _visual_extent_diagnostics = _expand_axis_for_visual_extents(
        base_axis_contract,
        request=request,
        render_options=render_options,
        template_id=template_id,
        series=series,
        categorical_contract=categorical,
        style=style,
        width_mm=width,
        height_mm=height,
    )
    render_options = _apply_categorical_box_aspect_width(
        render_options,
        series,
        axis_contract=axis_contract,
        template_id=template_id,
    )
    if template_id in {"box", "box_strip"}:
        series = _reindex_categorical_series(
            series,
            render_options=render_options,
        )
    categorical = _categorical_plot_contract(
        series,
        template_id=template_id,
        render_options=render_options,
    )
    axis_contract, _visual_extent_diagnostics = _expand_axis_for_visual_extents(
        base_axis_contract,
        request=request,
        render_options=render_options,
        template_id=template_id,
        series=series,
        categorical_contract=categorical,
        style=style,
        width_mm=width,
        height_mm=height,
    )
    axes = _veusz_axes_spec(
        render_options=render_options,
        axis_info=axis_info,
        axis_contract=axis_contract,
        categorical_contract=categorical,
        style=style,
    )
    show_key = _show_veusz_key(
        template_id=template_id,
        render_options=render_options,
        series_count=len(series),
    )
    show_direct_labels = _show_veusz_direct_labels(
        template_id=template_id,
        render_options=render_options,
        series_count=len(series),
        show_key=show_key,
    )
    direct_labels = _direct_label_contracts(
        series,
        render_options=render_options,
        axis_contract=axis_contract,
        style=style,
        show_direct_labels=show_direct_labels,
    )
    direct_labels.extend(
        _categorical_axis_label_contracts(
            categorical, axis_contract=axis_contract, style=style
        )
    )
    categorical_groups = {
        str(group.get("y_name") or ""): group
        for group in (
            categorical.get("groups", []) if isinstance(categorical, dict) else []
        )
        if isinstance(group, dict)
    }
    reference_guides = _reference_guides_contract(render_options)
    units: list[dict[str, Any]] = []
    scalar = axis_info.get("scalar_field")
    if isinstance(scalar, dict):
        if scalar_contract is None:
            raise ValueError("Scalar-field derivation has no closed visual contract.")
        units.append(
            {
                "kind": "scalar_field",
                "data_name": str(scalar["data_name"]),
                "x_values": list(scalar["x_values"]),
                "y_values": list(scalar["y_values"]),
                "z_values": [list(row) for row in scalar["z_values"]],
                "z_label": str(scalar["z_label"]),
                "scalar_visual": scalar_visual_contract(
                    scalar_contract,
                    label="derived scalar field",
                ),
                "axes": json_safe(axes),
                "reference_guides": json_safe(reference_guides),
                "direct_labels": json_safe(direct_labels),
                "source_artifacts": json_safe(scalar["source_artifacts"]),
            }
        )
    else:
        for index, item in enumerate(series, start=1):
            group = categorical_groups.get(item.y_name)
            units.append(
                {
                    "kind": "series",
                    "name": f"series_{index}",
                    "label": item.label,
                    "x_name": item.x_name,
                    "y_name": item.y_name,
                    "x_values": list(item.x_values),
                    "y_values": list(item.y_values),
                    "presentation_kind": item.presentation_kind,
                    "category_position": item.category_position,
                    "component_labels": list(item.component_labels),
                    "plot_line_hide": item.presentation_kind
                    in CATEGORICAL_SERIES_KINDS,
                    "raw_points_visible": (
                        bool(group["raw_points_visible"])
                        if isinstance(group, dict)
                        else True
                    ),
                    "boxplot_eligible": (
                        bool(group["boxplot_eligible"])
                        if isinstance(group, dict)
                        else False
                    ),
                    "axes": json_safe(axes),
                    "reference_guides": json_safe(reference_guides),
                    "direct_labels": json_safe(direct_labels),
                    "source_artifacts": [
                        {"path": path, "sha256": digest}
                        for path, digest in item.source_artifacts
                    ],
                }
            )
    source_artifacts = sorted({(str(frame.path), frame.sha256) for frame in frames})
    return {
        "kind": "sciplot_terminal_render_data_contract",
        "version": 1,
        "status": "passed",
        "template": template_id,
        "source_artifacts": [
            {"path": path, "sha256": digest} for path, digest in source_artifacts
        ],
        "units": units,
        "unit_count": len(units),
    }
