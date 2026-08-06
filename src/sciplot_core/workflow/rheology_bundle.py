"""Materialize and render rheology sweep metric figures."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.figure_plan import (
    finalize_figure_plan_result,
    outcomes_for_artifact_map,
    request_for_figure_task,
    resolved_figure_plan_from_payload,
)
from sciplot_core.policy import DEFAULT_EXPORT_FORMATS_POLICY
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.render import render_to_dir

from sciplot_core.workflow.bundle_exports import _rename_metric_exports
from sciplot_core.workflow.rheology_task_sources import (
    RHEOLOGY_METRIC_LABELS,
    RheologyTaskSource,
    build_rheology_task_sources,
    sweep_prefix_for_request,
)
from sciplot_core.workflow.rheology_terminal_validation import (
    validate_temperature_render_payload,
    validate_temperature_task_sources,
)

_RHEOLOGY_METRIC_LABELS = RHEOLOGY_METRIC_LABELS


def _sweep_prefix_for_request(request: dict[str, Any]) -> str | None:
    return sweep_prefix_for_request(request)


def _sweep_metric_sources(
    source: Path,
    *,
    request: dict[str, Any],
    output_dir: Path,
    source_attestation: PreparationSourceAttestation | None = None,
) -> list[tuple[str, Path, dict[str, Any]]]:
    return [
        (record.metric_id, record.source, dict(record.render_options))
        for record in build_rheology_task_sources(
            source,
            request=request,
            output_dir=output_dir,
            source_attestation=source_attestation,
        )
    ]


def _render_veusz_sweep_bundle(
    input_path: Path,
    *,
    source_input: Path | None = None,
    source_attestation: PreparationSourceAttestation | None = None,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
    _source_builder: Callable[
        ..., list[RheologyTaskSource]
    ] = build_rheology_task_sources,
    _renderer: Callable[..., dict[str, Any]] = render_to_dir,
) -> dict[str, Any] | None:
    output_dir = output_dir.expanduser().resolve()
    prefix = _sweep_prefix_for_request(request)
    figure_plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    if prefix == "temp" and figure_plan is None:
        raise ValueError(
            "temperature_figure_plan_required: temperature Workflow rendering "
            "requires one exact resolved FigurePlan."
        )
    task_sources = _source_builder(
        input_path,
        request=request,
        output_dir=output_dir,
        raw_source=source_input,
        source_attestation=source_attestation,
    )
    if not task_sources and figure_plan is None:
        return None
    if prefix == "temp":
        assert figure_plan is not None
        validate_temperature_task_sources(
            task_sources,
            figure_plan=figure_plan,
            source_attestation=source_attestation,
        )
    elif any(record.binding is not None for record in task_sources):
        raise ValueError(
            "rheology_private_terminal_binding_scope_mismatch: only temperature "
            "task sources may use the private terminal-source seam."
        )

    figures_dir = output_dir / "figures"
    transaction_dir = output_dir / f".sciplot-rheology-sweep-stage-{uuid4().hex}"
    staged_figures_dir = transaction_dir / "figures"
    render_root = transaction_dir / "render"
    staged_figures_dir.mkdir(parents=True, exist_ok=False)
    render_root.mkdir(parents=True, exist_ok=False)
    combined_outputs: list[str] = []
    combined_exports: list[dict[str, Any]] = []
    combined_reports: list[dict[str, Any]] = []
    combined_documents: list[str] = []
    combined_specs: list[str] = []
    combined_terminal_requests: list[dict[str, Any]] = []
    task_by_stem = (
        {task.artifact_stem: task for task in figure_plan.tasks}
        if figure_plan is not None
        else {}
    )
    artifacts_by_id = (
        {task.figure_id: [] for task in figure_plan.tasks}
        if figure_plan is not None
        else {}
    )
    staged_artifacts_by_id = (
        {task.figure_id: [] for task in figure_plan.tasks}
        if figure_plan is not None
        else {}
    )
    result: dict[str, Any]
    try:
        for record in task_sources:
            metric_id = record.metric_id
            metric_dir = render_root / metric_id
            metric_render_options = {**options, **record.render_options}
            task = task_by_stem.get(metric_id)
            if prefix == "temp" and task is None:
                raise ValueError(
                    "temperature_figure_plan_mismatch: a materialized metric "
                    "source has no exact selected FigureTask."
                )
            task_request = request_for_figure_task(request, task) if task else request
            request_context = {
                **task_request,
                "explicit_render_option_keys": request.get(
                    "explicit_render_option_keys", []
                ),
            }
            renderer_arguments: dict[str, Any] = {
                "template": str(request.get("template") or "point_line"),
                "output_dir": metric_dir,
                "options": metric_render_options,
                "export_formats": export_formats,
                "request_context": request_context,
            }
            if prefix == "temp" and record.binding is not None:
                request_context.update(
                    {
                        "rule_id": record.binding.rule_id,
                        "x_metric": record.binding.x_metric,
                        "y_metric": record.binding.y_metric,
                        "series_order": list(record.binding.sample_order),
                    }
                )
                renderer_arguments["template"] = record.binding.template
                renderer_arguments["_terminal_source_binding"] = record.binding
            payload = _renderer(record.source, **renderer_arguments)
            if prefix == "temp":
                assert task is not None
                validate_temperature_render_payload(
                    payload,
                    record=record,
                    task=task,
                    metric_dir=metric_dir,
                    export_formats=export_formats,
                )

            staged_outputs, staged_exports = _rename_metric_exports(
                payload,
                metric_id=metric_id,
                figures_dir=staged_figures_dir,
            )
            outputs = [
                _rebase_figure_path(
                    value,
                    source_root=staged_figures_dir,
                    target_root=figures_dir,
                )
                for value in staged_outputs
            ]
            exports: list[dict[str, Any]] = []
            for item in staged_exports:
                final_path = _rebase_figure_path(
                    str(item.get("path") or ""),
                    source_root=staged_figures_dir,
                    target_root=figures_dir,
                )
                exports.append({**item, "source": final_path, "path": final_path})
            if task is not None:
                exports = [{**item, "figure_id": task.figure_id} for item in exports]
            combined_outputs.extend(outputs)
            combined_exports.extend(exports)

            staged_worker = staged_figures_dir / "_veusz" / metric_id
            source_worker = metric_dir / "_veusz"
            if source_worker.exists():
                staged_worker.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source_worker, staged_worker)
            mapped_documents = _mapped_worker_paths(
                payload.get("veusz_documents", []),
                source_worker=source_worker,
                staged_worker=staged_worker,
                final_worker=figures_dir / "_veusz" / metric_id,
            )
            mapped_specs = _mapped_worker_paths(
                payload.get("veusz_specs", []),
                source_worker=source_worker,
                staged_worker=staged_worker,
                final_worker=figures_dir / "_veusz" / metric_id,
            )
            combined_documents.extend(mapped_documents)
            combined_specs.extend(mapped_specs)
            if task is not None:
                artifacts_by_id[task.figure_id].extend(
                    [*outputs, *mapped_documents, *mapped_specs]
                )
                staged_artifacts_by_id[task.figure_id].extend(
                    [
                        *staged_outputs,
                        *(
                            _rebase_figure_path(
                                value,
                                source_root=figures_dir,
                                target_root=staged_figures_dir,
                            )
                            for value in [*mapped_documents, *mapped_specs]
                        ),
                    ]
                )
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
        result = {
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
                "metric_ids": [record.metric_id for record in task_sources],
            },
        }
        if figure_plan is not None:
            result["multi_metric_bundle"]["figure_ids"] = list(
                figure_plan.selected_figure_ids
            )
            staged_outcomes = outcomes_for_artifact_map(
                figure_plan,
                staged_artifacts_by_id,
                missing_reason_code=(
                    "temperature_metric_source_unavailable"
                    if prefix == "temp"
                    else "frequency_metric_source_unavailable"
                ),
            )
            result["figure_outcomes"] = [
                {
                    **outcome.to_payload(),
                    "artifacts": list(artifacts_by_id[outcome.figure_id]),
                }
                for outcome in staged_outcomes
            ]
            finalize_figure_plan_result(figure_plan, result)
        _install_staged_figures(
            staged_figures_dir,
            figures_dir=figures_dir,
            transaction_dir=transaction_dir,
        )
    finally:
        shutil.rmtree(transaction_dir, ignore_errors=True)

    return result


def _rebase_figure_path(
    value: str,
    *,
    source_root: Path,
    target_root: Path,
) -> str:
    path = Path(value).expanduser().resolve()
    try:
        relative = path.relative_to(source_root.resolve())
    except ValueError as exc:
        raise ValueError(
            "Rheology figure artifact escaped its transaction root."
        ) from exc
    return str(target_root / relative)


def _mapped_worker_paths(
    values: object,
    *,
    source_worker: Path,
    staged_worker: Path,
    final_worker: Path,
) -> list[str]:
    if not isinstance(values, list) or not source_worker.exists():
        return []
    mapped: list[str] = []
    for item in values:
        source_path = Path(str(item)).expanduser().resolve()
        try:
            relative = source_path.relative_to(source_worker.resolve())
        except ValueError:
            continue
        if (staged_worker / relative).is_file():
            mapped.append(str(final_worker / relative))
    return mapped


def _install_staged_figures(
    staged_figures_dir: Path,
    *,
    figures_dir: Path,
    transaction_dir: Path,
) -> None:
    previous = transaction_dir / "previous_figures"
    try:
        if figures_dir.exists() or figures_dir.is_symlink():
            figures_dir.replace(previous)
        staged_figures_dir.replace(figures_dir)
    except BaseException:
        if previous.exists() and not figures_dir.exists():
            previous.replace(figures_dir)
        raise
