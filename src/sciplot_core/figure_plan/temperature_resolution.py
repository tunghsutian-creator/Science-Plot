"""Project one resolved temperature-rheology domain into canonical tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.metric_binding import CartesianMetricBinding
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.semantic_sources.rheology_temperature_domain import (
    TEMPERATURE_RULE_ID,
    TEMPERATURE_SAMPLE_METRICS,
    ResolvedRheologyTemperatureDomain,
    RheologyTemperatureDomainError,
    TemperatureSourceFacts,
    resolve_rheology_temperature_domain,
)


def resolve_temperature_plan(
    *,
    input_path: Path,
    request: dict[str, Any],
    source_resolution: ResolvedRheologyTemperatureDomain | None = None,
) -> ResolvedFigurePlan:
    """Resolve the fixed two-task plan from one typed source domain."""

    resolved_source = source_resolution or _resolve_temperature_domain(
        input_path=input_path,
        request=request,
    )
    if resolved_source.source != input_path.expanduser().resolve():
        raise FigurePlanResolutionError(
            "temperature_source_mismatch",
            "The resolved rheology-temperature domain belongs to another source.",
        )
    facts = resolved_source.facts
    tasks = (
        _temperature_task(
            figure_id="storage_modulus_vs_temperature",
            order=1,
            title="Storage modulus vs temperature",
            y_metric="storage_modulus",
            artifact_stem="temp_storage_modulus",
            facts=facts,
        ),
        _temperature_task(
            figure_id="tan_delta_vs_temperature",
            order=2,
            title="tan delta vs temperature",
            y_metric="loss_factor",
            artifact_stem="temp_loss_factor",
            facts=facts,
        ),
    )
    return ResolvedFigurePlan.planned(
        rule_id=TEMPERATURE_RULE_ID,
        selection_policy="default_storage_modulus_then_loss_factor",
        primary_figure_id=tasks[0].figure_id,
        tasks=tasks,
        source_sha256=facts.source_sha256,
    )


def load_temperature_source_facts(
    *,
    input_path: Path,
    request: dict[str, Any],
) -> TemperatureSourceFacts:
    """Resolve one typed source domain and return its FigurePlan facts."""

    return _resolve_temperature_domain(
        input_path=input_path,
        request=request,
    ).facts


def _resolve_temperature_domain(
    *,
    input_path: Path,
    request: dict[str, Any],
) -> ResolvedRheologyTemperatureDomain:
    try:
        return resolve_rheology_temperature_domain(input_path, request=request)
    except RheologyTemperatureDomainError as exc:
        raise FigurePlanResolutionError(exc.reason_code, str(exc)) from exc


def _temperature_task(
    *,
    figure_id: str,
    order: int,
    title: str,
    y_metric: str,
    artifact_stem: str,
    facts: TemperatureSourceFacts,
) -> FigureTask:
    return FigureTask.with_metric_binding(
        figure_id=figure_id,
        order=order,
        title=title,
        metric_binding=CartesianMetricBinding(
            x_metric="temperature",
            y_metric=y_metric,
        ),
        template="point_line",
        artifact_stem=artifact_stem,
        document_stem=figure_id,
        sample_order=facts.sample_order,
        replicate_counts=facts.replicate_counts,
    )


__all__ = [
    "TEMPERATURE_RULE_ID",
    "TEMPERATURE_SAMPLE_METRICS",
    "ResolvedRheologyTemperatureDomain",
    "TemperatureSourceFacts",
    "load_temperature_source_facts",
    "resolve_temperature_plan",
]
