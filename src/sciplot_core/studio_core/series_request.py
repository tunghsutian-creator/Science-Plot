"""Resolve source frames and build Studio series from one render request."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.materials_rules import (
    format_plot_text_units,
)
from sciplot_core.publication import (
    build_transform_step,
)
from sciplot_core.source_coverage import (
    evaluate_mapping_source_coverage,
)
from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
    StudioSeries,
)
from sciplot_core.studio_render.series_domain import (
    _resolved_domain_render_options,
    _validate_log_domain_series,
)
from sciplot_core.studio_render.frame_series import (
    _series_from_frame_records,
)
from sciplot_core.studio_render.table_io import (
    _read_source_frame_records,
)
from sciplot_core.studio_render.series_options import (
    _apply_series_options,
)
from sciplot_core.studio_render.readability_defaults import (
    _apply_readability_render_defaults,
)
from sciplot_core.studio_render.series_transforms import (
    _apply_template_series_transforms,
)
from sciplot_core.studio_render.template_resolution import (
    _request_template,
)

from sciplot_core.studio_core.impact_series import (
    _impact_point_line_series_from_source,
)


def _series_from_request(
    request: dict[str, Any],
    *,
    base_dir: Path,
) -> tuple[list[StudioSeries], dict[str, Any], list[dict[str, Any]], Path]:
    if "_terminal_source_prepared" in request:
        raise ValueError(
            "`_terminal_source_prepared` is reserved and cannot appear in a "
            "plot request."
        )
    input_value = request.get("input")
    if not isinstance(input_value, str) or not input_value.strip():
        raise ValueError(
            "plot_request.json needs an input path for Studio document generation."
        )
    source = Path(input_value).expanduser()
    if not source.is_absolute():
        source = (base_dir / source).resolve()
    source_root = source
    effective_request, mapping_application = resolve_data_mapping_request(
        request,
        base_dir=base_dir,
    )
    effective_input = effective_request.get("input")
    if not isinstance(effective_input, str) or not effective_input.strip():
        raise ValueError("Resolved data mapping request has no effective input path.")
    source = Path(effective_input).expanduser()
    if not source.is_absolute():
        source = (base_dir / source).resolve()
    request = effective_request
    transform_steps = [
        dict(step)
        for step in (
            mapping_application.get("transform_steps", [])
            if mapping_application is not None
            else []
        )
        if isinstance(step, dict)
    ]
    if str(
        request.get("rule_id") or ""
    ).strip() == "performance_comparison" and _request_template(request) in {
        "scatter",
        "polar_curve",
    }:
        from sciplot_core.performance_comparison import (
            PerformanceComparisonError,
            performance_transform_parameters,
            prepare_performance_comparison,
        )
        from sciplot_core.performance_veusz import performance_series_records

        template_id = _request_template(request)
        try:
            payload = prepare_performance_comparison(
                source,
                template_id=template_id,
            )
        except PerformanceComparisonError as exc:
            raise StudioPreparationBlocked(exc.reason_code, str(exc)) from exc
        records = performance_series_records(payload)
        artifact = (str(payload["source"]), str(payload["source_sha256"]))
        styled = [
            StudioSeries(
                label=str(item["label"]),
                x_name=str(item["x_name"]),
                y_name=str(item["y_name"]),
                x_values=tuple(float(value) for value in item["x_values"]),
                y_values=tuple(float(value) for value in item["y_values"]),
                color=str(item["color"]),
                line_width=float(item["line_width_pt"]),
                marker=str(item["marker"]),
                marker_size=float(item["marker_size_pt"]),
                line_style=str(item["line_style"]),
                presentation_kind=str(item["presentation_kind"]),
                source_artifacts=(artifact,),
            )
            for item in records
        ]
        transform_steps.append(
            build_transform_step(
                step_id="performance_comparison_preparation",
                operation=(
                    "validate_material_metric_contract_and_derive_presentation_geometry"
                ),
                input_path=Path(str(payload["source"])),
                output_path=None,
                implementation_ref=(
                    "sciplot_core.performance_comparison.prepare_performance_comparison"
                ),
                parameters=performance_transform_parameters(payload),
            )
        )
        axis_info = {
            "x_label": str(payload.get("x_label") or ""),
            "y_label": str(payload.get("y_label") or ""),
            "presentation_kind": "performance_comparison",
            "performance_comparison": payload,
            "series_count": len(styled),
            "semantic_terminal_series_order": [str(item["label"]) for item in records],
        }
        layout = payload["layout"]
        render_options = (
            dict(request.get("render_options"))
            if isinstance(request.get("render_options"), dict)
            else {}
        )
        render_options["size"] = "x".join(
            f"{float(value):g}" for value in layout["page_size_mm"]
        )
        if not bool(layout.get("legend_uses_reserved_panel")):
            render_options.setdefault("legend_position", "auto")
            render_options.setdefault("series_label_mode", "legend")
            for axis, bounds in (
                ("x", payload["x_bounds"]),
                ("y", payload["y_bounds"]),
            ):
                render_options.setdefault(f"{axis}_min", float(bounds[0]))
                render_options.setdefault(f"{axis}_max", float(bounds[1]))
            render_options = _apply_readability_render_defaults(
                render_options,
                request=request,
                axis_info=axis_info,
                series=styled,
                template_id=template_id,
            )
            payload["inside_legend_render_options"] = json_safe(render_options)
        request["render_options"] = render_options
        return styled, axis_info, transform_steps, source_root
    if (
        str(request.get("rule_id") or "").strip() == "impact_metric"
        and _request_template(request) == "point_line"
    ):
        raw_series, axis_info, impact_steps = _impact_point_line_series_from_source(
            source, request=request
        )
        transform_steps.extend(impact_steps)
        # The overlay builder owns its layered internal series order. Public
        # ordering is expressed by condition_order and the categorical sample
        # axis, not by the generated summary/marker/raw helper labels.
        request.pop("series_order", None)
        if isinstance(request.get("render_options"), dict):
            request["render_options"] = {
                key: value
                for key, value in request["render_options"].items()
                if key != "series_order"
            }
        render_options = _resolved_domain_render_options(
            request,
            axis_info=axis_info,
            series=raw_series,
        )
        styled = _apply_series_options(
            raw_series,
            render_options=render_options,
            request=request,
        )
        styled = _apply_template_series_transforms(
            styled,
            request=request,
            render_options=render_options,
        )
        _validate_log_domain_series(styled, render_options=render_options)
        axis_info["series_count"] = len(styled)
        axis_info["semantic_terminal_series_order"] = [item.label for item in styled]
        return styled, axis_info, transform_steps, source_root
    source, semantic_steps = _studio_source_for_request(
        source,
        request=request,
        base_dir=base_dir,
    )
    transform_steps.extend(semantic_steps)
    frames = _read_source_frame_records(source, request=request)
    styled, axis_info = _series_from_frame_records(request, frames=frames)
    axis_info["semantic_terminal_series_order"] = [item.label for item in styled]
    if mapping_application is not None:
        axis_info["data_mapping_coverage"] = _mapping_series_coverage(
            styled,
            mapping_application=mapping_application,
            request=request,
        )
    return styled, axis_info, transform_steps, source_root


def _mapping_series_coverage(
    series: list[StudioSeries],
    *,
    mapping_application: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    try:
        coverage = evaluate_mapping_source_coverage(
            [
                {
                    "identity": f"studio_series_{index}:{item.label}",
                    "kind": item.presentation_kind,
                    "source_artifacts": item.source_artifacts,
                }
                for index, item in enumerate(series, start=1)
            ],
            mapping_application=mapping_application,
            template=_request_template(request),
        )
        return {
            **coverage,
            "actual_series_labels": [str(item.label) for item in series],
        }
    except (FileNotFoundError, ValueError) as exc:
        raise StudioPreparationBlocked(
            "mapped_source_coverage_incomplete",
            f"Studio would omit a confirmed mapped source before VSZ generation: {exc}",
        ) from exc


def _veusz_literal_text(value: object) -> str:
    """Escape sample/category text so Veusz does not treat identifiers as math markup."""

    text = format_plot_text_units(value).replace("\\", "\ue000")
    text = re.sub(r"([_\^\[\]\{\}])", r"\\\1", text)
    return text.replace("\ue000", "{\\backslash}")


veusz_literal_text = _veusz_literal_text


def _studio_source_for_request(
    source: Path,
    *,
    request: dict[str, Any],
    base_dir: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    rule_id = str(request.get("rule_id") or "").strip()
    if not rule_id:
        return source, []
    from sciplot_core.semantic import classify_source, prepare_semantic_source

    output_dir = base_dir / "studio"
    semantic = classify_source(source, requested_rule_id=rule_id)
    curation_value = request.get("curation")
    curation_path: Path | None = None
    if isinstance(curation_value, str) and curation_value.strip():
        curation_path = Path(curation_value).expanduser()
        if not curation_path.is_absolute():
            curation_path = (base_dir / curation_path).resolve()
    prepared = prepare_semantic_source(
        source,
        output_dir=output_dir,
        semantic=semantic,
        curation_path=curation_path,
        series_order=request.get("series_order"),
        column_confirmations=request.get("column_confirmations"),
        replicate_mode=request.get("replicate_mode"),
    )
    prepared_source = prepared.get("source")
    transform_steps = [
        step for step in prepared.get("transform_steps", []) if isinstance(step, dict)
    ]
    terminal_series_order = _semantic_terminal_series_order(transform_steps)
    if terminal_series_order:
        request["series_order"] = terminal_series_order
        render_options = request.get("render_options")
        if isinstance(render_options, dict) and "series_order" in render_options:
            request["render_options"] = {
                **render_options,
                "series_order": terminal_series_order,
            }
    if isinstance(prepared_source, str) and prepared_source.strip():
        return Path(prepared_source).expanduser(), transform_steps
    return source, transform_steps


def _semantic_terminal_series_order(
    transform_steps: list[dict[str, Any]],
) -> list[str]:
    for step in reversed(transform_steps):
        parameters = step.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for key in ("output_sample_labels", "series_order", "sample_order"):
            values = parameters.get(key)
            if not isinstance(values, list | tuple):
                continue
            result: list[str] = []
            for value in values:
                label = str(value).strip()
                if label and label not in result:
                    result.append(label)
            if result:
                return result
    return []


def _read_source_frames(
    source: Path,
    *,
    request: dict[str, Any] | None = None,
) -> list[tuple[str, pd.DataFrame]]:
    return [
        (record.label, record.frame)
        for record in _read_source_frame_records(source, request=request)
    ]


def _marker_thin_factor(item: StudioSeries, *, template_id: str) -> int:
    """Render a marker at every measured point for point-line series."""

    del item, template_id
    return 1
