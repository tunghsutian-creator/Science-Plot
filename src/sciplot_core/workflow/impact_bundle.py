"""Materialize and render impact-condition figure bundles."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    finalize_figure_plan_result,
    outcomes_for_artifact_map,
    request_for_figure_task,
    resolve_figure_plan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.policy import normalize_export_formats
from sciplot_core.render import render_to_dir
from sciplot_core.semantic_sources.impact_sources import (
    read_impact_condition_payloads,
)
from sciplot_core.workflow.bundle_exports import (
    _rename_metric_exports,
)


def _impact_condition_sources(
    source_input: Path,
    *,
    request: dict[str, Any],
    output_dir: Path,
    _resolved_figure_plan: ResolvedFigurePlan | None = None,
) -> list[tuple[str, Path, dict[str, Any]]]:
    """Materialize one canonical categorical source per impact workbook sheet."""

    if str(request.get("rule_id") or "").strip() != "impact_metric":
        return []
    if (
        resolve_rule_template(
            "impact_metric",
            request.get("template")
            if isinstance(request.get("template"), str)
            else None,
        )
        == "point_line"
    ):
        return []
    source = source_input
    if source.is_dir():
        workbooks = sorted(
            path
            for path in source.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}
        )
        if len(workbooks) != 1:
            return []
        source = workbooks[0]
    if not source.is_file():
        return []
    conditions = read_impact_condition_payloads(source)
    figure_plan = _resolved_figure_plan
    if figure_plan is None and request.get("resolved_figure_plan") is not None:
        figure_plan = resolved_figure_plan_from_payload(request["resolved_figure_plan"])
    if figure_plan is None:
        study_model_payload = request.get("study_model")
        study_model = (
            study_model_payload if isinstance(study_model_payload, dict) else {}
        )
        figure_plan = resolve_figure_plan(
            rule_id="impact_metric",
            template=resolve_rule_template(
                "impact_metric",
                (
                    request.get("template")
                    if isinstance(request.get("template"), str)
                    else None
                ),
            ),
            study_model=study_model,
            input_path=source,
            request=request,
        )
    if figure_plan is None or figure_plan.selection_policy != "all_workbook_conditions":
        return []

    source_dir = output_dir / "processed" / "veusz_metric_sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    condition_sources: list[tuple[str, Path, dict[str, Any]]] = []
    by_condition = dict(conditions)
    for task in figure_plan.tasks:
        condition = task.conditions[0]
        payload = by_condition.get(condition)
        if payload is None:
            continue
        metric_source = source_dir / f"{task.artifact_stem}.csv"
        pd.DataFrame(payload.rows).to_csv(metric_source, header=False, index=False)
        condition_sources.append(
            (
                task.artifact_stem,
                metric_source,
                {
                    "legend_position": "none",
                    "series_label_mode": "none",
                    "x_label_override": "Sample",
                    "y_label_override": "Impact strength (kJ m⁻²)",
                    "summary_statistic": "median_iqr",
                    "size": "60x55",
                },
            )
        )
    return condition_sources


def _resolve_impact_bundle_context(
    request: dict[str, Any],
    figure_plan: ResolvedFigurePlan | None,
) -> tuple[str, ResolvedFigurePlan | None] | None:
    if str(request.get("rule_id") or "").strip() != "impact_metric":
        return None
    impact_template = resolve_rule_template(
        "impact_metric",
        request.get("template") if isinstance(request.get("template"), str) else None,
    )
    if figure_plan is None and request.get("resolved_figure_plan") is not None:
        figure_plan = resolved_figure_plan_from_payload(request["resolved_figure_plan"])
    return impact_template, figure_plan


def _render_veusz_impact_bundle(
    source_input: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
    _source_builder: Callable[..., list[tuple[str, Path, dict[str, Any]]]] = (
        _impact_condition_sources
    ),
    _renderer: Callable[..., dict[str, Any]] = render_to_dir,
    _resolved_figure_plan: ResolvedFigurePlan | None = None,
) -> dict[str, Any] | None:
    context = _resolve_impact_bundle_context(request, _resolved_figure_plan)
    if context is None:
        return None
    impact_template, figure_plan = context
    return _render_resolved_impact_bundle(
        source_input,
        output_dir=output_dir,
        options=options,
        export_formats=normalize_export_formats(export_formats),
        request=request,
        impact_template=impact_template,
        figure_plan=figure_plan,
        source_builder=_source_builder,
        renderer=_renderer,
    )


def _render_canonical_veusz_impact_bundle(
    source_input: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: tuple[str, ...],
    request: dict[str, Any],
    _resolved_figure_plan: ResolvedFigurePlan | None = None,
) -> dict[str, Any] | None:
    context = _resolve_impact_bundle_context(request, _resolved_figure_plan)
    if context is None:
        return None
    impact_template, figure_plan = context
    return _render_resolved_impact_bundle(
        source_input,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
        impact_template=impact_template,
        figure_plan=figure_plan,
        source_builder=_impact_condition_sources,
        renderer=render_to_dir,
    )


def _render_resolved_impact_bundle(
    source_input: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: tuple[str, ...],
    request: dict[str, Any],
    impact_template: str,
    figure_plan: ResolvedFigurePlan | None,
    source_builder: Callable[..., list[tuple[str, Path, dict[str, Any]]]],
    renderer: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    if impact_template == "point_line":
        task_request = (
            request_for_figure_task(request, figure_plan.tasks[0])
            if figure_plan is not None
            else request
        )
        result = renderer(
            source_input,
            template=impact_template,
            output_dir=output_dir / "figures",
            options=options,
            export_formats=export_formats,
            request_context={
                **task_request,
                "template": impact_template,
                "explicit_render_option_keys": request.get(
                    "explicit_render_option_keys", []
                ),
            },
        )
        finalize_figure_plan_result(figure_plan, result)
        return result
    condition_sources = source_builder(
        source_input,
        request=request,
        output_dir=output_dir,
        _resolved_figure_plan=figure_plan,
    )
    if not condition_sources and (
        figure_plan is None or figure_plan.selection_policy != "all_workbook_conditions"
    ):
        return None
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
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
    artifacts_by_id: dict[str, list[str]] = (
        {task.figure_id: [] for task in figure_plan.tasks}
        if figure_plan is not None
        else {}
    )
    for figure_id, metric_source, metric_options in condition_sources:
        metric_dir = figures_dir / f"_{figure_id}_render"
        task = task_by_stem.get(figure_id)
        task_request = (
            request_for_figure_task(request, task) if task is not None else request
        )
        payload = renderer(
            metric_source,
            template=impact_template,
            output_dir=metric_dir,
            options={**options, **metric_options},
            export_formats=export_formats,
            request_context={
                **task_request,
                "template": impact_template,
                "explicit_render_option_keys": request.get(
                    "explicit_render_option_keys", []
                ),
            },
        )
        outputs, exports = _rename_metric_exports(
            payload,
            metric_id=figure_id,
            figures_dir=figures_dir,
        )
        if task is not None:
            exports = [{**item, "figure_id": task.figure_id} for item in exports]
        combined_outputs.extend(outputs)
        combined_exports.extend(exports)
        metric_worker = figures_dir / "_veusz" / figure_id
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
        if task is not None:
            artifacts_by_id[task.figure_id].extend(
                [*outputs, *mapped_documents, *mapped_specs]
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
        if metric_dir.exists():
            shutil.rmtree(metric_dir)
    result = {
        "kind": "sciplot_render_result",
        "template": impact_template,
        "input": str(source_input),
        "sheet": None,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "export_formats": list(export_formats),
        "exports": combined_exports,
        "outputs": combined_outputs,
        "qa_reports": combined_reports,
        "veusz_documents": combined_documents,
        "veusz_specs": combined_specs,
        "terminal_render_requests": combined_terminal_requests,
        "multi_metric_bundle": {
            "kind": "impact_condition_bundle",
            "metric_ids": [
                figure_id for figure_id, _source, _options in condition_sources
            ],
        },
    }
    if figure_plan is not None:
        outcome_artifacts: dict[str, list[str] | tuple[str, ...]] = {
            figure_id: list(artifacts)
            for figure_id, artifacts in artifacts_by_id.items()
        }
        result["multi_metric_bundle"]["figure_ids"] = list(
            figure_plan.selected_figure_ids
        )
        result["figure_outcomes"] = [
            outcome.to_payload()
            for outcome in outcomes_for_artifact_map(
                figure_plan,
                outcome_artifacts,
                missing_reason_code="impact_condition_source_unavailable",
            )
        ]
        finalize_figure_plan_result(figure_plan, result)
    return result
