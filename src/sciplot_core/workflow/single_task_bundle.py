"""Install one already-selected FigureTask through the shared Veusz lifecycle."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    FigureTask,
    finalize_figure_plan_result,
    outcomes_for_artifact_map,
    request_for_figure_task,
)
from sciplot_core.policy import DEFAULT_EXPORT_FORMATS_POLICY
from sciplot_core.render import render_to_dir
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding
from sciplot_core.workflow.bundle_exports import _rename_metric_exports
from sciplot_core.workflow.task_artifacts import (
    install_task_worker_tree,
    task_qa_reports,
)


def render_selected_single_task_bundle(
    input_path: Path,
    *,
    plan: ResolvedFigurePlan,
    task: FigureTask,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
    metric_id: str,
    bundle_kind: str,
    missing_reason_code: str,
    terminal_source_binding: MaterializedTerminalSourceBinding | None = None,
) -> dict[str, Any]:
    """Render and atomically install one task without selecting its identity."""

    transaction_dir = output_dir / f".single-task-transaction-{uuid4().hex}"
    task_request = request_for_figure_task(request, task)
    try:
        payload = render_to_dir(
            input_path,
            template=task.template,
            output_dir=transaction_dir,
            options=options,
            export_formats=export_formats,
            request_context={
                **task_request,
                "explicit_render_option_keys": request.get(
                    "explicit_render_option_keys", []
                ),
            },
            _terminal_source_binding=terminal_source_binding,
        )
        figures_dir = output_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)
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
        artifacts = [*outputs, *documents, *specs]
        result: dict[str, Any] = {
            "kind": "sciplot_render_result",
            "template": task.template,
            "input": str(input_path),
            "sheet": None,
            "render_engine": "veusz",
            "qa_target": "veusz_export",
            "export_formats": list(export_formats or DEFAULT_EXPORT_FORMATS_POLICY),
            "outputs": outputs,
            "exports": exports,
            "qa_reports": task_qa_reports(
                payload,
                outputs=outputs,
                documents=documents,
            ),
            "veusz_documents": documents,
            "veusz_specs": specs,
            "terminal_render_requests": [
                item
                for item in payload.get("terminal_render_requests", [])
                if isinstance(item, dict)
            ],
            "transform_steps": [
                item
                for item in payload.get("transform_steps", [])
                if isinstance(item, dict)
            ],
            "multi_metric_bundle": {
                "kind": bundle_kind,
                "metric_ids": [metric_id],
                "figure_ids": [task.figure_id],
                "document_policy": "independent_single_page_vsz",
            },
            "figure_outcomes": [
                outcome.to_payload()
                for outcome in outcomes_for_artifact_map(
                    plan,
                    {task.figure_id: artifacts},
                    missing_reason_code=missing_reason_code,
                )
            ],
        }
        completed = finalize_figure_plan_result(plan, result)
        if completed is None or not completed.complete:
            raise ValueError(
                f"{missing_reason_code}: the selected task requires one VSZ, "
                "PDF, and 300-dpi TIFF."
            )
        return result
    finally:
        shutil.rmtree(transaction_dir, ignore_errors=True)


__all__ = ["render_selected_single_task_bundle"]
