"""Build rheology and impact figure queues and per-figure render requests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.figure_plan import (
    FigureTask,
    ResolvedFigurePlan,
    request_for_figure_task,
    resolve_figure_plan,
    resolved_figure_plan_from_payload,
)
from sciplot_core.materials_rules.catalog import resolve_rule_template
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
from sciplot_core.studio_core.impact_task_sources import (
    materialize_impact_condition_sources,
    materialize_impact_point_line_source,
    validated_impact_plan_snapshot,
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
            study_model=_request_study_model(request),
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
    render_options_value: object = figure_request.get("render_options")
    render_options = (
        dict(render_options_value) if isinstance(render_options_value, dict) else {}
    )
    render_options["size"] = "60x55"
    explicit_render_option_keys: object = figure_request.get(
        "explicit_render_option_keys"
    )
    explicit_render_keys = {
        str(value)
        for value in (
            explicit_render_option_keys
            if isinstance(explicit_render_option_keys, list)
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
            # An absent key inherits the frequency rule's logarithmic format
            # during the later merge. Explicit native Auto keeps this axis linear.
            render_options["y_tick_format"] = "Auto"
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
    source_root = _resolve_request_input(request, base_dir=base_dir)
    if source_root is None:
        return []
    source = source_root
    if source_root.is_dir():
        workbooks = sorted(
            path
            for path in source_root.rglob("*")
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
            study_model=_request_study_model(request),
            input_path=source_root,
            request=request,
        )
    if plan is None or plan.rule_id != "impact_metric":
        return []
    if _request_template(request) == "point_line":
        _payloads, workbook_hash = validated_impact_plan_snapshot(
            plan,
            template="point_line",
            request=request,
            source_root=source_root,
            workbook=source,
        )
        condition_source = materialize_impact_point_line_source(
            plan,
            source_root=source_root,
            workbook=source,
            workbook_hash=workbook_hash,
            project_dir=project_dir,
        )
        return [
            {
                **_queue_item_from_task(plan.tasks[0]),
                "condition_source": str(condition_source),
                "supported_templates": ["point_line"],
                "presentation_data_shape": "condition_overlay_replicates",
            }
        ]
    if plan.selection_policy != "all_workbook_conditions":
        return []
    condition_payloads, _workbook_hash = validated_impact_plan_snapshot(
        plan,
        template=_request_template(request),
        request=request,
        source_root=source_root,
        workbook=source,
    )
    return materialize_impact_condition_sources(
        plan,
        condition_payloads=condition_payloads,
        project_dir=project_dir,
    )


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
    render_options_value: object = request.get("render_options")
    render_options = (
        render_options_value if isinstance(render_options_value, dict) else {}
    )
    return _string_list(
        request.get("condition_order") or render_options.get("condition_order")
    )


def _request_study_model(request: dict[str, Any]) -> dict[str, Any]:
    value: object = request.get("study_model")
    return value if isinstance(value, dict) else {}


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
