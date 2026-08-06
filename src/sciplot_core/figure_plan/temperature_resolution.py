"""Resolve temperature-rheology source facts into two canonical tasks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.metric_binding import CartesianMetricBinding
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.source_binding import source_tree_sha256
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.foundation.text_values import clean_text
from sciplot_core.semantic_sources.models import RheologySweepSample
from sciplot_core.semantic_sources.rheology_ordering import _ordered_sweep_samples
from sciplot_core.semantic_sources.rheology_replicates import (
    _coalesce_replicate_sweep_samples,
)
from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _read_rheology_temperature_comparison_samples,
)


TEMPERATURE_RULE_ID = "rheology_temperature_sweep"
TEMPERATURE_SAMPLE_METRICS = ("storage_modulus", "loss_factor")


@dataclass(frozen=True, slots=True)
class TemperatureSourceFacts:
    """One stable, prepared-order view of the selected raw sweep sources."""

    source_sha256: str
    sample_order: tuple[str, ...]
    replicate_counts: tuple[tuple[str, int], ...]


def resolve_temperature_plan(
    *,
    input_path: Path,
    request: dict[str, Any],
) -> ResolvedFigurePlan:
    """Resolve the fixed two-task temperature plan from one source-facts load."""

    facts = load_temperature_source_facts(input_path=input_path, request=request)
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
    """Parse one stable raw snapshot and project its exact prepared sample order."""

    source = input_path.expanduser().resolve()
    source_sha256_before = source_tree_sha256(source)
    if source_sha256_before is None:
        raise FigurePlanResolutionError(
            "temperature_source_unavailable",
            "SciPlot could not fingerprint the rheology-temperature source.",
        )
    try:
        raw_samples = _read_rheology_temperature_comparison_samples(source)
    except (OSError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "temperature_source_unavailable",
            f"SciPlot could not read the rheology-temperature source: {exc}",
        ) from exc
    source_sha256_after = source_tree_sha256(source)
    if source_sha256_after != source_sha256_before:
        raise FigurePlanResolutionError(
            "temperature_source_changed_during_resolution",
            "The rheology-temperature source changed while its FigurePlan was "
            "being resolved.",
        )

    prepared_samples = _coalesce_replicate_sweep_samples(
        raw_samples,
        replicate_mode=request.get("replicate_mode"),
    )
    prepared_samples = _ordered_sweep_samples(
        prepared_samples,
        series_order=request.get("series_order"),
    )
    if not prepared_samples:
        raise FigurePlanResolutionError(
            "temperature_source_unavailable",
            "The rheology-temperature source has no selected samples.",
        )
    sample_order = tuple(sample.sample for sample in prepared_samples)
    if len(set(sample_order)) != len(sample_order):
        raise FigurePlanResolutionError(
            "temperature_sample_identity_ambiguous",
            "The prepared rheology-temperature samples do not have unique labels.",
        )
    _require_temperature_metrics(prepared_samples)

    raw_counts = Counter(_replicate_key(sample) for sample in raw_samples)
    replicate_counts = tuple(
        (sample.sample, raw_counts[_replicate_key(sample)])
        for sample in prepared_samples
    )
    if any(count < 1 for _sample, count in replicate_counts):
        raise FigurePlanResolutionError(
            "temperature_sample_identity_ambiguous",
            "A prepared rheology-temperature sample lost its raw replicate identity.",
        )
    return TemperatureSourceFacts(
        source_sha256=source_sha256_after,
        sample_order=sample_order,
        replicate_counts=replicate_counts,
    )


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


def _require_temperature_metrics(samples: list[RheologySweepSample]) -> None:
    missing: list[str] = []
    for sample in samples:
        absent = [
            metric
            for metric in TEMPERATURE_SAMPLE_METRICS
            if not any("x" in row and metric in row for row in sample.rows)
        ]
        if absent:
            missing.append(f"{sample.sample}: {', '.join(absent)}")
    if missing:
        raise FigurePlanResolutionError(
            "temperature_metric_source_unavailable",
            "The selected temperature samples do not all contain storage modulus "
            f"and loss factor ({'; '.join(missing)}).",
        )


def _replicate_key(sample: RheologySweepSample) -> str:
    return clean_text(sample.sample) or sample.source.stem


__all__ = [
    "TEMPERATURE_RULE_ID",
    "TEMPERATURE_SAMPLE_METRICS",
    "TemperatureSourceFacts",
    "load_temperature_source_facts",
    "resolve_temperature_plan",
]
