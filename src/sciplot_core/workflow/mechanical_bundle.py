"""Materialize and render mechanical curve and summary figures."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.materials_rules import (
    ELONGATION_AT_BREAK_LABEL,
    ELONGATION_AT_BREAK_METRIC,
)
from sciplot_core.policy import (
    CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
    DEFAULT_EXPORT_FORMATS_POLICY,
    compact_linear_axis,
)
from sciplot_core.render import render_to_dir

from sciplot_core.workflow.bundle_exports import (
    _SHARED_FIGURE_STYLE_KEYS,
    _rename_metric_exports,
)

_MECHANICAL_FIGURE_CONTRACTS: dict[str, dict[str, Any]] = {
    "tensile_curve": {
        "curve_id": "stress_vs_strain",
        "summaries": (
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
        ),
    },
    "compression_curve": {
        "curve_id": "compressive_stress_vs_strain",
        "summaries": (
            {
                "id": "compressive_strength_by_sample",
                "metric": "compressive_strength_MPa",
                "label": "Compressive strength (MPa)",
                "unit": "MPa",
                "template": "bar",
            },
        ),
    },
    "flexural_curve": {
        "curve_id": "flexural_stress_vs_strain",
        "summaries": (
            {
                "id": "flexural_strength_by_sample",
                "metric": "flexural_strength_MPa",
                "label": "Flexural strength (MPa)",
                "unit": "MPa",
                "template": "bar",
            },
        ),
    },
}


def _mechanical_summary_sources(
    input_path: Path,
    *,
    request: dict[str, Any],
    output_dir: Path,
    options: dict[str, Any],
) -> list[tuple[str, Path, dict[str, Any]]]:
    rule_id = str(request.get("rule_id") or "")
    figure_contract = _MECHANICAL_FIGURE_CONTRACTS.get(rule_id)
    if figure_contract is None:
        return []
    summary_source = input_path.with_name(f"{input_path.stem}_summary.csv")
    if not summary_source.exists():
        return []
    summary = pd.read_csv(summary_source)
    if "sample" not in summary.columns:
        return []
    study_model = (
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {}
    )
    figure_queue = (
        study_model.get("figure_queue")
        if isinstance(study_model.get("figure_queue"), list)
        else []
    )
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
        for contract in figure_contract["summaries"]
        if not figure_queue
        or contract["id"] in queued_ids
        or contract["metric"] in queued_metrics
    ]
    sample_order = [
        str(value)
        for value in study_model.get("sample_order", [])
        if str(value).strip()
    ]
    observed_order = [
        str(value) for value in summary["sample"].dropna().drop_duplicates().tolist()
    ]
    ordered_samples = [sample for sample in sample_order if sample in observed_order]
    ordered_samples.extend(
        sample for sample in observed_order if sample not in ordered_samples
    )
    if not ordered_samples:
        return []

    source_dir = output_dir / "processed" / "veusz_metric_sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    shared_style = {
        key: value for key, value in options.items() if key in _SHARED_FIGURE_STYLE_KEYS
    }
    metric_sources: list[tuple[str, Path, dict[str, Any]]] = []
    for contract in requested:
        metric = contract["metric"]
        if metric not in summary.columns:
            continue
        group_values = [
            pd.to_numeric(
                summary.loc[summary["sample"].astype(str) == sample, metric],
                errors="coerce",
            )
            .dropna()
            .tolist()
            for sample in ordered_samples
        ]
        if not any(group_values):
            continue
        compact_axis = compact_linear_axis(
            value for values in group_values for value in values
        )
        rows: list[list[Any]] = [
            [contract["label"] for _sample in ordered_samples],
            [contract["unit"] for _sample in ordered_samples],
            list(ordered_samples),
        ]
        for row_index in range(max(len(values) for values in group_values)):
            rows.append(
                [
                    values[row_index] if row_index < len(values) else ""
                    for values in group_values
                ]
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
                [0.0] + [value for values in group_values for value in values]
                if contract.get("template") == "bar"
                else [value for values in group_values for value in values]
            )
            bar_axis = (
                compact_linear_axis(axis_values)
                if contract.get("template") == "bar"
                else compact_axis
            )
            metric_options.update(
                {
                    "y_min": 0.0
                    if contract.get("template") == "bar"
                    else compact_axis[0],
                    "y_max": bar_axis[1] if bar_axis is not None else compact_axis[1],
                    "y_ticks": list(
                        bar_axis[2] if bar_axis is not None else compact_axis[2]
                    ),
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


def _render_veusz_mechanical_bundle(
    input_path: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    rule_id = str(request.get("rule_id") or "")
    figure_contract = _MECHANICAL_FIGURE_CONTRACTS.get(rule_id)
    if figure_contract is None:
        return None
    metric_sources = _mechanical_summary_sources(
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
        (
            str(figure_contract["curve_id"]),
            input_path,
            str(request.get("template") or "curve"),
            curve_options,
        )
    ]
    render_jobs.extend(
        (
            metric_id,
            metric_source,
            str(metric_options.pop("template", "bar")),
            metric_options,
        )
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
        outputs, exports = _rename_metric_exports(
            payload, metric_id=metric_id, figures_dir=figures_dir
        )
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
            "kind": "mechanical_curve_and_summary_bundle",
            "rule_id": rule_id,
            "metric_ids": [
                metric_id for metric_id, _source, _template, _options in render_jobs
            ],
        },
    }
