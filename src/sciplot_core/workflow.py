from __future__ import annotations

import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import json_safe, slug, unique_path
from sciplot_core.assisted_cleanup import (
    CLEANUP_REQUEST_FILENAME,
    consume_ready_cleanup_result,
    write_cleanup_request,
)
from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.delivery import build_delivery_package
from sciplot_core.materials_rules import (
    ELONGATION_AT_BREAK_LABEL,
    ELONGATION_AT_BREAK_METRIC,
    compute_analysis_metrics,
)
from sciplot_core.managed_output import managed_output_transaction
from sciplot_core.one_step import build_one_step_project, build_quality_actions
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.policy import (
    CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
    DEFAULT_EXPORT_FORMATS_POLICY,
    DEFAULT_RENDER_OPTIONS,
    DELIVERY_DIR,
    RHEOLOGY_METRIC_AXIS_LABELS,
    anchored_log_decade_ticks,
    compact_linear_axis,
    layout_policy_for_semantic,
    layout_policy_payload,
)
from sciplot_core.publication import (
    build_publication_intent,
    build_transform_ledger,
    build_transform_step,
    get_publication_profile,
    link_intent_to_transform_ledger,
    write_publication_artifacts,
)
from sciplot_core.request_contract import normalize_render_options
from sciplot_core.publish_state import build_publish_state
from sciplot_core.qa import run_qa
from sciplot_core.render import render_to_dir
from sciplot_core.semantic import build_intervention_request, classify_source, prepare_semantic_source
from sciplot_core.source_coverage import (
    verify_rendered_mapping_source_coverage,
)
from sciplot_core.split import (
    DEFAULT_STACK_SPLIT_POLICY,
    STACKED_TALL_FIGURE_HEIGHT_MM,
    SUPPORTED_SPLIT_TEMPLATES,
)
from sciplot_core.study_model import (
    attach_run_artifacts_to_study_model,
    build_output_package_contract,
    study_model_from_request,
)
from sciplot_recipes import run_recipe


_MANAGED_OUTPUT_DIRECTORIES = (
    "processed",
    "figures",
    "tables",
    "raw",
    DELIVERY_DIR,
)
_MANAGED_OUTPUT_FILES = (
    "request_snapshot.json",
    "manifest.json",
    "analysis_report.md",
    "revision_brief.md",
    "review.html",
    "intervention_request.json",
    CLEANUP_REQUEST_FILENAME,
    "publication_intent.json",
    "transform_ledger.json",
    "journal_profile.json",
    "publication_qa.json",
    "one_step_status.json",
    "autoplot_summary.json",
)


def _load_request(request_path: Path) -> dict[str, Any]:
    if request_path.suffix.lower() != ".json":
        raise ValueError("Plot requests currently support JSON files. Use a .json request file.")
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Plot request must be a JSON object.")
    return payload


