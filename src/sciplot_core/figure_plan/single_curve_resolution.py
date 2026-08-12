"""Project one typed single-curve source snapshot into a FigurePlan."""

from __future__ import annotations

import re
from typing import Any, NoReturn

from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.metric_binding import CartesianMetricBinding
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.materials_rules.catalog import get_rule, resolve_rule_template
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)


REGISTERED_SINGLE_CURVE_SELECTION_POLICY = "registered_single_curve"


def resolve_registered_single_curve_plan(
    *,
    rule_id: str,
    request: dict[str, Any],
    source_resolution: ResolvedScientificTransform,
    source_sha256: str,
) -> ResolvedFigurePlan:
    """Build one task from a rule and its already-resolved curve snapshot."""

    rule = get_rule(rule_id)
    if rule.figure_plan_adapter != "registered_single_curve":
        _invalid("The selected rule does not own the single-curve plan adapter.")
    requested_template = request.get("template")
    try:
        template = resolve_rule_template(
            rule,
            requested_template if isinstance(requested_template, str) else None,
        )
    except ValueError as exc:
        raise FigurePlanResolutionError(
            "registered_single_curve_template_invalid",
            str(exc),
        ) from exc
    if source_resolution.contract.semantic_family != rule.semantic_family:
        _invalid("The resolved curve does not match the selected semantic rule.")
    if not source_resolution.series:
        _invalid("The resolved single-curve source has no series.")

    sample_order = tuple(series.sample for series in source_resolution.series)
    if len(sample_order) != len(set(sample_order)):
        _invalid("Resolved single-curve sample identities must be unique.")
    if any(not series.points for series in source_resolution.series):
        _invalid("Every resolved single-curve series must contain data points.")

    x_metric = _output_metric(source_resolution, "x_metric")
    y_metric = _output_metric(source_resolution, "y_metric")
    if x_metric == y_metric:
        _invalid("The registered single-curve axes must use different metrics.")
    x_label = _output_axis_label(
        source_resolution,
        "x_label",
        fallback=rule.x_axis.canonical_label,
    )
    y_label = _output_axis_label(
        source_resolution,
        "y_label",
        fallback=rule.y_axis.canonical_label,
    )
    if any(
        _label_token(series.x_label)
        != _label_token(x_label)
        or _label_token(series.y_label)
        != _label_token(y_label)
        for series in source_resolution.series
    ):
        _invalid("Resolved curve labels do not share the transform output axes.")

    family_stem = rule.rule_id.removesuffix("_curve")
    figure_id = f"{family_stem}_{y_metric}_vs_{x_metric}"
    task = FigureTask.with_metric_binding(
        figure_id=figure_id,
        order=1,
        title=f"{y_label} vs {x_label}",
        metric_binding=CartesianMetricBinding(
            x_metric=x_metric,
            y_metric=y_metric,
        ),
        template=template,
        artifact_stem=figure_id,
        document_stem=figure_id,
        sample_order=sample_order,
        replicate_counts=tuple((sample, 1) for sample in sample_order),
    )
    return ResolvedFigurePlan.planned(
        rule_id=rule.rule_id,
        selection_policy=REGISTERED_SINGLE_CURVE_SELECTION_POLICY,
        primary_figure_id=figure_id,
        tasks=(task,),
        source_sha256=source_sha256,
    )


def _output_metric(
    source_resolution: ResolvedScientificTransform,
    key: str,
) -> str:
    value = source_resolution.contract.output.get(key)
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_]*", value) is None:
        _invalid(f"Scientific transform output {key!r} is not a metric identifier.")
    return value


def _output_axis_label(
    source_resolution: ResolvedScientificTransform,
    key: str,
    *,
    fallback: str,
) -> str:
    value = source_resolution.contract.output.get(key, fallback)
    if not isinstance(value, str) or not value.strip():
        _invalid(f"Scientific transform output {key!r} is not an axis label.")
    return value.strip()


def _label_token(label: str) -> str:
    return "".join(character for character in label.casefold() if character.isalnum())


def _invalid(message: str) -> NoReturn:
    raise FigurePlanResolutionError(
        "registered_single_curve_contract_invalid",
        message,
    )


__all__ = [
    "REGISTERED_SINGLE_CURVE_SELECTION_POLICY",
    "resolve_registered_single_curve_plan",
]
