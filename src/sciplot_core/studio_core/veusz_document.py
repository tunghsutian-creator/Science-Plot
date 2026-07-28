"""Build and persist one editable Veusz document from a renderer-neutral specification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_render.models import (
    StudioSeries,
)
from sciplot_core.studio_render.series_domain import (
    _resolved_domain_render_options,
)
from sciplot_core.studio_render.categorical_values import (
    _veusz_axis_label,
)
from sciplot_core.studio_render.categorical_series import (
    _reindex_categorical_series,
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
from sciplot_core.studio_render.axis_extent import (
    _expand_axis_for_visual_extents,
)
from sciplot_core.studio_render.axis_contract import (
    _veusz_axis_contract,
)
from sciplot_core.studio_render.legend_visibility import (
    _veusz_legend_mode,
    _show_veusz_direct_labels,
    _show_veusz_key,
)
from sciplot_core.studio_render.value_parsing import (
    _size_mm,
    _string_list,
)

from sciplot_core.studio_core.veusz_spec_builder import (
    _build_veusz_plot_spec,
)

from sciplot_core.studio_core.veusz_save import (
    _save_veusz_document_from_spec,
)

from sciplot_core.studio_core.registry_state import (
    _veusz_spec_path,
)


def _write_veusz_document(
    path: Path,
    *,
    request: dict[str, Any],
    series: list[StudioSeries],
    axis_info: dict[str, Any],
) -> Path:
    performance_payload = axis_info.get("performance_comparison")
    if isinstance(performance_payload, dict):
        from sciplot_core.performance_veusz import build_performance_veusz_spec

        ledger = (
            request.get("transform_ledger")
            if isinstance(request.get("transform_ledger"), dict)
            else {}
        )
        spec = build_performance_veusz_spec(
            payload=performance_payload,
            request=request,
            transform_steps=[
                dict(item) for item in ledger.get("steps", []) if isinstance(item, dict)
            ],
        )
        spec_path = _veusz_spec_path(path)
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(
            json.dumps(json_safe(spec), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _save_veusz_document_from_spec(path, spec, spec_path=spec_path)
        generate_log = path.parent / "logs" / "veusz_generate_stderr.log"
        if generate_log.exists():
            spec["stderr_logs"] = {"generate": str(generate_log)}
        spec_path.write_text(
            json.dumps(json_safe(spec), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return spec_path
    render_options = _resolved_domain_render_options(
        request,
        axis_info=axis_info,
        series=series,
    )
    series, legend_label_mapping = _compact_replicate_series_labels(series)
    if legend_label_mapping:
        render_options = dict(render_options)
        render_options["_legend_label_mapping"] = legend_label_mapping
        render_options["_autofixes_applied"] = sorted(
            {
                *_string_list(render_options.get("_autofixes_applied")),
                "replicate_legend_prefix_compacted",
            }
        )
    template_id = _request_template(request)
    render_options = _apply_readability_render_defaults(
        render_options,
        request=request,
        axis_info=axis_info,
        series=series,
        template_id=template_id,
    )
    axis_info = dict(axis_info)
    axis_info["x_label"] = _veusz_axis_label(
        render_options.get("x_label_override") or axis_info["x_label"]
    )
    axis_info["y_label"] = _veusz_axis_label(
        render_options.get("y_label_override") or axis_info["y_label"]
    )
    legend_mode = _veusz_legend_mode(render_options, template_id=template_id)
    style = _veusz_style_contract(render_options)
    categorical_contract = _categorical_plot_contract(
        series,
        template_id=template_id,
        render_options=render_options,
    )
    base_axis_contract = _veusz_axis_contract(
        render_options,
        template_id=template_id,
        series=series,
        explicit_render_options=_explicit_render_options(request),
    )
    width, height = _size_mm(str(render_options.get("size") or "60x55"))
    axis_contract, visual_extent_diagnostics = _expand_axis_for_visual_extents(
        base_axis_contract,
        request=request,
        render_options=render_options,
        template_id=template_id,
        series=series,
        categorical_contract=categorical_contract,
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
    categorical_contract = _categorical_plot_contract(
        series,
        template_id=template_id,
        render_options=render_options,
    )
    axis_contract, visual_extent_diagnostics = _expand_axis_for_visual_extents(
        base_axis_contract,
        request=request,
        render_options=render_options,
        template_id=template_id,
        series=series,
        categorical_contract=categorical_contract,
        style=style,
        width_mm=width,
        height_mm=height,
    )
    render_options = dict(render_options)
    render_options["_visual_extent_axis_diagnostics"] = visual_extent_diagnostics
    if visual_extent_diagnostics.get("expanded_axes"):
        render_options["_autofixes_applied"] = sorted(
            {
                *_string_list(render_options.get("_autofixes_applied")),
                "physical_visual_extent_axis_clearance",
            }
        )
    show_key = _show_veusz_key(
        template_id=template_id, render_options=render_options, series_count=len(series)
    )
    show_direct_labels = _show_veusz_direct_labels(
        template_id=template_id,
        render_options=render_options,
        series_count=len(series),
        show_key=show_key,
    )
    spec = _build_veusz_plot_spec(
        request=request,
        render_options=render_options,
        template_id=template_id,
        series=series,
        axis_info=axis_info,
        axis_contract=axis_contract,
        style=style,
        width_mm=width,
        height_mm=height,
        legend_mode=legend_mode,
        show_key=show_key,
        show_direct_labels=show_direct_labels,
    )
    spec_path = _veusz_spec_path(path)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        json.dumps(json_safe(spec), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _save_veusz_document_from_spec(path, spec, spec_path=spec_path)
    generate_log = path.parent / "logs" / "veusz_generate_stderr.log"
    if generate_log.exists():
        spec["stderr_logs"] = {"generate": str(generate_log)}
    spec_path.write_text(
        json.dumps(json_safe(spec), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return spec_path
