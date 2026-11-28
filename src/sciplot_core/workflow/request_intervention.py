"""Publish a pre-render intervention without executing an unapproved plot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.assisted_cleanup import write_cleanup_request
from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.source_locations import literal_source_path
from sciplot_core.one_step import build_one_step_project
from sciplot_core.semantic import build_intervention_request
from sciplot_core.workflow.errors import WorkflowIntervention
from sciplot_core.workflow.project_results import _write_one_step_status
from sciplot_core.workflow.route_intent import WorkflowRouteIntent


def _enforce_intervention_gate(
    *,
    request_path: Path,
    request: dict[str, Any],
    route_intent: WorkflowRouteIntent,
    semantic: dict[str, Any],
    input_path: Path,
    output_dir: Path,
    raw_archive: dict[str, Any],
    study_model: dict[str, Any],
    layout_policy: Any,
    figure_plan: ResolvedFigurePlan | None = None,
) -> None:
    pending_rule_blocked = semantic.get("rule_readiness") == "pending"
    if not (
        semantic.get("needs_ai_intervention")
        and (route_intent.uses_semantic_preparation or pending_rule_blocked)
    ):
        return
    intervention = build_intervention_request(
        input_path=input_path,
        output_dir=output_dir,
        semantic=semantic,
        request=request,
    )
    intervention_path = output_dir / "intervention_request.json"
    intervention_path.write_text(
        json.dumps(json_safe(intervention), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_cleanup_request(
        output_dir,
        _output_namespace=output_dir,
        input_path=input_path,
        reason=str(intervention.get("category") or "semantic_intervention"),
        semantic=semantic,
        request=request,
        intervention_request=intervention_path,
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
        resolved_figure_plan=figure_plan,
    )
    _write_one_step_status(output_dir, one_step_status)
    failure = (
        f"Requested material rule `{semantic.get('rule_id')}` is pending fixture-backed acceptance."
        if pending_rule_blocked
        else "SciPlot could not auto-detect this input."
    )
    raise WorkflowIntervention(f"{failure} Intervention request written to {literal_source_path(intervention_path)}.")
