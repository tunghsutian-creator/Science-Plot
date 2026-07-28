"""Materialize and render rheology sweep metric figures."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
    RHEOLOGY_METRIC_AXIS_LABELS,
    anchored_log_decade_ticks,
)
from sciplot_core.render import render_to_dir

from sciplot_core.workflow.bundle_exports import (
    _metric_token,
    _rename_metric_exports,
)

_RHEOLOGY_METRIC_LABELS = {
    "storage_modulus": "Storage Modulus",
    "loss_modulus": "Loss Modulus",
    "loss_factor": "Loss Factor",
    "tan_delta": "Loss Factor",
    "complex_modulus": "Complex Modulus",
    "complex_viscosity": "Complex Viscosity",
}


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
        if key != "tan_delta"
        and any(_metric_token(header) == _metric_token(label) for header in headers)
    ]
    if prefix == "temp":
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
            next_x = (
                x_columns[block_index + 1]
                if block_index + 1 < len(x_columns)
                else len(headers)
            )
            y_column = next(
                (
                    index
                    for index in range(x_column + 1, next_x)
                    if _metric_token(headers[index]) == metric_token
                ),
                None,
            )
            if y_column is None:
                continue
            sample = (
                samples[x_column] or samples[y_column] or f"Sample {block_index + 1}"
            )
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
            "y_label_override": RHEOLOGY_METRIC_AXIS_LABELS.get(
                metric_key, metric_label
            ),
        }
        plotted_values = pd.to_numeric(
            metric_frame.iloc[3:, 1::2].stack(), errors="coerce"
        ).dropna()
        if prefix == "temp":
            metric_render_options["yscale"] = "log"
            if metric_key == "loss_factor":
                positive_values = plotted_values[plotted_values > 0]
                spans_two_decades = (
                    not positive_values.empty
                    and len(positive_values) == len(plotted_values)
                    and float(positive_values.max()) / float(positive_values.min())
                    >= 100.0
                )
                metric_render_options["yscale"] = (
                    "log" if spans_two_decades else "linear"
                )
                if spans_two_decades:
                    metric_render_options["y_ticks"] = list(
                        anchored_log_decade_ticks(positive_values)
                    )
        if prefix == "freq" and metric_key == "storage_modulus":
            if not plotted_values.empty and float(plotted_values.max()) <= 5e5:
                metric_render_options.update(
                    {
                        "y_max": 5e5,
                        "y_ticks": [1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0],
                    }
                )
        elif prefix == "freq" and metric_key in {"loss_factor", "complex_viscosity"}:
            metric_render_options["y_ticks"] = list(
                anchored_log_decade_ticks(plotted_values)
            )
        metric_sources.append(
            (
                f"{prefix}_{metric_key}",
                metric_source,
                metric_render_options,
            )
        )
    return metric_sources


def _render_veusz_sweep_bundle(
    input_path: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    metric_sources = _sweep_metric_sources(
        input_path, request=request, output_dir=output_dir
    )
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
            "metric_ids": [
                metric_id for metric_id, _source, _options in metric_sources
            ],
        },
    }
