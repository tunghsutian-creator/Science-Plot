"""Render the selected publication-digitized DSC single-curve task."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import (
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.dsc_resolution import (
    dsc_single_curve_source_sha256,
)
from sciplot_core.workflow.single_task_bundle import (
    render_selected_single_task_bundle,
)


def _render_veusz_dsc_bundle(
    input_path: Path,
    *,
    output_dir: Path,
    options: dict[str, Any],
    export_formats: object,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    """Render the exact selected DSC task without phase or template selection."""

    if str(request.get("rule_id") or "").strip() != "dsc_curve":
        return None
    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    if plan is None:
        raise ValueError(
            "dsc_figure_plan_required: DSC bundle execution requires one "
            "selected FigurePlan."
        )
    if plan.rule_id != "dsc_curve" or len(plan.tasks) != 1:
        raise ValueError(
            "dsc_figure_plan_mismatch: DSC rendering requires the exact "
            "single-task dsc_curve plan."
        )
    task = plan.tasks[0]
    if task.figure_id != "dsc_heat_flow_vs_temperature" or task.template != "curve":
        raise ValueError(
            "dsc_figure_plan_mismatch: DSC rendering cannot expand or replace "
            "the selected single-curve task."
        )
    if dsc_single_curve_source_sha256(input_path) != plan.source_sha256:
        raise ValueError(
            "dsc_figure_plan_source_changed: DSC source no longer matches the "
            "selected FigurePlan."
        )

    return render_selected_single_task_bundle(
        input_path,
        plan=plan,
        task=task,
        output_dir=output_dir,
        options=options,
        export_formats=export_formats,
        request=request,
        metric_id="heat_flow",
        bundle_kind="dsc_single_curve_figure_set",
        missing_reason_code="dsc_task_artifacts_incomplete",
    )


__all__ = ["_render_veusz_dsc_bundle"]
