"""Project and verify exact FigureTasks across Studio queue, registry, and specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sciplot_core.figure_plan.metric_binding import (
    CartesianMetricBinding,
    OrderedMetricsBinding,
)
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.studio_figure_set_contract import (
    STUDIO_FIGURE_SET_KIND,
    STUDIO_FIGURE_SET_TASK_VERSION,
)


_METRIC_PROJECTION_FIELDS = frozenset({"metric", "x_metric", "y_metric", "metric_ids"})


def figure_task_metric_projection(
    task: FigureTask,
    *,
    include_singular_metric: bool,
) -> dict[str, Any]:
    """Return the only compatible flat metric view of one exact task."""

    binding = task.metric_binding
    if binding is None:
        assert task.x_metric is not None
        assert task.y_metric is not None
        binding = CartesianMetricBinding(
            x_metric=task.x_metric,
            y_metric=task.y_metric,
        )
    if isinstance(binding, CartesianMetricBinding):
        projection: dict[str, Any] = {
            "x_metric": binding.x_metric,
            "y_metric": binding.y_metric,
        }
        if include_singular_metric:
            projection["metric"] = binding.y_metric
        return projection
    if isinstance(binding, OrderedMetricsBinding):
        return {"metric_ids": list(binding.metric_ids)}
    raise ValueError("studio_figure_task_mismatch: unsupported metric binding.")


def figure_queue_item_from_task(task: FigureTask) -> dict[str, Any]:
    """Build one task-authoritative queue item with bounded compatibility fields."""

    return {
        "id": task.figure_id,
        "order": task.order,
        "title": task.title,
        **figure_task_metric_projection(task, include_singular_metric=True),
        "default_template": task.template,
        "artifact_stem": task.artifact_stem,
        "document_stem": task.document_stem,
        "conditions": list(task.conditions),
        "condition_labels": list(task.condition_labels),
        "sample_order": list(task.sample_order),
        "resolved_figure_task": task.to_payload(),
    }


def figure_queue_from_plan(
    figure_plan: ResolvedFigurePlan | None,
    rule_id: str,
) -> list[dict[str, Any]]:
    """Project one supported rule's exact ordered plan into a Studio queue."""

    if figure_plan is None or figure_plan.rule_id != rule_id:
        return []
    return [figure_queue_item_from_task(task) for task in figure_plan.tasks]


def generic_figure_queue_from_plan(
    figure_plan: ResolvedFigurePlan | None,
    *,
    render_adapter: str | None,
) -> list[dict[str, Any]]:
    """Project one exact task only for a rule owned by the generic renderer."""

    if figure_plan is None or render_adapter != "generic":
        return []
    if len(figure_plan.tasks) != 1:
        raise ValueError(
            "studio_generic_single_task_plan_mismatch: generic Studio rendering "
            "requires exactly one selected task."
        )
    return figure_queue_from_plan(figure_plan, figure_plan.rule_id)


def figure_registry_projection_from_task(task: FigureTask) -> dict[str, Any]:
    """Build the task-owned fields of one v2 figure-set registry entry."""

    return {
        "figure_id": task.figure_id,
        "title": task.title,
        **figure_task_metric_projection(task, include_singular_metric=True),
        "template": task.template,
        "order": task.order,
        "artifact_stem": task.artifact_stem,
        "document_stem": task.document_stem,
        "resolved_figure_task": task.to_payload(),
    }


def figure_task_from_queue_item(
    value: Mapping[str, Any],
    *,
    required: bool = False,
) -> FigureTask | None:
    """Parse a task-aware queue item; only complete absence is legacy."""

    return _task_from_projection(
        value,
        required=required,
        projection_builder=figure_queue_item_from_task,
        source="Studio figure queue item",
    )


def figure_task_from_registry_entry(
    value: Mapping[str, Any],
    *,
    required: bool = False,
) -> FigureTask | None:
    """Parse one task-aware v2 registry entry and verify its flat projection."""

    return _task_from_projection(
        value,
        required=required,
        projection_builder=figure_registry_projection_from_task,
        source="Studio figure-set registry entry",
    )


def _task_from_projection(
    value: Mapping[str, Any],
    *,
    required: bool,
    projection_builder: Any,
    source: str,
) -> FigureTask | None:
    if not isinstance(value, Mapping):
        raise ValueError(f"studio_figure_task_mismatch: {source} must be an object.")
    if "resolved_figure_task" not in value:
        if required:
            raise ValueError(
                "studio_figure_task_mismatch: "
                f"{source} is missing resolved_figure_task."
            )
        return None
    payload = value.get("resolved_figure_task")
    try:
        task = FigureTask.from_payload(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"studio_figure_task_mismatch: {source} contains an invalid FigureTask."
        ) from exc
    if payload != task.to_payload():
        raise ValueError(
            f"studio_figure_task_mismatch: {source} FigureTask is not canonical."
        )
    expected = projection_builder(task)
    for key, expected_value in expected.items():
        if key not in value or value.get(key) != expected_value:
            raise ValueError(
                "studio_figure_task_mismatch: "
                f"{source} field `{key}` disagrees with its exact FigureTask."
            )
    expected_metric_fields = _METRIC_PROJECTION_FIELDS & set(expected)
    actual_metric_fields = _METRIC_PROJECTION_FIELDS & set(value)
    if actual_metric_fields != expected_metric_fields:
        raise ValueError(
            "studio_figure_task_mismatch: "
            f"{source} mixes incompatible metric projection fields."
        )
    return task


