"""Assemble the complete renderer-neutral Veusz plot specification."""

from __future__ import annotations

from typing import Any

from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.policy import FIXED_PUBLICATION_FRAME_POLICY
from sciplot_core.studio_render.axes_spec import (
    _reference_guides_contract,
    _veusz_axes_spec,
)
from sciplot_core.studio_render.categorical_plot_spec import (
    _categorical_plot_contract,
)
from sciplot_core.studio_render.models import (
    StudioSeries,
    _VeuszAxisContract,
    _VeuszStyleContract,
)
from sciplot_core.studio_render.scalar_plot_spec import (
    _scalar_field_plot_contract,
)
from sciplot_core.studio_render.value_parsing import _string_list

from sciplot_core.studio_core.runtime import upstream_status
from sciplot_core.studio_core.semantic_validation import _visual_data_transforms
from sciplot_core.studio_core.veusz_spec_labels import (
    build_veusz_direct_labels,
    build_veusz_legend_spec,
)
from sciplot_core.studio_core.veusz_spec_layout import (
    build_veusz_layout_issues,
)
from sciplot_core.studio_core.veusz_spec_series import (
    build_veusz_series_specs,
)


def _build_veusz_plot_spec(
    *,
    request: dict[str, Any],
    render_options: dict[str, Any],
    template_id: str,
    series: list[StudioSeries],
    axis_info: dict[str, Any],
    axis_contract: _VeuszAxisContract,
    style: _VeuszStyleContract,
    width_mm: float,
    height_mm: float,
    legend_mode: str,
    show_key: bool,
    show_direct_labels: bool,
) -> dict[str, Any]:
    """Compose independent scalar, categorical, layout, and style contracts."""

    scalar_field = _scalar_field_plot_contract(
        axis_info,
        render_options=render_options,
        template_id=template_id,
        style=style,
    )
    categorical = _categorical_plot_contract(
        series,
        template_id=template_id,
        render_options=render_options,
    )
    categorical_style = (
        categorical.get("visual_style")
        if isinstance(categorical, dict)
        and isinstance(categorical.get("visual_style"), dict)
        else {}
    )
    direct_labels = build_veusz_direct_labels(
        series=series,
        render_options=render_options,
        axis_contract=axis_contract,
        style=style,
        show_direct_labels=show_direct_labels,
        categorical_contract=categorical,
    )
    legend, factor_legend = build_veusz_legend_spec(
        series=series,
        template_id=template_id,
        render_options=render_options,
        categorical_contract=categorical,
        style=style,
        legend_mode=legend_mode,
        show_key=show_key,
        width_mm=width_mm,
    )
    layout_issues = build_veusz_layout_issues(
        request=request,
        render_options=render_options,
        template_id=template_id,
        series=series,
        axis_info=axis_info,
        axis_contract=axis_contract,
        categorical_contract=categorical,
        factor_legend=factor_legend,
        show_key=show_key,
    )
    return {
        "kind": "sciplot_veusz_plot_spec",
        "version": 1,
        "created_at": utc_now_iso(),
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "template": template_id,
        "source_request": json_safe(request),
        "render_options": json_safe(render_options),
        "size_mm": [width_mm, height_mm],
        "frame_alignment": _frame_alignment(style),
        "autofixes_applied": _string_list(render_options.get("_autofixes_applied")),
        "visual_extent_axis_clearance": json_safe(
            render_options.get("_visual_extent_axis_diagnostics") or {}
        ),
        "layout_issues": layout_issues,
        "visual_data_transforms": _visual_data_transforms(
            template_id=template_id,
            render_options=render_options,
            series_count=len(series),
        ),
        "provenance": {"veusz": upstream_status()["veusz"]},
        "style": _style_spec(style),
        "axes": _veusz_axes_spec(
            render_options=render_options,
            axis_info=axis_info,
            axis_contract=axis_contract,
            categorical_contract=categorical,
            style=style,
        ),
        "legend": legend,
        "categorical": categorical,
        "scalar_field": scalar_field,
        "reference_guides": _reference_guides_contract(render_options),
        "series": build_veusz_series_specs(
            series=series,
            template_id=template_id,
            render_options=render_options,
            categorical_contract=categorical,
            categorical_visual_style=categorical_style,
            style=style,
        ),
        "direct_labels": direct_labels,
    }


def _frame_alignment(style: _VeuszStyleContract) -> dict[str, Any]:
    return {
        "status": "locked",
        "margin_mode": FIXED_PUBLICATION_FRAME_POLICY.margin_mode,
        "outside_legend_allowed": FIXED_PUBLICATION_FRAME_POLICY.outside_legend_allowed,
        "auxiliary_frame_envelope": (
            FIXED_PUBLICATION_FRAME_POLICY.auxiliary_frame_envelope
        ),
        "auxiliary_text_envelope": (
            FIXED_PUBLICATION_FRAME_POLICY.auxiliary_text_envelope
        ),
        "margins_mm": _margins_spec(style),
    }


def _style_spec(style: _VeuszStyleContract) -> dict[str, Any]:
    return {
        "font_family": style.font_family,
        "font_size_pt": style.font_size_pt,
        "legend_font_size_pt": style.legend_font_size_pt,
        "axis_linewidth_pt": style.axis_linewidth_pt,
        "tick_width_pt": style.tick_width_pt,
        "tick_length_pt": style.tick_length_pt,
        "minor_tick_width_pt": style.minor_tick_width_pt,
        "minor_tick_length_pt": style.minor_tick_length_pt,
        "line_width_pt": style.line_width_pt,
        "line_alpha": style.line_alpha,
        "marker_alpha": style.marker_alpha,
        "marker_size_pt": style.marker_size_pt,
        "marker_line_width_pt": style.marker_line_width_pt,
        "axes_labelpad_pt": style.axes_labelpad_pt,
        "xtick_major_pad_pt": style.xtick_major_pad_pt,
        "ytick_major_pad_pt": style.ytick_major_pad_pt,
        "legend_frameon": style.legend_frameon,
        "margins_mm": _margins_spec(style),
    }


def _margins_spec(style: _VeuszStyleContract) -> dict[str, float]:
    return {
        "left": style.left_margin_mm,
        "right": style.right_margin_mm,
        "bottom": style.bottom_margin_mm,
        "top": style.top_margin_mm,
    }
