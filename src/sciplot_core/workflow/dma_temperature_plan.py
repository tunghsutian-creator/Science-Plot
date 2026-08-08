"""Validate the one executable DMA-temperature plan against its live source."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_ARTIFACT_STEM,
    DMA_TEMPERATURE_DOCUMENT_STEM,
    DMA_TEMPERATURE_FIGURE_ID,
    DMA_TEMPERATURE_RULE_ID,
    DMA_TEMPERATURE_SELECTION_POLICY,
    DMA_TEMPERATURE_TEMPLATE,
    DMA_TEMPERATURE_X_METRIC,
    DMA_TEMPERATURE_Y_METRIC,
)
from sciplot_core.figure_plan import CartesianMetricBinding, ResolvedFigurePlan
from sciplot_core.figure_plan.dma_temperature_resolution import (
    DmaTemperatureSourceFacts,
    load_dma_temperature_source_facts,
)


def require_dma_temperature_execution_plan(
    plan: ResolvedFigurePlan,
    *,
    source: Path,
) -> DmaTemperatureSourceFacts:
    """Return source facts only when every executable plan identity is exact."""

    if (
        plan.rule_id != DMA_TEMPERATURE_RULE_ID
        or plan.selection_policy != DMA_TEMPERATURE_SELECTION_POLICY
        or plan.primary_figure_id != DMA_TEMPERATURE_FIGURE_ID
        or len(plan.tasks) != 1
    ):
        _mismatch("plan identity or task cardinality")
    task = plan.tasks[0]
    if (
        task.figure_id != DMA_TEMPERATURE_FIGURE_ID
        or task.order != 1
        or task.template != DMA_TEMPERATURE_TEMPLATE
        or task.artifact_stem != DMA_TEMPERATURE_ARTIFACT_STEM
        or task.document_stem != DMA_TEMPERATURE_DOCUMENT_STEM
        or task.metric_binding
        != CartesianMetricBinding(
            x_metric=DMA_TEMPERATURE_X_METRIC,
            y_metric=DMA_TEMPERATURE_Y_METRIC,
        )
        or task.conditions
        or task.condition_labels
    ):
        _mismatch("task, metric, template, or artifact identity")

    facts = load_dma_temperature_source_facts(source)
    if plan.source_sha256 != facts.source_sha256:
        raise ValueError(
            "dma_temperature_figure_plan_source_changed: the live DMA source "
            "does not match the selected FigurePlan."
        )
    if task.sample_order != facts.sample_order:
        _mismatch("sample order")
    expected_replicates = tuple((sample, 1) for sample in facts.sample_order)
    if task.replicate_counts != expected_replicates:
        _mismatch("sample replicate-count projection")
    return facts


def _mismatch(field: str) -> None:
    raise ValueError(
        "dma_temperature_figure_plan_mismatch: the selected FigurePlan has a "
        f"conflicting {field}."
    )


__all__ = [
    "DMA_TEMPERATURE_SELECTION_POLICY",
    "require_dma_temperature_execution_plan",
]
