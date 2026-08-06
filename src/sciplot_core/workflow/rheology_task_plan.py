"""Validate and project FigurePlan selections for rheology task sources."""

from __future__ import annotations

from typing import Any

from sciplot_core.figure_plan.metric_binding import CartesianMetricBinding
from sciplot_core.figure_plan.plan import (
    ResolvedFigurePlan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation


TEMPERATURE_RULE_ID = "rheology_temperature_sweep"
TEMPERATURE_METRICS = ("storage_modulus", "loss_factor")
TEMPERATURE_TASK_KEYS = {
    "storage_modulus": "storage_modulus_vs_temperature",
    "loss_factor": "tan_delta_vs_temperature",
}


def sweep_prefix_for_request(request: dict[str, Any]) -> str | None:
    """Return the stable artifact prefix for a supported sweep rule."""

    rule_id = str(request.get("rule_id") or "").strip()
    if rule_id == "rheology_frequency_sweep":
        return "freq"
    if rule_id == TEMPERATURE_RULE_ID:
        return "temp"
    return None


def selected_frequency_metric_keys(
    available_metrics: list[str],
    *,
    request: dict[str, Any],
) -> list[str]:
    """Project an optional frequency plan onto the available prepared metrics."""

    figure_plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    if figure_plan is None:
        return available_metrics
    if figure_plan.rule_id != "rheology_frequency_sweep":
        raise ValueError("Frequency bundle received a mismatched figure plan.")
    available = set(available_metrics)
    return [
        task.y_metric
        for task in figure_plan.tasks
        if task.y_metric is not None and task.y_metric in available
    ]


def temperature_plan_metric_keys(
    figure_plan: ResolvedFigurePlan,
    *,
    source_attestation: PreparationSourceAttestation,
) -> list[str]:
    """Validate the exact temperature plan and return its ordered metrics."""

    expected = (
        (
            "storage_modulus_vs_temperature",
            "temp_storage_modulus",
            "storage_modulus",
        ),
        ("tan_delta_vs_temperature", "temp_loss_factor", "loss_factor"),
    )
    if (
        figure_plan.rule_id != TEMPERATURE_RULE_ID
        or figure_plan.selection_policy != "default_storage_modulus_then_loss_factor"
        or figure_plan.primary_figure_id != expected[0][0]
        or len(figure_plan.tasks) != len(expected)
        or figure_plan.source_sha256 != source_attestation.source_tree_sha256_after
    ):
        raise ValueError(
            "temperature_figure_plan_mismatch: temperature task sources received "
            "a stale or non-canonical FigurePlan."
        )
    sample_order: tuple[str, ...] | None = None
    metric_keys: list[str] = []
    for task, (figure_id, artifact_stem, y_metric) in zip(
        figure_plan.tasks,
        expected,
        strict=True,
    ):
        binding = task.metric_binding
        if (
            task.figure_id != figure_id
            or task.order != len(metric_keys) + 1
            or task.template != "point_line"
            or task.artifact_stem != artifact_stem
            or not isinstance(binding, CartesianMetricBinding)
            or binding.x_metric != "temperature"
            or binding.y_metric != y_metric
            or not task.sample_order
            or tuple(sample for sample, _count in task.replicate_counts)
            != task.sample_order
        ):
            raise ValueError(
                "temperature_figure_plan_mismatch: temperature task identity, "
                "metrics, order, or sample binding is not canonical."
            )
        if sample_order is None:
            sample_order = task.sample_order
        elif task.sample_order != sample_order:
            raise ValueError(
                "temperature_figure_plan_mismatch: both temperature tasks must "
                "bind one source-derived sample order."
            )
        metric_keys.append(y_metric)
    return metric_keys


__all__ = [
    "TEMPERATURE_METRICS",
    "TEMPERATURE_RULE_ID",
    "TEMPERATURE_TASK_KEYS",
    "selected_frequency_metric_keys",
    "sweep_prefix_for_request",
    "temperature_plan_metric_keys",
]
