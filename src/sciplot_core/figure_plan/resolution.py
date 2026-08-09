"""Resolve Study Model recommendations and source facts into selected tasks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.constants import SUPPORTED_FIGURE_PLAN_RULE_IDS
from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.impact_resolution import (
    resolve_impact_plan,
    stable_impact_figure_id,
)
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.figure_plan.source_binding import source_tree_sha256
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS


_RHEOLOGY_FREQUENCY_METRICS = {
    "complex_modulus",
    "storage_modulus",
    "loss_modulus",
    "loss_factor",
    "complex_viscosity",
}
_RHEOLOGY_SOURCE_METRICS = (
    ("storage_modulus", "Storage Modulus"),
    ("loss_modulus", "Loss Modulus"),
    ("loss_factor", "Loss Factor"),
    ("complex_modulus", "Complex Modulus"),
    ("complex_viscosity", "Complex Viscosity"),
)
_FIGURE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_]*")


def resolve_current_figure_plan(
    *,
    persisted: object,
    rule_id: str | None,
    template: str,
    study_model: dict[str, Any],
    input_path: Path | None,
    request: dict[str, Any],
) -> ResolvedFigurePlan | None:
    """Resolve current source facts and reject a stale or malformed saved plan."""

    try:
        persisted_plan = resolved_figure_plan_from_payload(persisted)
    except (TypeError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "invalid_resolved_figure_plan",
            f"The persisted figure plan is invalid: {exc}",
        ) from exc
    normalized_rule = str(rule_id or "").strip()
    if normalized_rule in SUPPORTED_FIGURE_PLAN_RULE_IDS and input_path is None:
        raise FigurePlanResolutionError(
            "figure_plan_source_required",
            f"Figure planning for `{normalized_rule}` requires an explicit source.",
        )
    try:
        current_plan = resolve_figure_plan(
            rule_id=rule_id,
            template=template,
            study_model=study_model,
            input_path=input_path,
            request=request,
        )
    except FigurePlanResolutionError:
        raise
    except (OSError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "resolved_figure_plan_unavailable",
            f"SciPlot could not resolve the current figure plan: {exc}",
        ) from exc
    if current_plan is None and normalized_rule in SUPPORTED_FIGURE_PLAN_RULE_IDS:
        raise FigurePlanResolutionError(
            "resolved_figure_plan_unavailable",
            f"SciPlot could not resolve a figure plan for `{normalized_rule}`.",
        )
    if (
        current_plan is not None
        and normalized_rule in SUPPORTED_FIGURE_PLAN_RULE_IDS
        and current_plan.source_sha256 is None
    ):
        raise FigurePlanResolutionError(
            "figure_plan_source_unavailable",
            f"SciPlot could not fingerprint the source for `{normalized_rule}`.",
        )
    if persisted_plan is not None and (
        current_plan is None or persisted_plan.plan_sha256 != current_plan.plan_sha256
    ):
        raise FigurePlanResolutionError(
            "stale_resolved_figure_plan",
            "The persisted figure plan no longer matches the current rule, "
            "template, Study Model, or source conditions.",
        )
    return current_plan


def resolve_preparation_figure_plan(
    *,
    persisted: object,
    rule_id: str | None,
    template: str,
    study_model: dict[str, Any],
    input_path: Path | None,
    request: dict[str, Any],
) -> ResolvedFigurePlan | None:
    """Resolve a new plan for a render that will replace generated artifacts.

    A preparation may refresh task selection after source or Study Model changes,
    but it may not silently discard an invalid plan or cross rule boundaries.
    Exact-current reuse and publication must use ``resolve_current_figure_plan``.
    """

    try:
        persisted_plan = resolved_figure_plan_from_payload(persisted)
    except (TypeError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "invalid_resolved_figure_plan",
            f"The persisted figure plan is invalid: {exc}",
        ) from exc
    current_plan = resolve_current_figure_plan(
        persisted=None,
        rule_id=rule_id,
        template=template,
        study_model=study_model,
        input_path=input_path,
        request=request,
    )
    if persisted_plan is not None and (
        current_plan is None or persisted_plan.rule_id != current_plan.rule_id
    ):
        raise FigurePlanResolutionError(
            "stale_resolved_figure_plan",
            "The persisted figure plan cannot be refreshed across rule boundaries.",
        )
    return current_plan


def resolve_figure_plan(
    *,
    rule_id: str | None,
    template: str,
    study_model: dict[str, Any],
    input_path: Path | None,
    request: dict[str, Any],
) -> ResolvedFigurePlan | None:
    """Resolve the current plan for supported rule families without writes."""

    normalized_rule = str(rule_id or "").strip()
    if normalized_rule == "dma_temperature_sweep":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "DMA temperature figure planning requires an explicit source path.",
            )
        from sciplot_core.figure_plan.dma_temperature_resolution import (
            resolve_dma_temperature_plan,
        )

        return resolve_dma_temperature_plan(
            input_path=input_path,
            request={**request, "template": template},
        )
    if normalized_rule == "dsc_curve":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "DSC figure planning requires an explicit source path.",
            )
        from sciplot_core.figure_plan.dsc_resolution import (
            resolve_dsc_single_curve_plan,
        )

        return resolve_dsc_single_curve_plan(
            input_path=input_path,
            request={**request, "template": template},
        )
    if normalized_rule in MECHANICAL_RULE_IDS:
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "Mechanical figure planning requires an explicit source path.",
            )
        from sciplot_core.figure_plan.mechanical_resolution import (
            resolve_mechanical_plan,
        )

        return resolve_mechanical_plan(
            input_path=input_path,
            rule_id=normalized_rule,
            template=template,
            study_model=study_model,
            request=request,
        )
    if normalized_rule == "performance_comparison":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "Performance figure planning requires an explicit source path.",
            )
        from sciplot_core.figure_plan.performance_resolution import (
            resolve_performance_plan,
        )

        return resolve_performance_plan(
            input_path=input_path,
            request=request,
        )
    if normalized_rule == "rheology_temperature_sweep":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "Temperature figure planning requires an explicit source path.",
            )
        from sciplot_core.figure_plan.temperature_resolution import (
            resolve_temperature_plan,
        )

        return resolve_temperature_plan(
            input_path=input_path,
            request=request,
        )
    source_sha256 = source_tree_sha256(input_path)
    if normalized_rule == "rheology_frequency_sweep":
        return _resolve_frequency_plan(
            study_model,
            input_path=input_path,
            source_sha256=source_sha256,
        )
    if normalized_rule == "impact_metric":
        if input_path is None:
            raise FigurePlanResolutionError(
                "figure_plan_source_required",
                "Impact figure planning requires an explicit source path.",
            )
        return resolve_impact_plan(
            input_path=input_path,
            template=template,
            request=request,
            source_sha256=source_sha256,
        )
    return None


def _resolve_frequency_plan(
    study_model: dict[str, Any],
    *,
    input_path: Path | None,
    source_sha256: str | None,
) -> ResolvedFigurePlan | None:
    from sciplot_core.study_model.normalization import normalize_study_model

    normalized = normalize_study_model(study_model)
    raw_queue_value = normalized.get("figure_queue")
    if isinstance(raw_queue_value, list):
        raw_queue = raw_queue_value
    else:
        raw_queue = []
    tasks: list[FigureTask] = []
    seen_ids: set[str] = set()
    for value in raw_queue:
        if not isinstance(value, dict):
            continue
        figure_id = str(value.get("id") or "").strip()
        x_metric = _metric_id(value.get("x_metric"))
        y_metric = _metric_id(value.get("y_metric") or value.get("metric"))
        if (
            _FIGURE_ID_PATTERN.fullmatch(figure_id) is None
            or figure_id in seen_ids
            or x_metric != "angular_frequency"
            or y_metric not in _RHEOLOGY_FREQUENCY_METRICS
        ):
            continue
        seen_ids.add(figure_id)
        tasks.append(
            FigureTask(
                figure_id=figure_id,
                order=len(tasks) + 1,
                title=str(value.get("title") or figure_id),
                x_metric=x_metric,
                y_metric=y_metric,
                template="point_line",
                artifact_stem=f"freq_{y_metric}",
                document_stem=figure_id,
            )
        )
    selected_metrics = {task.y_metric for task in tasks}
    for y_metric in _frequency_source_metrics(input_path):
        if y_metric in selected_metrics:
            continue
        selected_metrics.add(y_metric)
        figure_id = f"{y_metric}_vs_frequency"
        tasks.append(
            FigureTask(
                figure_id=figure_id,
                order=len(tasks) + 1,
                title=f"{dict(_RHEOLOGY_SOURCE_METRICS)[y_metric]} vs frequency",
                x_metric="angular_frequency",
                y_metric=y_metric,
                template="point_line",
                artifact_stem=f"freq_{y_metric}",
                document_stem=figure_id,
            )
        )
    primary = next(
        (task.figure_id for task in tasks if task.y_metric == "storage_modulus"),
        None,
    )
    if primary is None:
        return None
    return ResolvedFigurePlan.planned(
        rule_id="rheology_frequency_sweep",
        selection_policy="study_model_queue_plus_available_recognized_metrics",
        primary_figure_id=primary,
        tasks=tuple(tasks),
        source_sha256=source_sha256,
    )


def _frequency_source_metrics(source: Path | None) -> tuple[str, ...]:
    if source is None:
        return ()
    workbook = _single_frequency_workbook(source)
    if workbook is None:
        return ()
    import pandas as pd

    frame = pd.read_excel(workbook, sheet_name=0, header=None, nrows=1)
    if frame.empty:
        return ()
    header_tokens = {_header_token(value) for value in frame.iloc[0].tolist()}
    return tuple(
        metric
        for metric, label in _RHEOLOGY_SOURCE_METRICS
        if _header_token(label) in header_tokens
    )


def _single_frequency_workbook(source: Path) -> Path | None:
    resolved = source.expanduser().resolve()
    if resolved.is_file():
        return resolved if resolved.suffix.casefold() in {".xlsx", ".xls"} else None
    if not resolved.is_dir():
        return None
    workbooks = sorted(
        path
        for path in resolved.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls"}
    )
    return workbooks[0] if len(workbooks) == 1 else None


def _header_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _metric_id(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


__all__ = [
    "FigurePlanResolutionError",
    "resolve_current_figure_plan",
    "resolve_preparation_figure_plan",
    "resolve_figure_plan",
    "stable_impact_figure_id",
]
