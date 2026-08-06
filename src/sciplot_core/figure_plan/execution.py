"""Project tasks into requests and bind explicit per-figure outcomes."""

from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.outcome import FigureOutcome
from sciplot_core.figure_plan.payload_types import FigurePlanGatePayload
from sciplot_core.figure_plan.plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.figure_plan.metric_binding import (
    CartesianMetricBinding,
    OrderedMetricsBinding,
)
from sciplot_core.figure_plan.task import FigureTask


_METRIC_PROJECTION_FIELDS = ("metric", "x_metric", "y_metric", "metric_ids")


def request_for_figure_task(
    request: dict[str, Any],
    task: FigureTask,
) -> dict[str, Any]:
    """Project one complete task; never infer metrics from the first queue item."""

    projected = deepcopy(request)
    binding = task.metric_binding
    if binding is None:
        assert task.x_metric is not None
        assert task.y_metric is not None
        binding = CartesianMetricBinding(
            x_metric=task.x_metric,
            y_metric=task.y_metric,
        )
    _remove_metric_projection(projected)
    _apply_metric_projection(projected, binding, include_singular_metric=False)
    projected["template"] = task.template
    projected["resolved_figure_task"] = task.to_payload()
    if task.sample_order:
        projected["series_order"] = list(task.sample_order)
    if task.conditions:
        projected["condition_order"] = list(task.conditions)
    if task.condition_labels:
        projected["condition_label_mapping"] = dict(
            zip(task.conditions, task.condition_labels, strict=True)
        )
    study_model_value = projected.get("study_model")
    if isinstance(study_model_value, dict):
        study_model = deepcopy(study_model_value)
    else:
        study_model = {}
    _remove_metric_projection(study_model)
    raw_queue_value = study_model.get("figure_queue")
    if isinstance(raw_queue_value, list):
        raw_queue = raw_queue_value
    else:
        raw_queue = []
    existing = next(
        (
            deepcopy(value)
            for value in raw_queue
            if isinstance(value, dict) and str(value.get("id") or "") == task.figure_id
        ),
        {},
    )
    _remove_metric_projection(existing)
    _apply_metric_projection(existing, binding, include_singular_metric=True)
    study_model["figure_queue"] = [
        {
            **existing,
            "id": task.figure_id,
            "order": 1,
            "status": "planned",
            "title": task.title,
            "default_template": task.template,
            "artifact_stem": task.artifact_stem,
            "document_stem": task.document_stem,
            "resolved_figure_task": task.to_payload(),
        }
    ]
    projected["study_model"] = study_model
    return projected


def _remove_metric_projection(target: dict[str, Any]) -> None:
    for key in _METRIC_PROJECTION_FIELDS:
        target.pop(key, None)


def _apply_metric_projection(
    target: dict[str, Any],
    binding: CartesianMetricBinding | OrderedMetricsBinding,
    *,
    include_singular_metric: bool,
) -> None:
    if isinstance(binding, CartesianMetricBinding):
        target["x_metric"] = binding.x_metric
        target["y_metric"] = binding.y_metric
        if include_singular_metric:
            target["metric"] = binding.y_metric
        return
    target["metric_ids"] = list(binding.metric_ids)


def merge_figure_outcomes(
    plan: ResolvedFigurePlan,
    outcomes: list[FigureOutcome] | tuple[FigureOutcome, ...],
) -> ResolvedFigurePlan:
    """Replace known outcomes while retaining explicit pending tasks."""

    by_id: dict[str, FigureOutcome] = {}
    selected = set(plan.selected_figure_ids)
    for outcome in outcomes:
        if not isinstance(outcome, FigureOutcome):
            raise ValueError("Figure outcomes must be FigureOutcome objects.")
        if outcome.figure_id not in selected:
            raise ValueError(
                f"FigureOutcome references an unselected task: {outcome.figure_id}"
            )
        if outcome.figure_id in by_id:
            raise ValueError(
                f"Duplicate FigureOutcome for selected task: {outcome.figure_id}"
            )
        by_id[outcome.figure_id] = outcome
    prior = {outcome.figure_id: outcome for outcome in plan.outcomes}
    return ResolvedFigurePlan(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=plan.tasks,
        outcomes=tuple(
            by_id.get(task.figure_id, prior[task.figure_id]) for task in plan.tasks
        ),
        source_sha256=plan.source_sha256,
    )


