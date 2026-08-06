"""Bind canonical terminal render evidence to one selected FigurePlan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sciplot_core.terminal_request import normalize_terminal_render_request

from sciplot_core.figure_plan.outcome import FigureOutcome
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask


SOURCE_UNAVAILABLE_WITHOUT_TERMINAL_EVIDENCE = frozenset(
    {
        "frequency_metric_source_unavailable",
        "impact_condition_source_unavailable",
        "temperature_metric_source_unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class BoundTerminalFigureEvidence:
    """Immutable proof that terminal task evidence belongs to one selected plan."""

    selected_plan: ResolvedFigurePlan
    terminal_tasks: tuple[FigureTask, ...]
    reported_outcomes: tuple[FigureOutcome, ...]
    completed_plan: ResolvedFigurePlan | None


def bind_terminal_figure_evidence(
    *,
    selected_plan: ResolvedFigurePlan | None,
    result: dict[str, Any],
) -> BoundTerminalFigureEvidence | None:
    """Validate task-aware terminal requests before a render result can escape."""

    terminal_requests = _normalized_terminal_requests(result)
    terminal_tasks = tuple(
        FigureTask.from_payload(item["resolved_figure_task"])
        for item in terminal_requests
        if "resolved_figure_task" in item
    )
    if selected_plan is None:
        if terminal_tasks:
            raise ValueError(
                "terminal_figure_task_unbound: task-aware terminal evidence "
                "requires a selected FigurePlan."
            )
        if result.get("resolved_figure_plan") is not None or result.get(
            "figure_outcomes"
        ) not in (None, []):
            raise ValueError(
                "terminal_figure_plan_unbound: renderer plan evidence has no "
                "selected FigurePlan."
            )
        return None

    if len(terminal_tasks) != len(terminal_requests):
        raise ValueError(
            "terminal_figure_task_missing: every terminal request for a selected "
            "FigurePlan must carry an exact FigureTask."
        )
    _validate_terminal_task_sequence(
        selected_plan=selected_plan,
        terminal_requests=terminal_requests,
        terminal_tasks=terminal_tasks,
    )
    completed_plan, reported_outcomes = _reported_plan_and_outcomes(
        selected_plan=selected_plan,
        result=result,
    )
    _validate_missing_task_outcomes(
        selected_plan=selected_plan,
        terminal_tasks=terminal_tasks,
        reported_outcomes=reported_outcomes,
        completed_plan=completed_plan,
    )
    return BoundTerminalFigureEvidence(
        selected_plan=selected_plan,
        terminal_tasks=terminal_tasks,
        reported_outcomes=reported_outcomes,
        completed_plan=completed_plan,
    )


def _normalized_terminal_requests(
    result: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    raw_requests = result.get("terminal_render_requests")
    if raw_requests is None:
        return ()
    if not isinstance(raw_requests, list):
        raise ValueError(
            "terminal_figure_task_invalid: terminal_render_requests must be a list."
        )
    return tuple(
        normalize_terminal_render_request(
            item,
            label=f"terminal render request {index}",
        )
        for index, item in enumerate(raw_requests, start=1)
    )


def _validate_terminal_task_sequence(
    *,
    selected_plan: ResolvedFigurePlan,
    terminal_requests: tuple[dict[str, Any], ...],
    terminal_tasks: tuple[FigureTask, ...],
) -> None:
    selected_by_id = {task.figure_id: task for task in selected_plan.tasks}
    terminal_ids = [task.figure_id for task in terminal_tasks]
    if len(set(terminal_ids)) != len(terminal_ids):
        raise ValueError(
            "terminal_figure_task_duplicate: one FigureTask has more than one "
            "terminal request."
        )
    unknown = [
        figure_id for figure_id in terminal_ids if figure_id not in selected_by_id
    ]
    if unknown:
        raise ValueError(
            "terminal_figure_task_unselected: terminal evidence references "
            f"unselected tasks: {unknown}."
        )
    selected_positions = {
        task.figure_id: index for index, task in enumerate(selected_plan.tasks)
    }
    positions = [selected_positions[figure_id] for figure_id in terminal_ids]
    if positions != sorted(positions):
        raise ValueError(
            "terminal_figure_task_reordered: terminal tasks do not follow "
            "FigurePlan order."
        )
    for request, task in zip(terminal_requests, terminal_tasks, strict=True):
        if request.get("rule_id") != selected_plan.rule_id:
            raise ValueError(
                "terminal_figure_rule_mismatch: terminal task rule identity does "
                "not match the selected FigurePlan."
            )
        if task != selected_by_id[task.figure_id]:
            raise ValueError(
                "terminal_figure_task_mismatch: terminal FigureTask payload does "
                "not match the selected FigurePlan."
            )


def _reported_plan_and_outcomes(
    *,
    selected_plan: ResolvedFigurePlan,
    result: dict[str, Any],
) -> tuple[ResolvedFigurePlan | None, tuple[FigureOutcome, ...]]:
    raw_plan = result.get("resolved_figure_plan")
    raw_outcomes = result.get("figure_outcomes")
    completed_plan = (
        ResolvedFigurePlan.from_payload(raw_plan) if raw_plan is not None else None
    )
    if completed_plan is not None and completed_plan.plan_id != selected_plan.plan_id:
        raise ValueError(
            "terminal_figure_plan_mismatch: renderer result plan does not match "
            "the selected FigurePlan."
        )
    if raw_outcomes is None:
        if completed_plan is not None:
            raise ValueError(
                "terminal_figure_outcome_mismatch: renderer result plan has no "
                "matching figure_outcomes projection."
            )
        return completed_plan, ()
    if not isinstance(raw_outcomes, list):
        raise ValueError(
            "terminal_figure_outcome_mismatch: figure_outcomes must be a list."
        )
    outcomes = tuple(FigureOutcome.from_payload(item) for item in raw_outcomes)
    if (
        tuple(outcome.figure_id for outcome in outcomes)
        != selected_plan.selected_figure_ids
    ):
        raise ValueError(
            "terminal_figure_outcome_mismatch: renderer outcomes do not follow "
            "the complete selected FigurePlan."
        )
    if any(outcome.status == "pending" for outcome in outcomes):
        raise ValueError(
            "terminal_figure_outcome_mismatch: a terminal renderer cannot report "
            "pending outcomes."
        )
    if completed_plan is not None and outcomes != completed_plan.outcomes:
        raise ValueError(
            "terminal_figure_outcome_mismatch: renderer outcome projection does "
            "not match its result plan."
        )
    return completed_plan, outcomes


def _validate_missing_task_outcomes(
    *,
    selected_plan: ResolvedFigurePlan,
    terminal_tasks: tuple[FigureTask, ...],
    reported_outcomes: tuple[FigureOutcome, ...],
    completed_plan: ResolvedFigurePlan | None,
) -> None:
    terminal_ids = {task.figure_id for task in terminal_tasks}
    missing_ids = [
        task.figure_id
        for task in selected_plan.tasks
        if task.figure_id not in terminal_ids
    ]
    if not missing_ids:
        return
    if completed_plan is None:
        raise ValueError(
            "terminal_figure_task_missing: source-unavailable omissions require "
            "the matching completed result plan."
        )
    outcomes_by_id = {outcome.figure_id: outcome for outcome in reported_outcomes}
    invalid_missing = [
        figure_id
        for figure_id in missing_ids
        if (
            (outcome := outcomes_by_id.get(figure_id)) is None
            or outcome.status != "unavailable"
            or outcome.reason_code not in SOURCE_UNAVAILABLE_WITHOUT_TERMINAL_EVIDENCE
        )
    ]
    if invalid_missing:
        raise ValueError(
            "terminal_figure_task_missing: selected tasks lack terminal evidence "
            f"without an explicit source-unavailable outcome: {invalid_missing}."
        )


__all__ = [
    "SOURCE_UNAVAILABLE_WITHOUT_TERMINAL_EVIDENCE",
    "BoundTerminalFigureEvidence",
    "bind_terminal_figure_evidence",
]