def validate_figure_queue_against_plan(
    queue: Sequence[Mapping[str, Any]],
    plan: ResolvedFigurePlan,
) -> tuple[FigureTask, ...]:
    """Require one canonical same-order queue item for every selected task."""

    try:
        tasks = tuple(
            task
            for value in queue
            if (task := figure_task_from_queue_item(value, required=True)) is not None
        )
    except (TypeError, ValueError) as exc:
        if str(exc).startswith("studio_figure_task_mismatch:"):
            raise
        raise ValueError(
            "studio_figure_task_mismatch: Studio figure queue is invalid."
        ) from exc
    if tasks != plan.tasks:
        raise ValueError(
            "studio_figure_task_mismatch: Studio figure queue does not match "
            "the selected FigurePlan tasks in exact order."
        )
    return tasks


def validate_figure_registry_against_plan(
    registry: Mapping[str, Any],
    plan: ResolvedFigurePlan,
) -> tuple[FigureTask, ...]:
    """Require a strict v2 registry projection of the selected task sequence."""

    if (
        registry.get("kind") != STUDIO_FIGURE_SET_KIND
        or registry.get("version") != STUDIO_FIGURE_SET_TASK_VERSION
    ):
        raise ValueError(
            "studio_figure_task_mismatch: task-aware figure registry must be v2."
        )
    if (
        registry.get("rule_id") != plan.rule_id
        or registry.get("primary_figure_id") != plan.primary_figure_id
        or registry.get("plan_id") != plan.plan_id
        or registry.get("plan_sha256") != plan.plan_sha256
    ):
        raise ValueError(
            "studio_figure_task_mismatch: figure registry identity does not "
            "match the selected FigurePlan."
        )
    figures = registry.get("figures")
    if not isinstance(figures, list):
        raise ValueError(
            "studio_figure_task_mismatch: figure registry entries must be a list."
        )
    try:
        tasks = tuple(
            task
            for value in figures
            if (
                task := figure_task_from_registry_entry(
                    value,
                    required=True,
                )
            )
            is not None
        )
    except (TypeError, ValueError) as exc:
        if str(exc).startswith("studio_figure_task_mismatch:"):
            raise
        raise ValueError(
            "studio_figure_task_mismatch: figure registry entries are invalid."
        ) from exc
    if tasks != plan.tasks:
        raise ValueError(
            "studio_figure_task_mismatch: figure registry tasks do not match "
            "the selected FigurePlan in exact order."
        )
    return tasks


def primary_figure_task(plan: ResolvedFigurePlan) -> FigureTask:
    """Return the declared primary task without assuming list position or metric."""

    return next(task for task in plan.tasks if task.figure_id == plan.primary_figure_id)


def validate_veusz_spec_figure_task(
    spec: Mapping[str, Any],
    *,
    expected: FigureTask,
    source: str,
) -> None:
    """Bind one generated spec to its exact task and task-owned metric fields."""

    if spec.get("template") != expected.template:
        raise RuntimeError(
            "studio_figure_task_mismatch: "
            f"{source} template does not match its exact FigureTask."
        )
    source_request = spec.get("source_request")
    if not isinstance(source_request, Mapping):
        raise RuntimeError(
            "studio_figure_task_mismatch: "
            f"{source} is missing its task-bound source request."
        )
    if source_request.get("template") != expected.template:
        raise RuntimeError(
            "studio_figure_task_mismatch: "
            f"{source} source request template does not match its FigureTask."
        )
    payload = source_request.get("resolved_figure_task")
    try:
        actual = FigureTask.from_payload(payload)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "studio_figure_task_mismatch: "
            f"{source} source request contains an invalid FigureTask."
        ) from exc
    if actual != expected or payload != expected.to_payload():
        raise RuntimeError(
            "studio_figure_task_mismatch: "
            f"{source} source request does not match the selected FigureTask."
        )
    expected_metrics = figure_task_metric_projection(
        expected,
        include_singular_metric=False,
    )
    actual_metric_fields = _METRIC_PROJECTION_FIELDS & set(source_request)
    if actual_metric_fields != set(expected_metrics) or any(
        source_request.get(key) != value for key, value in expected_metrics.items()
    ):
        raise RuntimeError(
            "studio_figure_task_mismatch: "
            f"{source} source request metric projection is stale or mixed."
        )


__all__ = [
    "generic_figure_queue_from_plan",
    "figure_queue_from_plan",
    "figure_queue_item_from_task",
    "figure_registry_projection_from_task",
    "figure_task_from_queue_item",
    "figure_task_from_registry_entry",
    "figure_task_metric_projection",
    "primary_figure_task",
    "validate_figure_queue_against_plan",
    "validate_figure_registry_against_plan",
    "validate_veusz_spec_figure_task",
]