def outcomes_from_payload(value: object) -> list[FigureOutcome]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("figure_outcomes must be a list.")
    return [FigureOutcome.from_payload(item) for item in value]


def outcomes_for_artifact_map(
    plan: ResolvedFigurePlan,
    artifacts_by_figure_id: dict[str, list[str] | tuple[str, ...]],
    *,
    missing_reason_code: str = "selected_figure_artifacts_missing",
) -> list[FigureOutcome]:
    """Build one explicit ready/unavailable outcome for every selected task."""

    outcomes: list[FigureOutcome] = []
    for task in plan.tasks:
        artifacts = tuple(
            str(path)
            for value in artifacts_by_figure_id.get(task.figure_id, ())
            if isinstance(value, str)
            and value.strip()
            and (path := Path(value).expanduser()).is_file()
        )
        candidate = FigureOutcome(
            figure_id=task.figure_id,
            status="ready",
            artifacts=artifacts,
        )
        if candidate.delivery_artifacts_complete:
            outcomes.append(candidate)
        else:
            outcomes.append(
                FigureOutcome(
                    figure_id=task.figure_id,
                    status="unavailable",
                    artifacts=artifacts,
                    reason_code=missing_reason_code,
                    message=(
                        "The selected task does not have an editable VSZ and matching "
                        "PDF/TIFF delivery pair."
                    ),
                )
            )
    return outcomes


def finalize_figure_plan_result(
    plan: ResolvedFigurePlan | None,
    result: dict[str, Any],
) -> ResolvedFigurePlan | None:
    """Bind renderer outcomes and persist the same completed plan in the result."""

    if plan is None:
        return None
    fresh_plan = ResolvedFigurePlan.planned(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=plan.tasks,
        source_sha256=plan.source_sha256,
    )
    outcomes = outcomes_from_payload(result.get("figure_outcomes"))
    if not outcomes and len(plan.tasks) == 1:
        artifacts = _existing_result_artifacts(result)
        outcomes = outcomes_for_artifact_map(
            fresh_plan,
            {plan.tasks[0].figure_id: list(artifacts)},
        )
    reported_ids = {outcome.figure_id for outcome in outcomes}
    if len(reported_ids) != len(outcomes):
        raise ValueError("Renderer returned duplicate FigureOutcome records.")
    unknown_ids = reported_ids - set(fresh_plan.selected_figure_ids)
    if unknown_ids:
        raise ValueError(
            "Renderer returned outcomes for unselected tasks: "
            + ", ".join(sorted(unknown_ids))
        )
    missing_ids = [
        task.figure_id
        for task in fresh_plan.tasks
        if task.figure_id not in reported_ids
    ]
    outcomes.extend(
        FigureOutcome(
            figure_id=figure_id,
            status="unavailable",
            reason_code="selected_figure_outcome_missing",
            message="The current renderer did not report this selected task.",
        )
        for figure_id in missing_ids
    )
    outcomes.sort(
        key=lambda outcome: fresh_plan.selected_figure_ids.index(outcome.figure_id)
    )
    completed = merge_figure_outcomes(fresh_plan, outcomes)
    result["figure_outcomes"] = [outcome.to_payload() for outcome in completed.outcomes]
    result["resolved_figure_plan"] = completed.to_payload()
    return completed


