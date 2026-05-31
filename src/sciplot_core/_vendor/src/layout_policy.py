from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

LayoutObjectKind = str


@dataclass(frozen=True)
class LayoutCandidate:
    candidate_id: str
    anchor: tuple[float, float] | None = None
    standoff_pt: float = 0.0
    payload: Any = None
    notes: str = ""


@dataclass(frozen=True)
class LayoutScore:
    score: float
    blocked: bool = False
    reason: str = ""


@dataclass(frozen=True)
class LayoutEvaluation:
    candidate: LayoutCandidate
    score: float
    blocked: bool
    reason: str


@dataclass(frozen=True)
class LayoutDecision:
    object_kind: LayoutObjectKind
    chosen_candidate: LayoutCandidate | None
    chosen_score: float | None
    reason: str
    evaluations: tuple[LayoutEvaluation, ...]
    fallback_action: str | None = None
    fallback_reason: str | None = None
    context: dict[str, Any] | None = None


ScoreHook = Callable[[LayoutCandidate], LayoutScore]
FallbackHook = Callable[
    [Sequence[LayoutCandidate], Sequence[LayoutEvaluation], LayoutEvaluation | None],
    tuple[LayoutCandidate, float, str] | None,
]
FallbackTrigger = Callable[[LayoutEvaluation | None, Sequence[LayoutEvaluation]], bool]


def choose_layout_candidate(
    *,
    object_kind: LayoutObjectKind,
    candidates: Sequence[LayoutCandidate],
    score_hook: ScoreHook,
    fallback_hook: FallbackHook | None = None,
    fallback_trigger: FallbackTrigger | None = None,
) -> LayoutDecision:
    evaluations: list[LayoutEvaluation] = []
    for candidate in candidates:
        scored = score_hook(candidate)
        evaluations.append(
            LayoutEvaluation(
                candidate=candidate,
                score=float(scored.score),
                blocked=bool(scored.blocked),
                reason=scored.reason,
            )
        )

    viable = [evaluation for evaluation in evaluations if not evaluation.blocked]
    best = min(viable, key=lambda item: item.score) if viable else None

    should_try_fallback = best is None
    if not should_try_fallback and fallback_trigger is not None:
        should_try_fallback = bool(fallback_trigger(best, evaluations))

    if should_try_fallback and fallback_hook is not None:
        fallback = fallback_hook(candidates, evaluations, best)
        if fallback is not None:
            chosen_candidate, chosen_score, fallback_reason = fallback
            return LayoutDecision(
                object_kind=object_kind,
                chosen_candidate=chosen_candidate,
                chosen_score=float(chosen_score),
                reason="fallback_selected",
                evaluations=tuple(evaluations),
                fallback_action="fallback_hook",
                fallback_reason=fallback_reason,
            )

    if best is None:
        return LayoutDecision(
            object_kind=object_kind,
            chosen_candidate=None,
            chosen_score=None,
            reason="no_viable_candidate",
            evaluations=tuple(evaluations),
        )

    return LayoutDecision(
        object_kind=object_kind,
        chosen_candidate=best.candidate,
        chosen_score=float(best.score),
        reason="best_score",
        evaluations=tuple(evaluations),
    )


def flag_margin_fallback(decision: LayoutDecision, *, action: str, reason: str) -> LayoutDecision:
    return replace(decision, fallback_action=action, fallback_reason=reason)


def empty_layout_decision(object_kind: LayoutObjectKind, *, reason: str) -> LayoutDecision:
    return LayoutDecision(
        object_kind=object_kind,
        chosen_candidate=None,
        chosen_score=None,
        reason=reason,
        evaluations=(),
    )


def record_layout_decision(
    target: Any,
    decision: LayoutDecision,
    *,
    context: dict[str, Any] | None = None,
) -> None:
    records = getattr(target, "_sciplot_layout_debug", None)
    if not isinstance(records, list):
        records = []
    if context:
        merged_context = dict(decision.context or {})
        merged_context.update(context)
        decision = replace(decision, context=merged_context)
    records.append(_decision_to_dict(decision))
    target._sciplot_layout_debug = records


def _decision_to_dict(decision: LayoutDecision) -> dict[str, Any]:
    return {
        "object_kind": decision.object_kind,
        "reason": decision.reason,
        "chosen_candidate_id": decision.chosen_candidate.candidate_id if decision.chosen_candidate else None,
        "chosen_anchor": decision.chosen_candidate.anchor if decision.chosen_candidate else None,
        "chosen_standoff_pt": decision.chosen_candidate.standoff_pt if decision.chosen_candidate else None,
        "chosen_score": decision.chosen_score,
        "fallback_action": decision.fallback_action,
        "fallback_reason": decision.fallback_reason,
        "context": dict(decision.context or {}),
        "candidates": [
            {
                "candidate_id": evaluation.candidate.candidate_id,
                "anchor": evaluation.candidate.anchor,
                "standoff_pt": evaluation.candidate.standoff_pt,
                "blocked": evaluation.blocked,
                "score": evaluation.score,
                "reason": evaluation.reason,
                "notes": evaluation.candidate.notes,
            }
            for evaluation in decision.evaluations
        ],
    }
