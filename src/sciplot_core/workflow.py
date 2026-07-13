from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import slug, unique_path
from sciplot_core.assisted_cleanup import (
    CLEANUP_REQUEST_FILENAME,
    consume_ready_cleanup_result,
    write_cleanup_request,
)
from sciplot_core.delivery import build_delivery_package
from sciplot_core.materials_rules import compute_analysis_metrics
from sciplot_core.one_step import build_one_step_project, build_quality_actions
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
    DEFAULT_RENDER_OPTIONS,
    DELIVERY_DIR,
    RHEOLOGY_METRIC_AXIS_LABELS,
    anchored_log_decade_ticks,
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
from sciplot_core.qa import run_qa
from sciplot_core.render import json_safe, render_to_dir
from sciplot_core.semantic import build_intervention_request, classify_source, prepare_semantic_source
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


def _clear_managed_artifacts(output_dir: Path) -> None:
    for folder in ("processed", "figures", "tables", "raw", DELIVERY_DIR):
        path = output_dir / folder
        if path.exists():
            shutil.rmtree(path)
    for filename in (
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
    ):
        path = output_dir / filename
        if path.exists():
            path.unlink()


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
        metric_keys = [key for key in metric_keys if key in {"storage_modulus", "complex_viscosity"}] or metric_keys
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
                pd.DataFrame([output_headers, output_units, output_samples]),
                metric_frame,
            ],
            ignore_index=True,
        )
        metric_source = sources_dir / f"{prefix}_{metric_key}.csv"
        metric_frame.to_csv(metric_source, header=False, index=False)
        metric_render_options: dict[str, Any] = {
            "x_metric": "temperature" if prefix == "temp" else "angular_frequency",
            "y_metric": metric_key,
            "y_label_override": (
                RHEOLOGY_METRIC_AXIS_LABELS.get(metric_key, metric_label) if prefix == "freq" else metric_label
            ),
        }
        plotted_values = pd.to_numeric(metric_frame.iloc[3:, 1::2].stack(), errors="coerce").dropna()
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
    for metric_id, metric_source, metric_options in metric_sources:
        metric_dir = figures_dir / f"_{metric_id}_render"
        metric_render_options = {**options, **metric_options}
        payload = render_to_dir(
            metric_source,
            template=str(request.get("template") or "point_line"),
            output_dir=metric_dir,
            options=metric_render_options,
            export_formats=export_formats,
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
        if not candidate.exists():
            return candidate
        index += 1


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
    original_input_path = _resolve_request_path(source_request.get("input"), base_dir=base_dir, field="input")
    output_dir = _resolve_request_path(source_request.get("output"), base_dir=base_dir, field="output")
    output_dir.mkdir(parents=True, exist_ok=True)
    request, cleanup_application = consume_ready_cleanup_result(
        source_request,
        output_dir=output_dir,
        request_path=request_path,
    )
    input_path = _resolve_request_path(request.get("input"), base_dir=base_dir, field="input")
    _clear_managed_artifacts(output_dir)
    raw_archive = _archive_raw_input(input_path, output_dir)
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
    transform_steps: list[dict[str, Any]] = []
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
    if use_auto:
        route = "auto"
        final_recipe = semantic.get("recommended_recipe")
        prepared = prepare_semantic_source(
            input_path,
            output_dir=output_dir,
            semantic=semantic,
            curation_path=_resolve_optional_request_path(request.get("curation"), base_dir=base_dir),
            series_order=request.get("series_order"),
            column_confirmations=request.get("column_confirmations"),
            replicate_mode=request.get("replicate_mode"),
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
        _write_render_report(output_dir, request=request, result=result)

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
        delivery_package=None,
    )
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
    _write_one_step_status(output_dir, manifest["one_step"])
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _update_intake_project_after_run(request_path, manifest)
    return manifest


def run_one_step(
    input_path: Path,
    *,
    output_root: Path,
    project_name: str | None = None,
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
        "render_options": dict(DEFAULT_RENDER_OPTIONS),
    }
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
        "status": manifest.get("one_step", {}).get("state") or "ready",
        "project_dir": str(project_dir),
        "request_path": str(request_path),
        "run_output": str(run_dir),
        "one_step": manifest.get("one_step", {}),
        "manifest": manifest,
    }


__all__ = ["run_one_step", "run_request"]