def editable_figure_plan(
    plan: ResolvedFigurePlan,
    entries: list[dict[str, Any]],
    *,
    verified_pending_artifact_targets: Collection[Path] = (),
) -> ResolvedFigurePlan:
    """Describe installed or transaction-verified editable artifacts."""

    pending_targets = {
        path.expanduser().resolve() for path in verified_pending_artifact_targets
    }
    by_id = {
        str(entry.get("figure_id") or ""): entry
        for entry in entries
        if isinstance(entry, dict)
    }
    outcomes: list[FigureOutcome] = []
    for task in plan.tasks:
        entry = by_id.get(task.figure_id)
        if entry is None:
            outcomes.append(
                FigureOutcome(
                    figure_id=task.figure_id,
                    status="unavailable",
                    reason_code="figure_registry_entry_missing",
                    message="No current Studio registry entry exists for this task.",
                )
            )
            continue
        artifacts: list[str] = []
        for key in ("document", "spec"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            path = Path(value).expanduser()
            if path.is_file() or path.resolve() in pending_targets:
                artifacts.append(value)
        if entry.get("status") == "ready" and artifacts:
            outcomes.append(
                FigureOutcome(
                    figure_id=task.figure_id,
                    status="editable",
                    artifacts=tuple(artifacts),
                )
            )
            continue
        unavailable_value = entry.get("unavailable")
        if isinstance(unavailable_value, dict):
            unavailable = unavailable_value
        else:
            unavailable = {}
        outcomes.append(
            FigureOutcome(
                figure_id=task.figure_id,
                status="unavailable",
                artifacts=tuple(artifacts),
                reason_code=str(unavailable.get("reason_code") or "figure_unavailable"),
                message=str(
                    unavailable.get("message")
                    or "The selected figure is not currently available."
                ),
            )
        )
    return merge_figure_outcomes(plan, outcomes)


def figure_plan_gate(value: object) -> FigurePlanGatePayload | None:
    """Return one fail-closed package/publish gate for optional legacy state."""

    if value is None:
        return None
    try:
        plan = resolved_figure_plan_from_payload(value)
    except (TypeError, ValueError) as exc:
        return {
            "valid": False,
            "complete": False,
            "plan_id": None,
            "plan_sha256": None,
            "selected_figure_ids": [],
            "ready_figure_ids": [],
            "incomplete_figure_ids": [],
            "reason": f"invalid_resolved_figure_plan: {exc}",
        }
    if plan is None:
        return None
    ready_ids = [
        outcome.figure_id
        for outcome in plan.outcomes
        if outcome.status == "ready" and outcome.delivery_artifacts_complete
    ]
    return {
        "valid": True,
        "complete": plan.complete,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "source_sha256": plan.source_sha256,
        "selected_figure_ids": list(plan.selected_figure_ids),
        "ready_figure_ids": ready_ids,
        "incomplete_figure_ids": [
            figure_id
            for figure_id in plan.selected_figure_ids
            if figure_id not in set(ready_ids)
        ],
        "reason": None if plan.complete else "resolved_figure_plan_incomplete",
    }


def sync_figure_plan_projection(
    target: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """Atomically replace or remove the duplicated plan/outcome projection."""

    plan = resolved_figure_plan_from_payload(source.get("resolved_figure_plan"))
    if plan is None:
        target.pop("resolved_figure_plan", None)
        target.pop("figure_outcomes", None)
        return
    target["resolved_figure_plan"] = plan.to_payload()
    target["figure_outcomes"] = [outcome.to_payload() for outcome in plan.outcomes]


def _existing_result_artifacts(result: dict[str, Any]) -> tuple[str, ...]:
    values: list[object] = []
    for key in ("outputs", "veusz_documents", "veusz_specs"):
        candidate = result.get(key)
        if isinstance(candidate, list):
            values.extend(candidate)
    return tuple(
        str(path)
        for value in values
        if isinstance(value, str)
        and value.strip()
        and (path := Path(value).expanduser()).is_file()
    )


__all__ = [
    "editable_figure_plan",
    "figure_plan_gate",
    "finalize_figure_plan_result",
    "merge_figure_outcomes",
    "outcomes_for_artifact_map",
    "outcomes_from_payload",
    "request_for_figure_task",
    "sync_figure_plan_projection",
]
