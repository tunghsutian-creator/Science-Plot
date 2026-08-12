"""Render one selected performance FigurePlan as an atomic task bundle."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    finalize_figure_plan_result,
    outcomes_for_artifact_map,
    request_for_figure_task,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.source_binding import source_tree_sha256
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.policy import DEFAULT_EXPORT_FORMATS_POLICY
from sciplot_core.render import render_to_dir
from sciplot_core.workflow.bundle_exports import _rename_metric_exports
from sciplot_core.workflow.task_artifacts import (
    install_task_worker_tree,
    task_qa_reports,
)


def _render_veusz_performance_bundle(
    source_input: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
    _resolved_figure_plan: ResolvedFigurePlan | None = None,
) -> dict[str, Any] | None:
    """Render exactly the selected tasks; never select templates in the adapter."""

    if str(request.get("rule_id") or "").strip() != "performance_comparison":
        return None
    plan = _resolved_figure_plan
    if plan is None and request.get("resolved_figure_plan") is not None:
        plan = resolved_figure_plan_from_payload(request["resolved_figure_plan"])
    if plan is None:
        raise ValueError(
            "performance_figure_plan_required: performance bundle execution "
            "requires one selected FigurePlan."
        )
    if plan.rule_id != "performance_comparison":
        raise ValueError(
            "performance_figure_plan_mismatch: selected FigurePlan has the wrong rule."
        )
    if source_tree_sha256(source_input) != plan.source_sha256:
        raise ValueError(
            "performance_figure_plan_source_changed: source no longer matches "
            "the selected FigurePlan."
        )

    transaction_dir = output_dir / (f".performance-bundle-transaction-{uuid4().hex}")
    rendered: list[tuple[FigureTask, dict[str, Any]]] = []
    try:
        for task in plan.tasks:
            task_request = request_for_figure_task(request, task)
            payload = render_to_dir(
                source_input,
                template=task.template,
                output_dir=transaction_dir / task.artifact_stem,
                options=options,
                export_formats=export_formats,
                request_context={
                    **task_request,
                    "explicit_render_option_keys": request.get(
                        "explicit_render_option_keys", []
                    ),
                },
            )
            rendered.append((task, payload))
    except Exception:
        shutil.rmtree(transaction_dir, ignore_errors=True)
        raise

    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    combined: dict[str, list[Any]] = {
        "outputs": [],
        "exports": [],
        "qa_reports": [],
        "veusz_documents": [],
        "veusz_specs": [],
        "terminal_render_requests": [],
        "transform_steps": [],
    }
    artifacts_by_id = {task.figure_id: [] for task in plan.tasks}
    try:
        for task, payload in rendered:
            outputs, exports = _rename_metric_exports(
                payload,
                metric_id=task.artifact_stem,
                figures_dir=figures_dir,
            )
            exports = [{**item, "figure_id": task.figure_id} for item in exports]
            documents, specs = install_task_worker_tree(
                payload,
                task=task,
                figures_dir=figures_dir,
            )
            combined["outputs"].extend(outputs)
            combined["exports"].extend(exports)
            combined["veusz_documents"].extend(documents)
            combined["veusz_specs"].extend(specs)
            combined["terminal_render_requests"].extend(
                item
                for item in payload.get("terminal_render_requests", [])
                if isinstance(item, dict)
            )
            combined["transform_steps"].extend(
                item
                for item in payload.get("transform_steps", [])
                if isinstance(item, dict)
            )
            combined["qa_reports"].extend(
                task_qa_reports(
                    payload,
                    outputs=outputs,
                    documents=documents,
                )
            )
            artifacts_by_id[task.figure_id].extend([*outputs, *documents, *specs])
    finally:
        shutil.rmtree(transaction_dir, ignore_errors=True)

    result: dict[str, Any] = {
        "kind": "sciplot_render_result",
        "template": "performance_comparison_figure_set",
        "input": str(source_input),
        "sheet": None,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "export_formats": list(export_formats or DEFAULT_EXPORT_FORMATS_POLICY),
        **combined,
        "multi_metric_bundle": {
            "kind": "performance_comparison_figure_set",
            "templates": [task.template for task in plan.tasks],
            "figure_ids": list(plan.selected_figure_ids),
            "document_policy": "independent_single_page_vsz",
        },
        "figure_outcomes": [
            outcome.to_payload()
            for outcome in outcomes_for_artifact_map(
                plan,
                artifacts_by_id,
                missing_reason_code="performance_task_artifacts_incomplete",
            )
        ],
    }
    completed = finalize_figure_plan_result(plan, result)
    if completed is None or not completed.complete:
        raise ValueError(
            "performance_task_artifacts_incomplete: every selected performance "
            "task requires one VSZ, PDF, and 300-dpi TIFF."
        )
    return result


__all__ = ["_render_veusz_performance_bundle"]
