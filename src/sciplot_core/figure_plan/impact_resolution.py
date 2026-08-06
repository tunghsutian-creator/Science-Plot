"""Resolve impact source facts into stable selected figure tasks."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.path_names import slug

from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.request_values import (
    impact_condition_label_mapping,
)
from sciplot_core.figure_plan.task import FigureTask


def resolve_impact_plan(
    *,
    input_path: Path,
    template: str,
    request: dict[str, Any],
    source_sha256: str | None,
) -> ResolvedFigurePlan:
    """Resolve one impact figure plan from a workbook or generic request."""

    workbook = _single_impact_workbook(input_path)
    if workbook is None:
        return _with_source_sha256(
            _generic_impact_plan(template),
            source_sha256,
        )
    from sciplot_core.semantic_sources.impact_sources import (
        read_impact_condition_payloads,
    )

    available = read_impact_condition_payloads(workbook)
    if not available:
        return _with_source_sha256(
            _generic_impact_plan(template),
            source_sha256,
        )
    effective_template = str(template).strip()
    if effective_template == "point_line":
        return _with_source_sha256(
            _impact_point_line_plan(
                available,
                template=effective_template,
                request=request,
            ),
            source_sha256,
        )
    if len(available) == 1:
        return _with_source_sha256(
            _single_condition_plan(available[0], template=effective_template),
            source_sha256,
        )
    return _with_source_sha256(
        _multi_condition_plan(available, template=effective_template),
        source_sha256,
    )


def _with_source_sha256(
    plan: ResolvedFigurePlan,
    source_sha256: str | None,
) -> ResolvedFigurePlan:
    return ResolvedFigurePlan(
        rule_id=plan.rule_id,
        selection_policy=plan.selection_policy,
        primary_figure_id=plan.primary_figure_id,
        tasks=plan.tasks,
        outcomes=plan.outcomes,
        source_sha256=source_sha256,
    )


def _impact_point_line_plan(
    available: list[tuple[str, Any]],
    *,
    template: str,
    request: dict[str, Any],
) -> ResolvedFigurePlan:
    selected, selection_policy = _selected_point_line_conditions(
        available,
        request=request,
    )
    task = FigureTask(
        figure_id="impact_strength_by_sample",
        order=1,
        title="Impact strength by sample",
        x_metric="sample",
        y_metric="impact_strength",
        template=template,
        artifact_stem="impact_point_line",
        document_stem="impact_strength_by_sample",
        conditions=tuple(condition for condition, _payload in selected),
        condition_labels=tuple(
            impact_condition_label_mapping(request).get(condition, condition)
            for condition, _payload in selected
        ),
        sample_order=tuple(selected[0][1].samples),
    )
    return ResolvedFigurePlan.planned(
        rule_id="impact_metric",
        selection_policy=selection_policy,
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )


def _single_condition_plan(
    available: tuple[str, Any],
    *,
    template: str,
) -> ResolvedFigurePlan:
    condition, payload = available
    task = FigureTask(
        figure_id="impact_strength_by_sample",
        order=1,
        title=f"Impact strength - {condition}",
        x_metric="sample",
        y_metric="impact_strength",
        template=template,
        artifact_stem="impact_strength_by_sample",
        document_stem="impact_strength_by_sample",
        conditions=(condition,),
        condition_labels=(condition,),
        sample_order=tuple(payload.samples),
        replicate_counts=tuple(
            zip(payload.samples, payload.replicate_counts, strict=True)
        ),
    )
    return ResolvedFigurePlan.planned(
        rule_id="impact_metric",
        selection_policy="single_workbook_condition",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )


def _multi_condition_plan(
    available: list[tuple[str, Any]],
    *,
    template: str,
) -> ResolvedFigurePlan:
    condition_names = [condition for condition, _payload in available]
    artifact_stems = _legacy_autoplot_impact_stems(condition_names)
    document_stems = _legacy_studio_impact_stems(condition_names)
    tasks = tuple(
        FigureTask(
            figure_id=stable_impact_figure_id(condition),
            order=index,
            title=f"Impact strength - {condition}",
            x_metric="sample",
            y_metric="impact_strength",
            template=template,
            artifact_stem=artifact_stems[index - 1],
            document_stem=document_stems[index - 1],
            conditions=(condition,),
            condition_labels=(condition,),
            sample_order=tuple(payload.samples),
            replicate_counts=tuple(
                zip(payload.samples, payload.replicate_counts, strict=True)
            ),
        )
        for index, (condition, payload) in enumerate(available, start=1)
    )
    task_ids = [task.figure_id for task in tasks]
    if len(set(task_ids)) != len(task_ids):
        raise FigurePlanResolutionError(
            "duplicate_impact_condition_identity",
            "Impact workbook conditions do not have unique stable identities.",
        )
    return ResolvedFigurePlan.planned(
        rule_id="impact_metric",
        selection_policy="all_workbook_conditions",
        primary_figure_id=tasks[0].figure_id,
        tasks=tasks,
    )


def _generic_impact_plan(template: str) -> ResolvedFigurePlan:
    effective_template = str(template).strip()
    if effective_template == "point_line":
        raise FigurePlanResolutionError(
            "impact_point_line_needs_workbook_conditions",
            "Impact point-line comparison requires independently named workbook "
            "conditions.",
        )
    task = FigureTask(
        figure_id="impact_strength_by_sample",
        order=1,
        title="Impact strength by sample",
        x_metric="sample",
        y_metric="impact_strength",
        template=effective_template,
        artifact_stem="impact_strength_by_sample",
        document_stem="impact_strength_by_sample",
    )
    return ResolvedFigurePlan.planned(
        rule_id="impact_metric",
        selection_policy="single_render_request",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )


def stable_impact_figure_id(condition: str) -> str:
    """Return an order-independent, ASCII-safe identity for one sheet label."""

    normalized = unicodedata.normalize("NFKC", str(condition)).casefold().strip()
    compact = re.sub(r"\s+", "", normalized)
    token = re.sub(r"[^a-z0-9]+", "_", compact).strip("_")
    if token and normalized == token:
        return f"impact_{token}"
    digest = canonical_json_sha256(normalized, allow_nan=False)[:10]
    return f"impact_{token or 'condition'}_{digest}"


def _legacy_autoplot_impact_stems(conditions: list[str]) -> list[str]:
    """Retain current Workflow filenames while IDs become route-independent."""

    return _stable_compatibility_stems(
        [
            (f"impact_{slug(str(condition).replace(' ', ''))}", condition)
            for condition in conditions
        ]
    )


def _legacy_studio_impact_stems(conditions: list[str]) -> list[str]:
    """Retain current Studio document filenames for existing source labels."""

    bases: list[tuple[str, str]] = []
    for order, condition in enumerate(conditions, start=1):
        token = (
            re.sub(r"[^a-z0-9]+", "_", str(condition).casefold()).strip("_")
            or f"condition_{order}"
        )
        bases.append((f"impact_{token}", condition))
    return _stable_compatibility_stems(bases)


def _stable_compatibility_stems(
    bases: list[tuple[str, str]],
) -> list[str]:
    counts = {
        base: sum(1 for value, _identity in bases if value == base) for base, _ in bases
    }
    return [
        (
            base
            if counts[base] == 1
            else f"{base}_{canonical_json_sha256(identity, allow_nan=False)[:8]}"
        )
        for base, identity in bases
    ]


def _selected_point_line_conditions(
    available: list[tuple[str, Any]],
    *,
    request: dict[str, Any],
) -> tuple[list[tuple[str, Any]], str]:
    if len(available) < 2:
        raise FigurePlanResolutionError(
            "impact_point_line_needs_multiple_conditions",
            "Impact point-line comparison needs at least two workbook conditions.",
        )
    by_condition = {condition: payload for condition, payload in available}
    requested_order = _condition_order(request)
    if len(requested_order) != len(set(requested_order)):
        raise FigurePlanResolutionError(
            "duplicate_impact_point_line_condition",
            "Impact point-line condition_order cannot contain duplicates.",
        )
    if requested_order:
        selected = _explicit_point_line_conditions(
            requested_order,
            by_condition=by_condition,
        )
        selection_policy = "explicit_condition_order"
    else:
        selected = _largest_compatible_condition_group(available)
        selection_policy = "largest_compatible_ordered_sample_axis_group"
    _validate_point_line_conditions(selected)
    return selected, selection_policy


def _explicit_point_line_conditions(
    requested_order: list[str],
    *,
    by_condition: dict[str, Any],
) -> list[tuple[str, Any]]:
    missing = [
        condition for condition in requested_order if condition not in by_condition
    ]
    if missing:
        raise FigurePlanResolutionError(
            "unknown_impact_point_line_condition",
            "Unknown impact point-line condition(s): " + ", ".join(missing),
        )
    return [(condition, by_condition[condition]) for condition in requested_order]


def _largest_compatible_condition_group(
    available: list[tuple[str, Any]],
) -> list[tuple[str, Any]]:
    compatible: dict[tuple[str, ...], list[tuple[str, Any]]] = {}
    shape_order: list[tuple[str, ...]] = []
    for condition, payload in available:
        shape = tuple(payload.samples)
        if shape not in compatible:
            shape_order.append(shape)
            compatible[shape] = []
        compatible[shape].append((condition, payload))
    selected_shape = max(
        shape_order,
        key=lambda shape: (
            len(compatible[shape]),
            len(shape),
            -shape_order.index(shape),
        ),
    )
    return compatible[selected_shape]


def _validate_point_line_conditions(selected: list[tuple[str, Any]]) -> None:
    if len(selected) < 2:
        raise FigurePlanResolutionError(
            "impact_point_line_incompatible_conditions",
            "No compatible group of at least two impact conditions shares one "
            "sample axis; choose conditions explicitly or repair the source.",
        )
    sample_order = tuple(selected[0][1].samples)
    if any(tuple(payload.samples) != sample_order for _condition, payload in selected):
        raise FigurePlanResolutionError(
            "impact_point_line_sample_axis_mismatch",
            "Every selected impact point-line condition must use the same ordered "
            "sample axis.",
        )
    if {str(payload.unit) for _condition, payload in selected} != {"kJ/m2"}:
        raise FigurePlanResolutionError(
            "impact_point_line_unit_mismatch",
            "Impact point-line conditions must all use canonical kJ/m2 units.",
        )


def _single_impact_workbook(source: Path) -> Path | None:
    resolved = source.expanduser().resolve()
    if resolved.is_file():
        return (
            resolved
            if resolved.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}
            else None
        )
    if not resolved.is_dir():
        return None
    workbooks = sorted(
        path
        for path in resolved.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}
    )
    return workbooks[0] if len(workbooks) == 1 else None


def _condition_order(request: dict[str, Any]) -> list[str]:
    render_options_value = request.get("render_options")
    if isinstance(render_options_value, dict):
        render_options = render_options_value
    else:
        render_options = {}
    value = request.get("condition_order") or render_options.get("condition_order")
    if not isinstance(value, list | tuple):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


__all__ = ["resolve_impact_plan", "stable_impact_figure_id"]
