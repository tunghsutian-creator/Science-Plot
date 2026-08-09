"""Resolve mechanical source facts into one exact ordered FigurePlan."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from sciplot_core.mechanical_figure_contract import (
    MechanicalRuleFigureContract,
    mechanical_figure_contract,
    mechanical_selection_policy,
)

from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.metric_binding import CartesianMetricBinding
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask


if TYPE_CHECKING:
    from sciplot_core.semantic_sources.mechanical_facts import MechanicalSourceFacts


_REPLICATE_MODE_ALIASES = {
    "all": "individual",
    "average": "mean",
    "avg": "mean",
    "best": "representative",
}


def resolve_mechanical_plan(
    *,
    input_path: Path,
    rule_id: str,
    template: str,
    study_model: dict[str, Any],
    request: dict[str, Any],
) -> ResolvedFigurePlan:
    """Bind curve and every accepted descriptive summary to raw source facts."""

    contract = mechanical_figure_contract(rule_id)
    _validate_template(contract, template=template, request=request)
    _validate_study_model_queue(contract, study_model=study_model)
    replicate_mode = _resolved_replicate_mode(
        contract,
        study_model=study_model,
        request=request,
    )
    from sciplot_core.semantic_sources.mechanical_facts import (
        MechanicalSourceFactsError,
        load_mechanical_source_facts,
    )

    try:
        facts = load_mechanical_source_facts(
            input_path,
            rule_id=rule_id,
            series_order=request.get("series_order"),
        )
    except FigurePlanResolutionError:
        raise
    except MechanicalSourceFactsError as exc:
        raise FigurePlanResolutionError(exc.reason_code, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "mechanical_source_contract_invalid",
            f"The {rule_id} source could not be resolved without loss: {exc}",
        ) from exc
    _validate_source_facts(contract, facts=facts)
    try:
        curve_series = facts.curve_series_for_mode(replicate_mode)
    except MechanicalSourceFactsError as exc:
        raise FigurePlanResolutionError(exc.reason_code, str(exc)) from exc
    except ValueError as exc:
        raise FigurePlanResolutionError(
            "mechanical_replicate_mode_invalid",
            str(exc),
        ) from exc
    curve_sample_order = tuple(series.sample for series in curve_series)
    if not curve_sample_order or len(curve_sample_order) != len(
        set(curve_sample_order)
    ):
        _fail(
            "mechanical_curve_sample_identity_invalid",
            "Mechanical curve series must have non-empty unique display identities.",
        )
    if replicate_mode == "representative":
        if curve_sample_order != facts.sample_order:
            _fail(
                "mechanical_representative_order_mismatch",
                "Representative curve order does not match the source-derived "
                "mechanical sample order.",
            )
        curve_replicate_counts = facts.replicate_counts
    else:
        curve_replicate_counts = tuple((sample, 1) for sample in curve_sample_order)

    tasks: list[FigureTask] = []
    for order, task_contract in enumerate(contract.tasks, start=1):
        is_curve = order == 1
        tasks.append(
            FigureTask.with_metric_binding(
                figure_id=task_contract.figure_id,
                order=order,
                title=task_contract.title,
                metric_binding=CartesianMetricBinding(
                    x_metric=task_contract.x_metric,
                    y_metric=task_contract.y_metric,
                ),
                template=task_contract.template,
                artifact_stem=task_contract.artifact_stem,
                document_stem=task_contract.document_stem,
                sample_order=(curve_sample_order if is_curve else facts.sample_order),
                replicate_counts=(
                    curve_replicate_counts if is_curve else facts.replicate_counts
                ),
            )
        )
    return ResolvedFigurePlan.planned(
        rule_id=rule_id,
        selection_policy=mechanical_selection_policy(replicate_mode),
        primary_figure_id=contract.primary_task.figure_id,
        tasks=tuple(tasks),
        source_sha256=facts.source_sha256,
    )


def _validate_template(
    contract: MechanicalRuleFigureContract,
    *,
    template: str,
    request: dict[str, Any],
) -> None:
    expected = contract.primary_task.template
    candidates = [template]
    if request.get("template") is not None:
        candidates.append(str(request.get("template") or "").strip())
    if any(candidate != expected for candidate in candidates):
        _fail(
            "mechanical_template_invalid",
            f"The {contract.rule_id} FigurePlan requires primary template "
            f"{expected!r}; every summary task is fixed separately by contract.",
        )


def _validate_study_model_queue(
    contract: MechanicalRuleFigureContract,
    *,
    study_model: dict[str, Any],
) -> None:
    raw_queue = study_model.get("figure_queue")
    if raw_queue is None:
        return
    if not isinstance(raw_queue, list | tuple):
        _fail(
            "mechanical_study_model_queue_invalid",
            "Mechanical Study Model figure_queue must be an ordered list.",
        )
    if len(raw_queue) != len(contract.tasks):
        _fail(
            "mechanical_study_model_queue_mismatch",
            "Mechanical Study Model must select the complete shared task sequence.",
        )
    for value, expected in zip(raw_queue, contract.tasks, strict=True):
        if not isinstance(value, dict):
            _fail(
                "mechanical_study_model_queue_invalid",
                "Every mechanical Study Model queue entry must be an object.",
            )
        observed = (
            str(value.get("id") or "").strip(),
            str(value.get("x_metric") or "").strip(),
            str(value.get("y_metric") or value.get("metric") or "").strip(),
            str(value.get("default_template") or "").strip(),
        )
        required = (
            expected.figure_id,
            expected.x_metric,
            expected.y_metric,
            expected.template,
        )
        if observed != required:
            _fail(
                "mechanical_study_model_queue_mismatch",
                "Mechanical Study Model task identity, order, metric, or template "
                "does not match the shared contract.",
            )
        statistics_method = expected.statistics_method
        if statistics_method is not None and value.get("statistics_method") != (
            statistics_method
        ):
            _fail(
                "mechanical_statistics_method_mismatch",
                "Mechanical summary statistics must be the confirmed median/IQR "
                "method with visible raw points.",
            )


def _resolved_replicate_mode(
    contract: MechanicalRuleFigureContract,
    *,
    study_model: dict[str, Any],
    request: dict[str, Any],
) -> str:
    request_value = request.get("replicate_mode")
    policy = study_model.get("replicate_policy")
    study_value = policy.get("mode") if isinstance(policy, dict) else None
    observed = [
        _normalize_replicate_mode(value)
        for value in (request_value, study_value)
        if value is not None and str(value).strip()
    ]
    if len(set(observed)) > 1:
        _fail(
            "mechanical_replicate_mode_conflict",
            "Request and Study Model mechanical replicate modes disagree.",
        )
    mode = observed[0] if observed else contract.default_replicate_mode
    if mode == "mean":
        _fail(
            "mechanical_mean_curve_unsupported",
            "Mechanical curves cannot be averaged pointwise; select the confirmed "
            "representative curve or render every individual specimen curve.",
        )
    if mode not in {"representative", "individual"}:
        _fail(
            "mechanical_replicate_mode_invalid",
            "Mechanical curve replicate_mode must be representative or individual.",
        )
    return mode


def _normalize_replicate_mode(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    return _REPLICATE_MODE_ALIASES.get(normalized, normalized)


def _validate_source_facts(
    contract: MechanicalRuleFigureContract,
    *,
    facts: MechanicalSourceFacts,
) -> None:
    if facts.rule_id != contract.rule_id:
        _fail(
            "mechanical_source_rule_mismatch",
            "Mechanical source facts belong to a different semantic rule.",
        )
    if not facts.source_sha256:
        _fail(
            "mechanical_source_unavailable",
            "Mechanical source facts do not include an exact source-tree SHA-256.",
        )
    if (
        not facts.sample_order
        or tuple(sample for sample, _count in facts.replicate_counts)
        != facts.sample_order
    ):
        _fail(
            "mechanical_source_sample_contract_invalid",
            "Mechanical source sample order and replicate counts are incomplete.",
        )
    if any(count < 1 for _sample, count in facts.replicate_counts):
        _fail(
            "mechanical_source_sample_contract_invalid",
            "Every mechanical sample must retain at least one raw specimen.",
        )
    primary = contract.primary_task
    if (
        facts.x_label != primary.source_x_label
        or facts.x_unit != primary.x_unit
        or facts.y_label != primary.source_y_label
        or facts.y_unit != primary.y_unit
    ):
        _fail(
            "mechanical_source_unit_mismatch",
            "Mechanical source curve labels or units disagree with the shared "
            "FigurePlan contract.",
        )
    metric_units = dict(facts.metric_units)
    for task in contract.summary_tasks:
        if metric_units.get(task.y_metric) != task.y_unit:
            _fail(
                "mechanical_source_unit_mismatch",
                f"Source metric {task.y_metric!r} does not have required unit "
                f"{task.y_unit!r}.",
            )
    records = facts.summary_records()
    expected_count = sum(count for _sample, count in facts.replicate_counts)
    if len(records) != expected_count:
        _fail(
            "mechanical_summary_replicate_count_mismatch",
            "Mechanical summary observations do not match the retained raw "
            "specimen counts.",
        )
    expected_metrics = {task.y_metric for task in contract.summary_tasks}
    if any(not expected_metrics <= set(record) for record in records):
        _fail(
            "mechanical_summary_metric_missing",
            "A retained mechanical specimen is missing a required summary metric.",
        )


def _fail(reason_code: str, message: str) -> NoReturn:
    raise FigurePlanResolutionError(reason_code, message)


__all__ = ["resolve_mechanical_plan"]
