"""Materialize and render DSC phase figure bundles."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
)
from sciplot_core.render import render_to_dir

from sciplot_core.workflow.bundle_exports import (
    _rename_metric_exports,
)


def _dsc_phase_sources(
    source: Path,
    *,
    request: dict[str, Any],
    output_dir: Path,
) -> list[tuple[str, Path, dict[str, Any]]]:
    if (
        str(request.get("rule_id") or "").strip() != "dsc_curve"
        or source.suffix.lower() != ".csv"
    ):
        return []
    frame = pd.read_csv(source, header=None)
    if frame.shape[0] < 4 or frame.shape[1] < 4 or frame.shape[1] % 2:
        return []
    phase_contracts = (
        ("Cooling", "dsc_cooling"),
        ("Second heating", "dsc_second_heating"),
    )
    sources_dir = output_dir / "processed" / "veusz_metric_sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    phase_sources: list[tuple[str, Path, dict[str, Any]]] = []
    for phase_label, figure_id in phase_contracts:
        selected_columns: list[int] = []
        clean_samples: list[str] = []
        for column in range(0, frame.shape[1], 2):
            sample = str(frame.iat[2, column]).strip()
            prefix = f"{phase_label} "
            if not sample.startswith(prefix):
                continue
            selected_columns.extend([column, column + 1])
            clean_samples.extend([sample[len(prefix) :], sample[len(prefix) :]])
        if not selected_columns:
            continue
        phase_frame = frame.iloc[:, selected_columns].copy()
        phase_frame.iloc[2, :] = clean_samples
        phase_source = sources_dir / f"{figure_id}.csv"
        phase_frame.to_csv(phase_source, header=False, index=False)
        phase_sources.append(
            (
                figure_id,
                phase_source,
                {
                    "legend_position": "none",
                    "series_label_mode": "inline",
                    "series_label_side": (
                        "right" if phase_label == "Cooling" else "left"
                    ),
                    "show_y_ticks": False,
                    "baseline": "none",
                    "stack_peak_envelope": True,
                    "x_label_override": "Temperature (°C)",
                    "y_label_override": "Heat flow (W g⁻¹)",
                    "palette_preset": "control_first_bright",
                },
            )
        )
    return phase_sources if len(phase_sources) == len(phase_contracts) else []


def _render_veusz_dsc_bundle(
    input_path: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    phase_sources = _dsc_phase_sources(
        input_path, request=request, output_dir=output_dir
    )
    if not phase_sources:
        return None
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    combined_outputs: list[str] = []
    combined_exports: list[dict[str, Any]] = []
    combined_reports: list[dict[str, Any]] = []
    combined_documents: list[str] = []
    combined_specs: list[str] = []
    combined_terminal_requests: list[dict[str, Any]] = []
    for phase_id, phase_source, phase_options in phase_sources:
        phase_dir = figures_dir / f"_{phase_id}_render"
        payload = render_to_dir(
            phase_source,
            template="stacked_curve",
            output_dir=phase_dir,
            options={**options, **phase_options},
            export_formats=export_formats,
            request_context={
                **request,
                "template": "stacked_curve",
                "explicit_render_option_keys": request.get(
                    "explicit_render_option_keys", []
                ),
            },
        )
        outputs, exports = _rename_metric_exports(
            payload, metric_id=phase_id, figures_dir=figures_dir
        )
        combined_outputs.extend(outputs)
        combined_exports.extend(exports)
        phase_worker = figures_dir / "_veusz" / phase_id
        if phase_worker.exists():
            shutil.rmtree(phase_worker)
        source_worker = phase_dir / "_veusz"
        if source_worker.exists():
            phase_worker.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_worker, phase_worker)
        mapped_documents: list[str] = []
        mapped_specs: list[str] = []
        for item in payload.get("veusz_documents", []):
            source_path = Path(str(item))
            try:
                destination = phase_worker / source_path.relative_to(source_worker)
            except ValueError:
                continue
            if destination.exists():
                mapped_documents.append(str(destination))
        for item in payload.get("veusz_specs", []):
            source_path = Path(str(item))
            try:
                destination = phase_worker / source_path.relative_to(source_worker)
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
        if phase_dir.exists():
            shutil.rmtree(phase_dir)
    return {
        "kind": "sciplot_render_result",
        "template": str(request.get("template") or "curve"),
        "input": str(input_path),
        "sheet": None,
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
            "kind": "dsc_cycle_phase_bundle",
            "metric_ids": [phase_id for phase_id, _source, _options in phase_sources],
        },
    }
