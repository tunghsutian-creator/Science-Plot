"""Build rheology and impact figure queues and per-figure render requests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    FigureTask,
    ResolvedFigurePlan,
    request_for_figure_task,
    resolve_figure_plan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.materials_rules import (
    resolve_rule_template,
)
from sciplot_core.policy import (
    rheology_metric_axis_label,
)
from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
)
from sciplot_core.studio_render.template_resolution import (
    _request_template,
)
from sciplot_core.studio_render.value_parsing import (
    _string_list,
)

from sciplot_core.studio_core.request_paths import (
    _resolve_request_input,
)
from sciplot_core.studio_core.figure_task_evidence import (
    figure_queue_item_from_task,
    figure_task_from_queue_item,
)


def _rheology_frequency_figure_queue(
    request: dict[str, Any],
    *,
    figure_plan: ResolvedFigurePlan | None = None,
) -> list[dict[str, Any]]:
    """Return the bounded, independent-document frequency-sweep queue."""

    if str(request.get("rule_id") or "").strip() != "rheology_frequency_sweep":
        return []
    plan = figure_plan or resolved_figure_plan_from_payload(
        request.get("resolved_figure_plan")
    )
    if plan is None:
        plan = resolve_figure_plan(
            rule_id="rheology_frequency_sweep",
            template="point_line",
            study_model=(
                request.get("study_model")
                if isinstance(request.get("study_model"), dict)
                else {}
            ),
            input_path=None,
            request=request,
        )
    if plan is None or plan.rule_id != "rheology_frequency_sweep":
        return []
    return [_queue_item_from_task(task) for task in plan.tasks]


def _rheology_frequency_figure_request(
    request: dict[str, Any],
    figure: dict[str, Any],
) -> dict[str, Any]:
    task = _task_from_queue_item(figure)
    figure_request = (
        request_for_figure_task(request, task)
        if task is not None
        else deepcopy(request)
    )
    if task is None:
        figure_request["x_metric"] = str(figure["x_metric"])
        figure_request["y_metric"] = str(figure["y_metric"])
        figure_request["template"] = str(figure.get("default_template") or "point_line")
    y_metric_value = figure_request.get("y_metric")
    if not isinstance(y_metric_value, str) or not y_metric_value.strip():
        raise ValueError(
            "studio_figure_task_mismatch: frequency figure requires a "
            "Cartesian y metric."
        )
    y_metric = y_metric_value.strip()
    render_options = (
        dict(figure_request.get("render_options"))
        if isinstance(figure_request.get("render_options"), dict)
        else {}
    )
    render_options["size"] = "60x55"
    explicit_render_keys = {
        str(value)
        for value in (
            figure_request.get("explicit_render_option_keys")
            if isinstance(
                figure_request.get("explicit_render_option_keys"),
                list,
            )
            else []
        )
    }
    if y_metric == "loss_factor":
        if "yscale" not in explicit_render_keys:
            render_options["yscale"] = "linear"
        if (
            str(render_options.get("yscale") or "").casefold() != "log"
            and "y_tick_format" not in explicit_render_keys
        ):
            render_options.pop("y_tick_format", None)
    metric_label = rheology_metric_axis_label(y_metric)
    if y_metric == "complex_viscosity":
        metric_label = "|\\eta^{*}| (mPa·s)"
    if metric_label is not None:
        render_options["y_label_override"] = metric_label
    figure_request["render_options"] = render_options
    return figure_request


def _rheology_frequency_primary_request(
    request: dict[str, Any],
    *,
    figure_plan: ResolvedFigurePlan | None = None,
) -> dict[str, Any]:
    queue = _rheology_frequency_figure_queue(
        request,
        figure_plan=figure_plan,
    )
    primary = (
        next(
            (item for item in queue if item.get("id") == figure_plan.primary_figure_id),
            None,
        )
        if figure_plan is not None
        else next(
            (item for item in queue if item.get("y_metric") == "storage_modulus"),
            None,
        )
    )
    return (
        _rheology_frequency_figure_request(request, primary)
        if primary is not None
        else request
    )


def _impact_condition_figure_queue(
    request: dict[str, Any],
    *,
    base_dir: Path,
    project_dir: Path,
    figure_plan: ResolvedFigurePlan | None = None,
) -> list[dict[str, Any]]:
    """Materialize one canonical categorical source per workbook condition."""

    if str(request.get("rule_id") or "").strip() != "impact_metric":
        return []
    if (
        request.get("resolved_figure_task") is not None
        and figure_plan is None
        and request.get("resolved_figure_plan") is None
    ):
        # A terminal worker executes its one bound task; it never reconstructs
        # the enclosing Studio figure-set queue.
        return []
    source = _resolve_request_input(request, base_dir=base_dir)
    if source is None:
        return []
    if source.is_dir():
        workbooks = sorted(
            path
            for path in source.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}
        )
        if len(workbooks) != 1:
            return []
        source = workbooks[0]
    if not source.is_file():
        return []
    plan = figure_plan or resolved_figure_plan_from_payload(
        request.get("resolved_figure_plan")
    )
    if plan is None:
        plan = resolve_figure_plan(
            rule_id="impact_metric",
            template=_request_template(request),
            study_model=(
                request.get("study_model")
                if isinstance(request.get("study_model"), dict)
                else {}
            ),
            input_path=source,
            request=request,
        )
    if plan is None or plan.rule_id != "impact_metric":
        return []
    if _request_template(request) == "point_line":
        if len(plan.tasks) != 1 or plan.tasks[0].template != "point_line":
            return []
        return [
            {
                **_queue_item_from_task(plan.tasks[0]),
                "condition_source": str(source),
                "supported_templates": ["point_line"],
                "presentation_data_shape": "condition_overlay_replicates",
            }
        ]
    if plan.selection_policy != "all_workbook_conditions":
        return []
    from sciplot_core.semantic import read_impact_condition_payloads

    conditions = dict(read_impact_condition_payloads(source))
    output_dir = project_dir / "studio" / "processed" / "impact_conditions"
    output_dir.mkdir(parents=True, exist_ok=True)
    queue: list[dict[str, Any]] = []
    for task in plan.tasks:
        condition = task.conditions[0]
        payload = conditions.get(condition)
        if payload is None:
            raise FigurePlanResolutionError(
                "impact_condition_source_changed",
                f"Resolved impact condition is no longer available: {condition}",
            )
        condition_source = output_dir / f"{task.document_stem}.csv"
        pd.DataFrame(payload.rows).to_csv(
            condition_source,
            header=False,
            index=False,
        )
        queue.append(
            {
                **_queue_item_from_task(task),
                "condition": str(condition),
                "condition_source": str(condition_source),
                "replicate_counts": dict(task.replicate_counts),
                "supported_templates": ["bar", "box", "box_strip", "point_line"],
                "presentation_data_shape": "categorical_replicates",
            }
        )
    return queue


def _impact_condition_figure_request(
    request: dict[str, Any],
    figure: dict[str, Any],
) -> dict[str, Any]:
    task = _task_from_queue_item(figure)
    figure_request = (
        request_for_figure_task(request, task)
        if task is not None
        else deepcopy(request)
    )
    figure_request["input"] = str(figure["condition_source"])
    if task is None:
        figure_request["template"] = resolve_rule_template(
            "impact_metric",
            request.get("template")
            if isinstance(request.get("template"), str)
            else str(figure.get("default_template") or "box_strip"),
        )
        figure_request["x_metric"] = "sample"
        figure_request["y_metric"] = "impact_strength"
    figure_request["series_order"] = list(figure.get("sample_order") or [])
    return figure_request


def _queue_item_from_task(task: FigureTask) -> dict[str, Any]:
    return figure_queue_item_from_task(task)


def _task_from_queue_item(figure: dict[str, Any]) -> FigureTask | None:
    return figure_task_from_queue_item(figure)


def _impact_point_line_condition_order(
    request: dict[str, Any],
) -> list[str]:
    render_options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    return _string_list(
        request.get("condition_order") or render_options.get("condition_order")
    )


def _impact_point_line_source(
    source: Path,
) -> Path:
    if source.is_file():
        return source
    workbooks = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}
    )
    if len(workbooks) != 1:
        raise StudioPreparationBlocked(
            "impact_point_line_workbook_ambiguous",
            "Impact point-line comparison needs exactly one workbook source.",
        )
    return workbooks[0]
