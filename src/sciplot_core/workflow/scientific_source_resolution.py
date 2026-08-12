"""Bind one workflow transaction to a shared scientific source snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    resolve_preparation_figure_plan,
    validate_preparation_figure_plan,
)
from sciplot_core.semantic_sources.scientific_source import (
    ResolvedScientificSource,
    resolve_scientific_source,
)
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.request_contract import project_semantic_render_options


def resolve_workflow_scientific_source(
    *,
    input_path: Path,
    rule_id: str,
    template: str,
    study_model: dict[str, Any],
    request: dict[str, Any],
) -> tuple[ResolvedScientificSource | None, ResolvedFigurePlan | None]:
    """Resolve the scientific source and current plan once for this run."""

    resolved_source = resolve_scientific_source(
        input_path,
        rule_id=rule_id,
        template=template,
        request=request,
        study_model=study_model,
    )
    plan = (
        validate_preparation_figure_plan(
            persisted=request.get("resolved_figure_plan"),
            rule_id=rule_id,
            current_plan=resolved_source.figure_plan,
        )
        if resolved_source is not None
        else resolve_preparation_figure_plan(
            persisted=request.get("resolved_figure_plan"),
            rule_id=rule_id,
            template=template,
            study_model=study_model,
            input_path=input_path,
            request=request,
        )
    )
    return resolved_source, plan


def bind_workflow_semantic_render_options(
    *,
    request: dict[str, Any],
    semantic: dict[str, Any],
    figure_plan: ResolvedFigurePlan | None,
    resolved_scientific_source: ResolvedScientificSource | None = None,
) -> dict[str, Any]:
    """Bind rule defaults while preserving only declared user overrides."""

    effective = dict(request)
    request_options = (
        dict(request.get("render_options"))
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    template = str(request.get("template") or semantic.get("template") or "curve")
    semantic_options = project_semantic_render_options(
        semantic.get("render_options"),
        template=template,
    )
    merged = {**request_options, **semantic_options}
    if (
        figure_plan is not None
        and figure_plan.selection_policy == "registered_single_curve"
    ):
        source_labels = _single_curve_source_axis_labels(
            resolved_scientific_source
        )
        axis_plan = (
            semantic.get("axis_plan")
            if isinstance(semantic.get("axis_plan"), dict)
            else {}
        )
        for axis_name, option_name in (
            ("x", "x_label_override"),
            ("y", "y_label_override"),
        ):
            axis = (
                axis_plan.get(axis_name)
                if isinstance(axis_plan.get(axis_name), dict)
                else {}
            )
            display_label = source_labels.get(axis_name) or axis.get("display_label")
            if isinstance(display_label, str) and display_label.strip():
                merged[option_name] = display_label.strip()
    explicit_payload = request.get("explicit_render_option_keys")
    explicit_keys = (
        {
            str(key)
            for key in explicit_payload
            if str(key) in request_options
        }
        if isinstance(explicit_payload, list | tuple | set)
        else set(request_options)
    )
    merged.update({key: request_options[key] for key in explicit_keys})
    effective["render_options"] = merged
    return effective


def _single_curve_source_axis_labels(
    resolved_source: ResolvedScientificSource | None,
) -> dict[str, str]:
    transform = resolved_source.transform if resolved_source is not None else None
    if transform is None:
        return {}
    output = transform.contract.output
    labels: dict[str, str] = {}
    for axis_name in ("x", "y"):
        label = output.get(f"{axis_name}_label")
        if not isinstance(label, str) or not label.strip():
            continue
        unit = output.get(f"{axis_name}_unit")
        display_unit = format_unit_label(unit) if isinstance(unit, str) else ""
        labels[axis_name] = (
            f"{label.strip()} ({display_unit})" if display_unit else label.strip()
        )
    return labels


__all__ = [
    "bind_workflow_semantic_render_options",
    "resolve_workflow_scientific_source",
]
