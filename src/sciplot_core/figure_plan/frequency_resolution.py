"""Resolve rheology-frequency tasks from one selected source view."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.source_binding import source_tree_sha256
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.semantic_sources.rheology_sweep_domain import (
    FREQUENCY_RULE_ID,
    ResolvedRheologySweepDomain,
    RheologySweepDomainError,
    resolve_rheology_frequency_domain,
)
from sciplot_core.study_model.normalization import normalize_study_model


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


def resolve_frequency_plan(
    *,
    study_model: dict[str, Any],
    input_path: Path | None,
    request: dict[str, Any],
    source_resolution: ResolvedRheologySweepDomain | None = None,
) -> ResolvedFigurePlan | None:
    """Build the frequency task set from one parser-selected source domain."""

    source_sha256: str | None
    available_metrics: tuple[str, ...]
    sample_order: tuple[str, ...] = ()
    replicate_counts: tuple[tuple[str, int], ...] = ()
    directory_source = bool(
        input_path is not None and input_path.expanduser().resolve().is_dir()
    )
    if directory_source:
        assert input_path is not None
        resolved_source = source_resolution or _resolve_frequency_domain(
            input_path,
            request=request,
        )
        if (
            resolved_source.rule_id != FREQUENCY_RULE_ID
            or resolved_source.source != input_path.expanduser().resolve()
        ):
            raise FigurePlanResolutionError(
                "frequency_source_mismatch",
                "The resolved rheology-frequency domain belongs to another source.",
            )
        source_sha256 = resolved_source.source_sha256
        available_metrics = resolved_source.facts.available_metrics
        sample_order = resolved_source.facts.sample_order
        replicate_counts = resolved_source.facts.replicate_counts
    else:
        if source_resolution is not None:
            raise FigurePlanResolutionError(
                "frequency_source_mismatch",
                "A rheology-frequency directory domain cannot bind a file source.",
            )
        source_sha256 = source_tree_sha256(input_path)
        available_metrics = _frequency_source_metrics(input_path)

    normalized = normalize_study_model(study_model)
    raw_queue_value = normalized.get("figure_queue")
    raw_queue = raw_queue_value if isinstance(raw_queue_value, list) else []
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
            or (directory_source and y_metric not in available_metrics)
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
                sample_order=sample_order,
                replicate_counts=replicate_counts,
            )
        )
    selected_metrics = {task.y_metric for task in tasks}
    for y_metric in available_metrics:
        if y_metric in selected_metrics or y_metric not in _RHEOLOGY_FREQUENCY_METRICS:
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
                sample_order=sample_order,
                replicate_counts=replicate_counts,
            )
        )
    primary = next(
        (task.figure_id for task in tasks if task.y_metric == "storage_modulus"),
        None,
    )
    if primary is None:
        return None
    return ResolvedFigurePlan.planned(
        rule_id=FREQUENCY_RULE_ID,
        selection_policy=(
            "parser_selected_metrics_from_study_model_queue"
            if directory_source
            else "study_model_queue_plus_available_recognized_metrics"
        ),
        primary_figure_id=primary,
        tasks=tuple(tasks),
        source_sha256=source_sha256,
    )


def _resolve_frequency_domain(
    input_path: Path,
    *,
    request: dict[str, Any],
) -> ResolvedRheologySweepDomain:
    try:
        return resolve_rheology_frequency_domain(input_path, request=request)
    except RheologySweepDomainError as exc:
        raise FigurePlanResolutionError(exc.reason_code, str(exc)) from exc


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


__all__ = ["resolve_frequency_plan"]