def _resolve_request_path(value: object, *, base_dir: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Plot request must define a non-empty `{field}` path.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _resolve_optional_request_path(value: object, *, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _bind_result_data_snapshots(
    result: dict[str, Any],
    *,
    plotted_source: Path,
    mapping_application: dict[str, Any] | None,
    request: dict[str, Any],
) -> dict[str, Any]:
    resolved_source = plotted_source.expanduser().resolve()
    snapshot_paths = [resolved_source]
    if mapping_application is not None:
        effective_input = Path(
            str(mapping_application.get("effective_input") or "")
        ).expanduser().resolve()
        if resolved_source == effective_input and resolved_source.is_dir():
            snapshot_paths = sorted(
                {
                    Path(str(record.get("path") or "")).expanduser().resolve()
                    for record in mapping_application.get("mapped_outputs", [])
                    if isinstance(record, dict)
                    and isinstance(record.get("path"), str)
                    and str(record["path"]).strip()
                },
                key=str,
            )
            if not snapshot_paths:
                raise ValueError(
                    "A mapped directory render has no concrete plotted tables."
                )
            for path in snapshot_paths:
                try:
                    path.relative_to(resolved_source)
                except ValueError as exc:
                    raise ValueError(
                        "A mapped plotted table is outside the effective input "
                        "directory."
                    ) from exc
                if not path.is_file():
                    raise FileNotFoundError(
                        f"Mapped plotted table not found: {path}"
                    )
    result["data_snapshot_sources"] = [str(path) for path in snapshot_paths]
    if len(snapshot_paths) == 1:
        result["data_snapshot_source"] = str(snapshot_paths[0])
    else:
        result.pop("data_snapshot_source", None)
    if mapping_application is not None:
        result["rendered_source_coverage"] = (
            verify_rendered_mapping_source_coverage(
                result,
                mapping_application=mapping_application,
                request=request,
            )
        )
    return result


def _managed_output_transaction(output_dir: Path):
    return managed_output_transaction(
        output_dir,
        managed_names=(*_MANAGED_OUTPUT_DIRECTORIES, *_MANAGED_OUTPUT_FILES),
    )


def _request_options(request: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if "template" in request:
        options["template"] = request["template"]
    if "render_options" in request:
        options["render_options"] = request["render_options"]
    if "exports" in request:
        options["exports"] = request["exports"]
    return options


def _archive_raw_input(input_path: Path, output_dir: Path) -> dict[str, Any]:
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_path(raw_dir, input_path.name)
    if input_path.is_dir():
        shutil.copytree(input_path, destination)
        kind = "directory"
    else:
        shutil.copy2(input_path, destination)
        kind = "file"
    return {
        "kind": kind,
        "source": str(input_path),
        "path": str(destination),
    }


def _figures_from_result(result: dict[str, Any]) -> list[str]:
    figures = result.get("figures") or result.get("outputs") or []
    return [str(path) for path in figures]


def _write_render_report(output_dir: Path, *, request: dict[str, Any], result: dict[str, Any]) -> None:
    lines = [
        "# SciPlot Run",
        "",
        "- Route: `render`",
        f"- Template: `{result['template']}`",
        f"- Figures: {len(result.get('outputs', []))}",
        "",
        "## Review Notes",
        "",
    ]
    notes = request.get("review_notes") or []
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- No review notes supplied.")
    (output_dir / "analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_auto_report(
    output_dir: Path,
    *,
    request: dict[str, Any],
    result: dict[str, Any],
    semantic: dict[str, Any],
    final_recipe: str | None,
) -> None:
    lines = [
        "# SciPlot Run",
        "",
        "- Route: `auto`",
        f"- Semantic family: `{semantic['semantic_family']}`",
        f"- Final recipe: `{final_recipe or 'direct_render'}`",
        f"- Template: `{result['template']}`",
        f"- Figures: {len(result.get('outputs', []))}",
        "",
        "## Semantic Reason",
        "",
        f"- {semantic.get('reason', 'No semantic reason recorded.')}",
        "",
        "## Review Notes",
        "",
    ]
    notes = request.get("review_notes") or []
    if notes:
        lines.extend(f"- {note}" for note in notes)
    else:
        lines.append("- No review notes supplied.")
    (output_dir / "analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_review_html(output_dir: Path, *, manifest: dict[str, Any]) -> None:
    figures = [Path(path) for path in manifest.get("figures", [])]
    notes = manifest.get("request", {}).get("review_notes") or []
    revision_brief = manifest.get("revision_brief")
    figure_items = []
    for figure in figures:
        rel = figure.relative_to(output_dir) if figure.is_relative_to(output_dir) else figure
        label = escape(str(rel))
        if figure.suffix.lower() == ".png":
            figure_items.append(f'<li><a href="{label}">{label}</a><br><img src="{label}" alt="{label}"></li>')
        else:
            figure_items.append(f'<li><a href="{label}">{label}</a></li>')
    note_items = [f"<li>{escape(str(note))}</li>" for note in notes] or ["<li>No review notes supplied.</li>"]
    html = "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>SciPlot Review</title>",
            "<style>",
            "body{font-family:Arial,sans-serif;margin:32px;line-height:1.45}",
            "img{max-width:720px;border:1px solid #ddd}",
            "</style>",
            "</head>",
            "<body>",
            "<h1>SciPlot Review</h1>",
            f"<p>Route: <code>{escape(str(manifest.get('route')))}</code></p>",
            "<h2>Review Notes</h2>",
            "<ul>",
            *note_items,
            "</ul>",
            "<h2>Figures</h2>",
            "<ul>",
            *figure_items,
            "</ul>",
            "<h2>Revision</h2>",
            "<ul>",
            (
                f'<li><a href="{escape(str(revision_brief))}">Revision brief for assisted repair</a></li>'
                if isinstance(revision_brief, str) and revision_brief
                else "<li>No revision brief was generated.</li>"
            ),
            "</ul>",
            "</body>",
            "</html>",
        ]
    )
    (output_dir / "review.html").write_text(html + "\n", encoding="utf-8")


def _layout_quality_from_result(result: dict[str, Any]) -> dict[str, Any]:
    reports = result.get("qa_reports") if isinstance(result, dict) else None
    summaries: list[dict[str, Any]] = []
    issue_ids: list[str] = []
    autofixes: list[str] = []
    needs_ai_intervention = False
    if isinstance(reports, list):
        for report in reports:
            if not isinstance(report, dict):
                continue
            for issue in report.get("issues", []):
                if isinstance(issue, dict) and isinstance(issue.get("id"), str):
                    issue_ids.append(str(issue["id"]))
                    if issue.get("severity") == "critical":
                        needs_ai_intervention = True
            for item in report.get("autofixes_applied", []):
                if isinstance(item, str):
                    autofixes.append(item)
            summary = report.get("layout_summary")
            if isinstance(summary, dict):
                summaries.append(summary)
                if summary.get("needs_ai_intervention") is True:
                    needs_ai_intervention = True
    payload = {
        "review_mode": "structured_qa_only",
        "needs_ai_intervention": needs_ai_intervention,
        "issue_ids": sorted(set(issue_ids)),
        "autofixes_applied": sorted(set(autofixes)),
        "summaries": summaries,
    }
    split_plan = result.get("split_plan")
    if isinstance(split_plan, dict):
        payload["split_plan"] = json_safe(split_plan)
    auto_split = result.get("auto_split")
    if isinstance(auto_split, dict):
        payload["auto_split"] = json_safe(auto_split)
        if auto_split.get("applied") is True:
            payload["autofixes_applied"] = sorted(set([*payload["autofixes_applied"], "split_stacked_figure_auto"]))
    return payload


def _layout_summary_height_mm(layout_quality: dict[str, Any]) -> float | None:
    heights: list[float] = []
    summaries = layout_quality.get("summaries") if isinstance(layout_quality.get("summaries"), list) else []
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        for key in ("requested_size_mm", "figure_size_mm"):
            value = summary.get(key)
            if not isinstance(value, list | tuple) or len(value) < 2:
                continue
            try:
                heights.append(float(value[1]))
            except (TypeError, ValueError):
                continue
    return max(heights) if heights else None


def _auto_split_policy_for_result(
    *,
    request: dict[str, Any],
    template: str,
    layout_quality: dict[str, Any],
) -> dict[str, Any] | None:
    if isinstance(request.get("split_policy"), dict):
        return None
    if template not in SUPPORTED_SPLIT_TEMPLATES:
        return None
    issue_ids = layout_quality.get("issue_ids") if isinstance(layout_quality.get("issue_ids"), list) else []
    if "stack_peak_too_small" not in {str(item) for item in issue_ids}:
        return None
    height_mm = _layout_summary_height_mm(layout_quality)
    if height_mm is None or height_mm < STACKED_TALL_FIGURE_HEIGHT_MM:
        return None
    return dict(DEFAULT_STACK_SPLIT_POLICY)


_RHEOLOGY_METRIC_LABELS = {
    "storage_modulus": "Storage Modulus",
    "loss_modulus": "Loss Modulus",
    "loss_factor": "Loss Factor",
    "tan_delta": "Loss Factor",
    "complex_modulus": "Complex Modulus",
    "complex_viscosity": "Complex Viscosity",
}

_TENSILE_SUMMARY_FIGURES: tuple[dict[str, str], ...] = (
    {
        "id": "tensile_strength_by_sample",
        "metric": "strength_MPa",
        "label": "Tensile strength (MPa)",
        "unit": "MPa",
        "template": "bar",
    },
    {
        "id": "elongation_at_break_by_sample",
        "metric": ELONGATION_AT_BREAK_METRIC,
        "label": ELONGATION_AT_BREAK_LABEL,
        "unit": "%",
        "template": "bar",
    },
    {
        "id": "tensile_modulus_by_sample",
        "metric": "modulus_MPa",
        "label": "Tensile modulus (MPa)",
        "unit": "MPa",
        "template": "bar",
    },
)

_SHARED_FIGURE_STYLE_KEYS = {
    "size",
    "visual_theme_id",
    "style_preset",
    "palette_preset",
    "marker_alpha",
}


def _metric_token(value: object) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _sweep_prefix_for_request(request: dict[str, Any]) -> str | None:
    rule_id = str(request.get("rule_id") or "").strip()
    if rule_id == "rheology_frequency_sweep":
        return "freq"
    if rule_id == "rheology_temperature_sweep":
        return "temp"
    return None


def _sweep_metric_sources(
    source: Path,
    *,
    request: dict[str, Any],
    output_dir: Path,
) -> list[tuple[str, Path, dict[str, Any]]]:
    prefix = _sweep_prefix_for_request(request)
    if prefix is None or source.suffix.lower() not in {".xlsx", ".xls"}:
        return []
    frame = pd.read_excel(source, sheet_name=0, header=None)
    if frame.shape[0] < 4:
        return []
    headers = [str(item).strip() for item in frame.iloc[0].tolist()]
    samples = [str(item).strip() for item in frame.iloc[1].tolist()]
    units = [str(item).strip() for item in frame.iloc[2].tolist()]
    x_columns = [
        index
        for index, label in enumerate(headers)
        if _metric_token(label) in {"angularfrequency", "frequency", "temperature"}
    ]
    if not x_columns:
        return []
    metric_keys = [
        key
        for key, label in _RHEOLOGY_METRIC_LABELS.items()
        if key != "tan_delta" and any(_metric_token(header) == _metric_token(label) for header in headers)
    ]
    if prefix == "temp":
        study_model = request.get("study_model") if isinstance(request.get("study_model"), dict) else {}
        figure_queue = study_model.get("figure_queue") if isinstance(study_model.get("figure_queue"), list) else []
        queued_metrics = {
            str(item.get("metric") or item.get("y_metric") or "").strip()
            for item in figure_queue
            if isinstance(item, dict)
        }
        requested_metrics = {
            "loss_factor" if metric == "tan_delta" else metric
            for metric in queued_metrics
            if metric
        } or {"storage_modulus", "loss_factor"}
        metric_keys = [key for key in metric_keys if key in requested_metrics]
    sources_dir = output_dir / "processed" / "veusz_metric_sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    metric_sources: list[tuple[str, Path, dict[str, Any]]] = []
    for metric_key in metric_keys:
        metric_label = _RHEOLOGY_METRIC_LABELS[metric_key]
        metric_token = _metric_token(metric_label)
        columns: list[pd.Series] = []
        output_headers: list[str] = []
        output_units: list[str] = []
        output_samples: list[str] = []
        for block_index, x_column in enumerate(x_columns):
            next_x = x_columns[block_index + 1] if block_index + 1 < len(x_columns) else len(headers)
            y_column = next(
                (index for index in range(x_column + 1, next_x) if _metric_token(headers[index]) == metric_token),
                None,
            )
            if y_column is None:
                continue
            sample = samples[x_column] or samples[y_column] or f"Sample {block_index + 1}"
            columns.extend(
                [
                    frame.iloc[3:, x_column].reset_index(drop=True),
                    frame.iloc[3:, y_column].reset_index(drop=True),
                ]
            )
            output_headers.extend([headers[x_column], headers[y_column]])
            output_units.extend([units[x_column], units[y_column]])
            output_samples.extend([sample, sample])
        if not columns:
            continue
        metric_frame = pd.concat(columns, axis=1)
        metric_frame.columns = list(range(metric_frame.shape[1]))
        metric_frame = pd.concat(
            [
                pd.DataFrame([output_headers, output_samples, output_units]),
                metric_frame,
            ],
            ignore_index=True,
        )
        metric_source = sources_dir / f"{prefix}_{metric_key}.csv"
        metric_frame.to_csv(metric_source, header=False, index=False)
        metric_render_options: dict[str, Any] = {
            "x_metric": "temperature" if prefix == "temp" else "angular_frequency",
            "y_metric": metric_key,
            "y_label_override": RHEOLOGY_METRIC_AXIS_LABELS.get(metric_key, metric_label),
        }
        plotted_values = pd.to_numeric(metric_frame.iloc[3:, 1::2].stack(), errors="coerce").dropna()
        if prefix == "temp":
            metric_render_options["yscale"] = "log"
            if metric_key == "loss_factor":
                positive_values = plotted_values[plotted_values > 0]
                spans_two_decades = (
                    not positive_values.empty
                    and len(positive_values) == len(plotted_values)
                    and float(positive_values.max()) / float(positive_values.min()) >= 100.0
                )
                metric_render_options["yscale"] = "log" if spans_two_decades else "linear"
                if spans_two_decades:
                    metric_render_options["y_ticks"] = list(anchored_log_decade_ticks(positive_values))
        if prefix == "freq" and metric_key == "storage_modulus":
            if not plotted_values.empty and float(plotted_values.max()) <= 5e5:
                metric_render_options.update(
                    {
                        "y_max": 5e5,
                        "y_ticks": [1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0],
                    }
                )
        elif prefix == "freq" and metric_key in {"loss_factor", "complex_viscosity"}:
            metric_render_options["y_ticks"] = list(anchored_log_decade_ticks(plotted_values))
        metric_sources.append(
            (
                f"{prefix}_{metric_key}",
                metric_source,
                metric_render_options,
            )
        )
    return metric_sources


def _rename_metric_exports(
    payload: dict[str, Any],
    *,
    metric_id: str,
    figures_dir: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    outputs: list[str] = []
    exports: list[dict[str, Any]] = []
    for item in payload.get("exports", []):
        if not isinstance(item, dict):
            continue
        source_value = item.get("path")
        fmt = str(item.get("format") or "").strip().lower()
        if not isinstance(source_value, str) or not fmt:
            continue
        source = Path(source_value)
        if not source.exists():
            continue
        if fmt == "pdf":
            destination = figures_dir / f"{metric_id}.pdf"
        elif fmt in {"tiff", "tiff_300"}:
            destination = figures_dir / f"{metric_id}_300dpi.tiff"
        elif fmt in {"png", "png_300"}:
            destination = figures_dir / f"{metric_id}_300dpi.png"
        else:
            destination = figures_dir / f"{metric_id}{source.suffix}"
        shutil.copy2(source, destination)
        record = {**item, "source": str(source), "path": str(destination)}
        outputs.append(str(destination))
        exports.append(record)
    return outputs, exports


def _tensile_summary_sources(
    input_path: Path,
    *,
    request: dict[str, Any],
    output_dir: Path,
    options: dict[str, Any],
) -> list[tuple[str, Path, dict[str, Any]]]:
    if str(request.get("rule_id") or "") != "tensile_curve":
        return []
    summary_source = input_path.with_name(f"{input_path.stem}_summary.csv")
    if not summary_source.exists():
        return []
    summary = pd.read_csv(summary_source)
    if "sample" not in summary.columns:
        return []
    study_model = request.get("study_model") if isinstance(request.get("study_model"), dict) else {}
    figure_queue = study_model.get("figure_queue") if isinstance(study_model.get("figure_queue"), list) else []
    queued_ids = {
        str(item.get("id") or "").strip()
        for item in figure_queue
        if isinstance(item, dict)
    }
    queued_metrics = {
        str(item.get("metric") or item.get("y_metric") or "").strip()
        for item in figure_queue
        if isinstance(item, dict)
    }
    requested = [
        contract
        for contract in _TENSILE_SUMMARY_FIGURES
        if not figure_queue or contract["id"] in queued_ids or contract["metric"] in queued_metrics
    ]
    sample_order = [str(value) for value in study_model.get("sample_order", []) if str(value).strip()]
    observed_order = [str(value) for value in summary["sample"].dropna().drop_duplicates().tolist()]
    ordered_samples = [sample for sample in sample_order if sample in observed_order]
    ordered_samples.extend(sample for sample in observed_order if sample not in ordered_samples)
    if not ordered_samples:
        return []

    source_dir = output_dir / "processed" / "veusz_metric_sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    shared_style = {key: value for key, value in options.items() if key in _SHARED_FIGURE_STYLE_KEYS}
    metric_sources: list[tuple[str, Path, dict[str, Any]]] = []
    for contract in requested:
        metric = contract["metric"]
        if metric not in summary.columns:
            continue
        group_values = [
            pd.to_numeric(
                summary.loc[summary["sample"].astype(str) == sample, metric],
                errors="coerce",
            ).dropna().tolist()
            for sample in ordered_samples
        ]
        if not any(group_values):
            continue
        compact_axis = compact_linear_axis(
            value
            for values in group_values
            for value in values
        )
        rows: list[list[Any]] = [
            [contract["label"] for _sample in ordered_samples],
            [contract["unit"] for _sample in ordered_samples],
            list(ordered_samples),
        ]
        for row_index in range(max(len(values) for values in group_values)):
            rows.append(
                [values[row_index] if row_index < len(values) else "" for values in group_values]
            )
        metric_source = source_dir / f"{contract['id']}.csv"
        pd.DataFrame(rows).to_csv(metric_source, header=False, index=False)
        metric_options: dict[str, Any] = {
            **CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
            **shared_style,
            "legend_position": "none",
            "series_label_mode": "none",
            "x_label_override": "Sample",
            "y_label_override": contract["label"],
            "summary_statistic": "median_iqr",
            "template": contract["template"],
        }
        if compact_axis is not None:
            axis_values = (
                [0.0]
                + [value for values in group_values for value in values]
                if contract.get("template") == "bar"
                else [value for values in group_values for value in values]
            )
            bar_axis = compact_linear_axis(axis_values) if contract.get("template") == "bar" else compact_axis
            metric_options.update(
                {
                    "y_min": 0.0 if contract.get("template") == "bar" else compact_axis[0],
                    "y_max": bar_axis[1] if bar_axis is not None else compact_axis[1],
                    "y_ticks": list(bar_axis[2] if bar_axis is not None else compact_axis[2]),
                }
            )
        metric_sources.append(
            (
                contract["id"],
                metric_source,
                metric_options,
            )
        )
    return metric_sources


def _render_veusz_tensile_bundle(
    input_path: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    metric_sources = _tensile_summary_sources(
        input_path,
        request=request,
        output_dir=output_dir,
        options=options,
    )
    if not metric_sources:
        return None
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    curve_options = dict(options)
    curve_options.setdefault("legend_position", "auto")
    render_jobs: list[tuple[str, Path, str, dict[str, Any]]] = [
        ("stress_vs_strain", input_path, str(request.get("template") or "curve"), curve_options)
    ]
    render_jobs.extend(
        (metric_id, metric_source, str(metric_options.pop("template", "bar")), metric_options)
        for metric_id, metric_source, metric_options in metric_sources
    )
    combined_outputs: list[str] = []
    combined_exports: list[dict[str, Any]] = []
    combined_reports: list[dict[str, Any]] = []
    combined_documents: list[str] = []
    combined_specs: list[str] = []
    combined_terminal_requests: list[dict[str, Any]] = []
    for metric_id, metric_source, template, metric_options in render_jobs:
        metric_dir = figures_dir / f"_{metric_id}_render"
        payload = render_to_dir(
            metric_source,
            template=template,
            output_dir=metric_dir,
            options=metric_options,
            export_formats=export_formats,
            request_context={
                **request,
                "explicit_render_option_keys": request.get(
                    "explicit_render_option_keys", []
                ),
            },
        )
        outputs, exports = _rename_metric_exports(payload, metric_id=metric_id, figures_dir=figures_dir)
        combined_outputs.extend(outputs)
        combined_exports.extend(exports)
        metric_worker = figures_dir / "_veusz" / metric_id
        if metric_worker.exists():
            shutil.rmtree(metric_worker)
        source_worker = metric_dir / "_veusz"
        if source_worker.exists():
            metric_worker.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_worker, metric_worker)
        mapped_documents: list[str] = []
        for item in payload.get("veusz_documents", []):
            source_path = Path(str(item))
            try:
                destination = metric_worker / source_path.relative_to(source_worker)
            except ValueError:
                continue
            if destination.exists():
                mapped_documents.append(str(destination))
        mapped_specs: list[str] = []
        for item in payload.get("veusz_specs", []):
            source_path = Path(str(item))
            try:
                destination = metric_worker / source_path.relative_to(source_worker)
            except ValueError:
                continue
            if destination.exists():
                mapped_specs.append(str(destination))
        combined_documents.extend(mapped_documents)
        combined_specs.extend(mapped_specs)
        combined_terminal_requests.extend(
            item
            for item in payload.get("terminal_render_requests", [])
            if isinstance(item, dict)
        )
        for report in payload.get("qa_reports", []):
            if not isinstance(report, dict):
                continue
            copied_report = dict(report)
            summary = report.get("layout_summary")
            if isinstance(summary, dict):
                copied_summary = dict(summary)
                if mapped_documents:
                    copied_summary["document"] = mapped_documents[0]
                copied_summary["outputs"] = list(outputs)
                copied_report["layout_summary"] = copied_summary
            combined_reports.append(copied_report)
        if metric_dir.exists():
            shutil.rmtree(metric_dir)
    return {
        "kind": "sciplot_render_result",
        "template": str(request.get("template") or "curve"),
        "input": str(input_path),
        "sheet": 0,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "export_formats": list(export_formats or DEFAULT_EXPORT_FORMATS_POLICY),
        "exports": combined_exports,
        "outputs": combined_outputs,
        "qa_reports": combined_reports,
        "veusz_documents": combined_documents,
        "veusz_specs": combined_specs,
        "terminal_render_requests": combined_terminal_requests,
        "multi_metric_bundle": {
            "kind": "tensile_curve_and_summary_bundle",
            "metric_ids": [metric_id for metric_id, _source, _template, _options in render_jobs],
        },
    }


def _render_veusz_sweep_bundle(
    input_path: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    metric_sources = _sweep_metric_sources(input_path, request=request, output_dir=output_dir)
    if not metric_sources:
        return None
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    combined_outputs: list[str] = []
    combined_exports: list[dict[str, Any]] = []
    combined_reports: list[dict[str, Any]] = []
    combined_documents: list[str] = []
    combined_specs: list[str] = []
    combined_terminal_requests: list[dict[str, Any]] = []
    for metric_id, metric_source, metric_options in metric_sources:
        metric_dir = figures_dir / f"_{metric_id}_render"
        metric_render_options = {**options, **metric_options}
        payload = render_to_dir(
            metric_source,
            template=str(request.get("template") or "point_line"),
            output_dir=metric_dir,
            options=metric_render_options,
            export_formats=export_formats,
            request_context={
                **request,
                "explicit_render_option_keys": request.get(
                    "explicit_render_option_keys", []
                ),
            },
        )
        outputs, exports = _rename_metric_exports(payload, metric_id=metric_id, figures_dir=figures_dir)
        combined_outputs.extend(outputs)
        combined_exports.extend(exports)
        metric_worker = figures_dir / "_veusz" / metric_id
        if metric_worker.exists():
            shutil.rmtree(metric_worker)
        source_worker = metric_dir / "_veusz"
        if source_worker.exists():
            metric_worker.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_worker, metric_worker)
        mapped_documents: list[str] = []
        for item in payload.get("veusz_documents", []):
            source_path = Path(str(item))
            try:
                destination = metric_worker / source_path.relative_to(source_worker)
            except ValueError:
                continue
            if destination.exists():
                mapped_documents.append(str(destination))
        mapped_specs: list[str] = []
        for item in payload.get("veusz_specs", []):
            source_path = Path(str(item))
            try:
                destination = metric_worker / source_path.relative_to(source_worker)
            except ValueError:
                continue
            if destination.exists():
                mapped_specs.append(str(destination))
        combined_documents.extend(mapped_documents)
        combined_specs.extend(mapped_specs)
        combined_terminal_requests.extend(
            item
            for item in payload.get("terminal_render_requests", [])
            if isinstance(item, dict)
        )
        for report in payload.get("qa_reports", []):
            if not isinstance(report, dict):
                continue
            copied_report = dict(report)
            summary = report.get("layout_summary")
            if isinstance(summary, dict):
                copied_summary = dict(summary)
                if mapped_documents:
                    copied_summary["document"] = mapped_documents[0]
                copied_summary["outputs"] = list(outputs)
                copied_report["layout_summary"] = copied_summary
            combined_reports.append(copied_report)
        if metric_dir.exists():
            shutil.rmtree(metric_dir)
    return {
        "kind": "sciplot_render_result",
        "template": str(request.get("template") or "point_line"),
        "input": str(input_path),
        "sheet": 0,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "export_formats": list(export_formats or DEFAULT_EXPORT_FORMATS_POLICY),
        "exports": combined_exports,
        "outputs": combined_outputs,
        "qa_reports": combined_reports,
        "veusz_documents": combined_documents,
        "veusz_specs": combined_specs,
        "terminal_render_requests": combined_terminal_requests,
        "multi_metric_bundle": {
            "kind": "rheology_sweep_metric_bundle",
            "metric_ids": [metric_id for metric_id, _source, _options in metric_sources],
        },
    }


def _render_with_auto_split(
    input_path: Path,
    *,
    template: str,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any]:
    figures_dir = output_dir / "figures"
    tensile_bundle = _render_veusz_tensile_bundle(
        input_path,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
    )
    if tensile_bundle is not None:
        return tensile_bundle
    bundle = _render_veusz_sweep_bundle(
        input_path,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
    )
    if bundle is not None:
        return bundle
    result = render_to_dir(
        input_path,
        template=template,
        output_dir=figures_dir,
        options=options,
        export_formats=export_formats,
        split_policy=request.get("split_policy"),
        request_context=request,
    )
    layout_quality = _layout_quality_from_result(result)
    policy = _auto_split_policy_for_result(request=request, template=template, layout_quality=layout_quality)
    if policy is None:
        return result

    if figures_dir.exists():
        shutil.rmtree(figures_dir)
    split_options = _compact_auto_split_options(options)
    split_result = render_to_dir(
        input_path,
        template=template,
        output_dir=figures_dir,
        options=split_options,
        export_formats=export_formats,
        split_policy=policy,
        request_context=request,
    )
    split_result["auto_split"] = {
        "applied": True,
        "trigger_issue": "stack_peak_too_small",
        "reason": "tall_stacked_peak_too_small",
        "policy": json_safe(policy),
        "original_layout_quality": json_safe(layout_quality),
    }
    return split_result


def _compact_auto_split_options(options: dict[str, Any]) -> dict[str, Any]:
    updated = dict(options)
    size = str(updated.get("size") or "").strip().lower()
    if size.endswith("x110"):
        updated["size"] = f"{size.removesuffix('x110')}x55"
    return updated


def _write_one_step_status(output_dir: Path, payload: dict[str, Any]) -> None:
    (output_dir / "one_step_status.json").write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _next_run_dir(project_dir: Path) -> Path:
    runs_dir = project_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate = runs_dir / f"run_{index:03d}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            index += 1
        else:
            return candidate


def _one_step_project_dir(input_path: Path, output_root: Path, project_name: str | None) -> Path:
    name = project_name or (input_path.stem if input_path.is_file() else input_path.name) or "sciplot_project"
    return output_root / slug(name)


def _write_revision_brief(output_dir: Path, *, manifest: dict[str, Any]) -> str:
    figures = [Path(path) for path in manifest.get("figures", []) if isinstance(path, str)]
    figure_lines = []
    for figure in figures:
        rel = figure.relative_to(output_dir) if figure.exists() and figure.is_relative_to(output_dir) else figure
        figure_lines.append(f"- `{rel}`")
    semantic = manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
    request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    size = ""
    render_options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
    if isinstance(render_options.get("size"), str):
        size = str(render_options["size"])
    layout_quality = manifest.get("layout_quality") if isinstance(manifest.get("layout_quality"), dict) else {}
    layout_issue_ids = layout_quality.get("issue_ids") if isinstance(layout_quality.get("issue_ids"), list) else []
    layout_autofixes = (
        layout_quality.get("autofixes_applied") if isinstance(layout_quality.get("autofixes_applied"), list) else []
    )
    quality_actions = build_quality_actions(
        issue_ids=[str(item) for item in layout_issue_ids],
        autofixes_applied=[str(item) for item in layout_autofixes],
        layout_summaries=layout_quality.get("summaries") if isinstance(layout_quality.get("summaries"), list) else [],
    )
    quality_action_lines = [
        f"- `{action.get('status', 'suggested')}` {action.get('label', action.get('id', 'Quality action'))}: "
        f"{action.get('reason', '')}"
        for action in quality_actions
    ]
    split_plan = layout_quality.get("split_plan") if isinstance(layout_quality.get("split_plan"), dict) else {}
    if split_plan:
        split_policy = split_plan.get("policy") if isinstance(split_plan.get("policy"), dict) else {}
        split_mode = split_policy.get("mode", "")
        split_line = (
            f"- Split: applied=`{bool(split_plan.get('applied'))}`, "
            f"chunks=`{split_plan.get('chunk_count', 0)}`, "
            f"policy=`{split_mode}`"
        )
    else:
        split_line = "- Split: none"
    lines = [
        "# SciPlot Revision Brief",
        "",
        "Use this brief for optional assisted repair of the SciPlot rule, recipe, style, or cleanup path.",
        "",
        "## Run",
        "",
        f"- Output: `{output_dir}`",
        f"- Request: `{manifest.get('request_path')}`",
        f"- Route: `{manifest.get('route')}`",
        f"- Rule: `{semantic.get('rule_id') or ''}`",
        f"- Template: `{manifest.get('result', {}).get('template') or ''}`",
        f"- Size: `{size}`" if size else "- Size: not specified in request",
        f"- QA: `{manifest.get('qa', {}).get('status') or 'unknown'}`",
        f"- Layout review mode: `{layout_quality.get('review_mode') or 'structured_qa_only'}`",
        f"- Assisted repair suggested: `{bool(layout_quality.get('needs_ai_intervention', False))}`",
        "",
        "## Figures",
        "",
        *(figure_lines or ["- No figures were recorded."]),
        "",
        "## Layout QA",
        "",
        f"- Issues: `{', '.join(str(item) for item in layout_issue_ids) if layout_issue_ids else 'none'}`",
        f"- Autofixes: `{', '.join(str(item) for item in layout_autofixes) if layout_autofixes else 'none'}`",
        split_line,
        "- Review source: structured QA summaries in `manifest.json`; image review is only needed for "
        "QA failures or explicit visual review requests.",
        "",
        "## Quality Actions",
        "",
        *(quality_action_lines or ["- No QA repair actions were suggested."]),
        "",
        "## Assisted Repair Request",
        "",
        "请按这些修改意见调整 SciPlot 规则、样式或数据整理路径，然后重新导出：",
        "",
        "- 图类型/数据识别：",
        "- 坐标轴标题和单位：",
        "- x/y 轴范围、log、reverse、刻度数量：",
        "- legend 名称、顺序、位置：",
        "- 字体、线宽、marker、颜色：",
        "- 其他：",
    ]
    path = output_dir / "revision_brief.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "revision_brief.md"


def _update_intake_project_after_run(request_path: Path, manifest: dict[str, Any]) -> None:
    project_dir = request_path.parent
    intake_manifest_path = project_dir / "intake_manifest.json"
    if not intake_manifest_path.exists():
        return
    project_manifest = json.loads(intake_manifest_path.read_text(encoding="utf-8"))
    project_manifest["last_run"] = {
        "completed_at": manifest["created_at"],
        "output": manifest["output"],
        "figures": manifest["figures"],
        "analysis_metrics": manifest.get("result", {}).get("analysis_metrics", []),
        "qa": manifest.get("qa", {}),
        "revision_brief": manifest.get("revision_brief"),
        "package_contract": manifest.get("package_contract", {}),
        "delivery_package": manifest.get("delivery_package", {}),
        "layout_quality": manifest.get("layout_quality", {}),
        "one_step": manifest.get("one_step", {}),
        "publication_intent": manifest.get("publication_intent", {}),
        "transform_ledger": manifest.get("transform_ledger", {}),
        "journal_profile": manifest.get("journal_profile", {}),
        "publication_qa": manifest.get("publication_qa", {}),
    }
    if isinstance(manifest.get("study_model"), dict):
        project_manifest["study_model"] = manifest["study_model"]
        project_manifest["last_run"]["study_model"] = manifest["study_model"]
    if isinstance(manifest.get("package_contract"), dict):
        project_manifest["package_contract"] = manifest["package_contract"]
    if isinstance(manifest.get("layout_quality"), dict):
        project_manifest["layout_quality"] = manifest["layout_quality"]
    if isinstance(manifest.get("delivery_package"), dict):
        project_manifest["delivery_package"] = manifest["delivery_package"]
    if isinstance(manifest.get("one_step"), dict):
        project_manifest["one_step"] = manifest["one_step"]
    for key in ("publication_intent", "transform_ledger", "journal_profile", "publication_qa"):
        if isinstance(manifest.get(key), dict):
            project_manifest[key] = manifest[key]
    intake_manifest_path.write_text(
        json.dumps(json_safe(project_manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    sciplot_paths = sorted(project_dir.glob("*.sciplot.json"))
    for path in sciplot_paths:
        path.write_text(
            json.dumps(json_safe(project_manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    from sciplot_core.intake import _prepare_studio_project_package, refresh_intake_project_zip

    _prepare_studio_project_package(project_dir)
    refresh_intake_project_zip(project_dir)


def run_request(request_path: Path) -> dict[str, Any]:
    request_path = request_path.expanduser().resolve()
    source_request = _load_request(request_path)
    base_dir = request_path.parent
    output_dir = _resolve_request_path(source_request.get("output"), base_dir=base_dir, field="output")
    with _managed_output_transaction(output_dir):
        return _run_request_in_managed_output(
            request_path=request_path,
            source_request=source_request,
            base_dir=base_dir,
            output_dir=output_dir,
        )


def _run_request_in_managed_output(
    *,
    request_path: Path,
    source_request: dict[str, Any],
    base_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    original_input_path = _resolve_request_path(source_request.get("input"), base_dir=base_dir, field="input")
    mapped_request, mapping_application = resolve_data_mapping_request(
        source_request,
        base_dir=base_dir,
    )
    request, cleanup_application = consume_ready_cleanup_result(
        mapped_request,
        output_dir=output_dir,
        request_path=request_path,
    )
    if mapping_application is not None and cleanup_application is not None:
        raise ValueError(
            "A confirmed DataMappingProposal and assisted cleanup cannot both "
            "replace the same input in one run."
        )
    input_path = _resolve_request_path(request.get("input"), base_dir=base_dir, field="input")
    raw_archive = _archive_raw_input(
        original_input_path if mapping_application is not None else input_path,
        output_dir,
    )
    if cleanup_application is not None and original_input_path.resolve() != input_path.resolve():
        raw_archive["pre_cleanup_input"] = _archive_raw_input(original_input_path, output_dir)
    (output_dir / "request_snapshot.json").write_text(
        json.dumps(request, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    requested_rule_id = request.get("rule_id") if isinstance(request.get("rule_id"), str) else None
    semantic = classify_source(input_path, requested_rule_id=requested_rule_id)
    study_model = study_model_from_request(request=request, semantic=semantic, input_path=input_path)
    publication_intent = build_publication_intent(
        study_model,
        request=request,
        existing=request.get("publication_intent") if isinstance(request.get("publication_intent"), dict) else None,
    )
    publication_profile = get_publication_profile(publication_intent["target_profile_id"])
    transform_steps: list[dict[str, Any]] = [
        deepcopy(step)
        for step in (
            mapping_application.get("transform_steps", [])
            if mapping_application is not None
            else []
        )
        if isinstance(step, dict)
    ]
    if cleanup_application is not None:
        transform_steps.append(
            build_transform_step(
                step_id="assisted_cleanup",
                operation="confirmed_cleanup",
                input_path=original_input_path,
                output_path=input_path,
                implementation_ref="sciplot_core.assisted_cleanup.consume_ready_cleanup_result",
                parameters={
                    "cleanup_result": cleanup_application["cleanup_result"],
                    "mapping_proposal": cleanup_application["mapping_proposal"],
                    "request_patch": cleanup_application["request_patch"],
                    "human_confirmed": True,
                },
            )
        )
    layout_policy = layout_policy_for_semantic(semantic, template=request.get("template"))
    final_recipe: str | None = None

    use_auto = request.get("recipe") == "auto" or (not request.get("recipe") and not request.get("template"))
    pending_rule_blocked = semantic.get("rule_readiness") == "pending"
    if semantic.get("needs_ai_intervention") and (use_auto or pending_rule_blocked):
        intervention = build_intervention_request(
            input_path=input_path,
            output_dir=output_dir,
            semantic=semantic,
            request=request,
        )
        (output_dir / "intervention_request.json").write_text(
            json.dumps(json_safe(intervention), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        write_cleanup_request(
            output_dir,
            input_path=input_path,
            reason=str(intervention.get("category") or "semantic_intervention"),
            semantic=semantic,
            request=request,
            intervention_request=output_dir / "intervention_request.json",
            provider="codex",
        )
        one_step_status = build_one_step_project(
            input_path=input_path,
            request_path=request_path,
            request=request,
            semantic=semantic,
            raw_archive=raw_archive,
            study_model=study_model,
            layout_policy=layout_policy,
            layout_quality={},
            qa=None,
            delivery_package=None,
            intervention_request=intervention,
        )
        _write_one_step_status(output_dir, one_step_status)
        if pending_rule_blocked:
            failure = f"Requested material rule `{semantic.get('rule_id')}` is pending fixture-backed acceptance."
        else:
            failure = "SciPlot could not auto-detect this input."
        raise ValueError(f"{failure} Intervention request written to {output_dir / 'intervention_request.json'}.")
    plotted_data_source: Path
    if use_auto:
        route = "auto"
        final_recipe = semantic.get("recommended_recipe")
        replicate_policy = (
            study_model.get("replicate_policy")
            if isinstance(study_model.get("replicate_policy"), dict)
            else {}
        )
        effective_replicate_mode = request.get("replicate_mode") or replicate_policy.get("mode")
        prepared = prepare_semantic_source(
            input_path,
            output_dir=output_dir,
            semantic=semantic,
            curation_path=_resolve_optional_request_path(request.get("curation"), base_dir=base_dir),
            series_order=request.get("series_order"),
            column_confirmations=request.get("column_confirmations"),
            replicate_mode=effective_replicate_mode,
        )
        transform_steps.extend(step for step in prepared.get("transform_steps", []) if isinstance(step, dict))
        render_options = dict(semantic.get("render_options") or {})
        request_render_options = request.get("render_options")
        if isinstance(request_render_options, dict):
            render_options.update(request_render_options)
        if semantic.get("rule_id") == "rheology_stress_relaxation":
            render_options.setdefault("x_label_override", "Time (s)")
            render_options.setdefault("y_label_override", "Normalized stress ($\\sigma/\\sigma_0$)")
        template = request.get("template") or semantic["template"]
        effective_render_request = {
            **request,
            "rule_id": semantic.get("rule_id"),
            "study_model": study_model,
            "template": template,
        }
        result = _render_with_auto_split(
            Path(str(prepared["source"])),
            template=str(template),
            output_dir=output_dir,
            options=render_options,
            export_formats=request.get("exports"),
            request=effective_render_request,
        )
        plotted_data_source = Path(str(prepared["source"]))
        processed_source = Path(str(prepared["processed_source"])) if prepared["processed_source"] else None
        analysis_metrics = compute_analysis_metrics(
            source_path=input_path,
            processed_source=processed_source,
            semantic=semantic,
            output_dir=output_dir,
        )
        result = {
            **result,
            "semantic_family": semantic["semantic_family"],
            "rule_id": semantic.get("rule_id"),
            "final_recipe": final_recipe,
            "processed": prepared["processed"],
            "processed_source": prepared["processed_source"],
            "analysis_metrics": analysis_metrics,
        }
        _write_auto_report(
            output_dir,
            request=request,
            result=result,
            semantic=semantic,
            final_recipe=final_recipe,
        )
    elif request.get("recipe"):
        route = "recipe"
        final_recipe = str(request["recipe"])
        result = run_recipe(
            str(request["recipe"]),
            input_path,
            output_dir=output_dir,
            options=_request_options(request),
        )
        plotted_data_source = Path(
            str(result.get("processed_source") or input_path)
        )
        transform_steps.extend(step for step in result.get("transform_steps", []) if isinstance(step, dict))
    else:
        route = "render"
        template = request.get("template")
        if not isinstance(template, str) or not template.strip():
            raise ValueError("Plot requests without `recipe` must define a non-empty `template`.")
        render_options = request.get("render_options")
        result = _render_with_auto_split(
            input_path,
            template=template,
            output_dir=output_dir,
            options=render_options if isinstance(render_options, dict) else {},
            export_formats=request.get("exports"),
            request=request,
        )
        plotted_data_source = input_path
        _write_render_report(output_dir, request=request, result=result)

    result = _bind_result_data_snapshots(
        result,
        plotted_source=plotted_data_source,
        mapping_application=mapping_application,
        request=request,
    )
    transform_ledger = build_transform_ledger(
        study_model,
        request=request,
        input_path=input_path,
        steps=transform_steps,
        existing=request.get("transform_ledger") if isinstance(request.get("transform_ledger"), dict) else None,
    )
    publication_intent = link_intent_to_transform_ledger(publication_intent, transform_ledger)
    study_model["publication_intent_ref"] = "publication_intent.json"
    publication_artifacts = write_publication_artifacts(
        output_dir,
        publication_intent=publication_intent,
        transform_ledger=transform_ledger,
        publication_profile=publication_profile,
    )
    qa = run_qa(
        output_dir,
        publication_profile=publication_profile,
        strict_publication=bool(request.get("publication_strict")),
        veusz_documents=[Path(value) for value in result.get("veusz_documents", []) if isinstance(value, str)],
    )
    publication_qa = qa.get("publication") if isinstance(qa.get("publication"), dict) else {}
    publication_artifacts = write_publication_artifacts(
        output_dir,
        publication_intent=publication_intent,
        transform_ledger=transform_ledger,
        publication_profile=publication_profile,
        publication_qa=publication_qa,
    )
    figures = _figures_from_result(result)
    analysis_metrics = result.get("analysis_metrics") if isinstance(result.get("analysis_metrics"), list) else []
    study_model = attach_run_artifacts_to_study_model(
        study_model,
        output_dir=output_dir,
        figures=figures,
        analysis_metrics=analysis_metrics,
        qa=qa,
    )
    manifest = {
        "kind": "sciplot_run",
        "created_at": datetime.now(UTC).isoformat(),
        "request_path": str(request_path),
        "request": json_safe(request),
        "source_request": json_safe(source_request),
        "data_mapping_application": (
            json_safe(mapping_application)
            if mapping_application is not None
            else None
        ),
        "cleanup_application": json_safe(cleanup_application) if cleanup_application is not None else None,
        "route": route,
        "semantic": json_safe(semantic),
        "final_recipe": final_recipe,
        "input": str(input_path),
        "raw_archive": json_safe(raw_archive),
        "output": str(output_dir),
        "figures": figures,
        "result": json_safe(result),
        "study_model": json_safe(study_model),
        "publication_intent": json_safe(publication_intent),
        "transform_ledger": json_safe(transform_ledger),
        "journal_profile": json_safe(publication_profile),
        "publication_qa": json_safe(publication_qa),
        "publication_artifacts": json_safe(publication_artifacts),
        "qa": qa,
        "render_engine": result.get("render_engine") or "veusz",
        "qa_target": result.get("qa_target") or "veusz_export",
        "veusz_documents": result.get("veusz_documents", []),
        "veusz_specs": result.get("veusz_specs", []),
        "layout_policy": layout_policy_payload(layout_policy),
        "operation_mode": normal_mode_payload(route=route),
    }
    manifest["layout_quality"] = _layout_quality_from_result(manifest["result"])
    manifest["revision_brief"] = _write_revision_brief(output_dir, manifest=manifest)
    _write_review_html(output_dir, manifest=manifest)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["package_contract"] = build_output_package_contract(output_dir, manifest=manifest)
    manifest["delivery_package"] = build_delivery_package(output_dir, manifest=manifest)
    manifest["one_step"] = build_one_step_project(
        input_path=input_path,
        request_path=request_path,
        request=request,
        semantic=semantic,
        raw_archive=raw_archive,
        study_model=study_model,
        layout_policy=layout_policy,
        layout_quality=manifest["layout_quality"],
        qa=qa,
        delivery_package=manifest["delivery_package"],
    )
    manifest.update(
        build_publish_state(
            qa=qa,
            package_contract=manifest["package_contract"],
            delivery_package=manifest["delivery_package"],
            prerequisite_state=manifest["one_step"]["state"],
        )
    )
    _write_one_step_status(output_dir, manifest["one_step"])
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _update_intake_project_after_run(request_path, manifest)
    return manifest


def run_one_step(
    input_path: Path,
    *,
    output_root: Path,
    project_name: str | None = None,
    delivery_root: Path | None = None,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    project_dir = _one_step_project_dir(input_path, output_root, project_name)
    project_dir.mkdir(parents=True, exist_ok=True)
    run_dir = _next_run_dir(project_dir)
    request_path = project_dir / "plot_request.json"
    request = {
        "recipe": "auto",
        "input": str(input_path),
        "output": str(run_dir),
        "exports": list(DEFAULT_EXPORT_FORMATS_POLICY),
        "render_options": normalize_render_options(DEFAULT_RENDER_OPTIONS),
    }
    if delivery_root is not None:
        request["delivery_output"] = str(delivery_root.expanduser().resolve())
    request_path.write_text(json.dumps(json_safe(request), indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        manifest = run_request(request_path)
    except ValueError as exc:
        status_path = run_dir / "one_step_status.json"
        if not status_path.exists():
            raise
        status = json.loads(status_path.read_text(encoding="utf-8"))
        return {
            "kind": "sciplot_one_step_result",
            "status": status.get("state") or "needs_rule_repair",
            "project_dir": str(project_dir),
            "request_path": str(request_path),
            "run_output": str(run_dir),
            "one_step": status,
            "error": str(exc),
        }
    return {
        "kind": "sciplot_one_step_result",
        "status": manifest.get("state") or "needs_rule_repair",
        "project_dir": str(project_dir),
        "request_path": str(request_path),
        "run_output": str(run_dir),
        "one_step": manifest.get("one_step", {}),
        "manifest": manifest,
    }


__all__ = ["run_one_step", "run_request"]
