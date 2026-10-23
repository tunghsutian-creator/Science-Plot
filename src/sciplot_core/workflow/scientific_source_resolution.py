"""Bind one workflow transaction to a shared scientific source snapshot."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import (
    ResolvedFigurePlan,
    resolve_preparation_figure_plan,
    resolved_figure_plan_from_payload,
    validate_preparation_figure_plan,
)
from sciplot_core.semantic_sources.scientific_source import (
    ResolvedScientificSource,
    resolve_scientific_source,
)
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.materials_rules import get_rule
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.presentation_identity import (
    SelectedPresentationIdentity,
    resolve_selected_presentation_identity,
)
from sciplot_core.request_contract import project_semantic_render_options
from sciplot_core.studio_render.domain_defaults import _explicit_render_options
from sciplot_core.studio_render.spectral_axis_display import (
    freeze_new_spectral_axis_display,
)


def previous_workflow_request(request_path: Path) -> dict[str, Any] | None:
    """Retain a prior canonical binding before a new run replaces its request.

    Historical automatic requests may only have their resolved binding in their
    own run snapshot. Read that exact source/choice-bound record, never infer
    its identity by classifying today's source again.
    """
    if not request_path.exists():
        return None
    previous = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(previous, dict):
        raise ValueError("Previous plot request must be a JSON object.")
    if previous.get("resolved_figure_plan") is not None:
        return previous
    output = previous.get("output")
    if not isinstance(output, str):
        return previous
    run = Path(output)
    run = run if run.is_absolute() else request_path.parent / run
    if (
        run.parent != request_path.parent / "runs"
        or not run.name.startswith("run_")
        or not run.name[4:].isdigit()
        or run.resolve() != run.absolute()
    ):
        return previous
    snapshot = run / "request_snapshot.json"
    if not snapshot.exists():
        return previous
    if snapshot.resolve() != snapshot.absolute():
        return previous
    recorded = json.loads(snapshot.read_text(encoding="utf-8"))
    if not isinstance(recorded, dict) or any(
        recorded.get(key) != previous.get(key)
        for key in ("input", "output", "recipe", "rule_id", "template")
    ):
        return previous
    plan = resolved_figure_plan_from_payload(recorded.get("resolved_figure_plan"))
    return (
        {**previous, "resolved_figure_plan": plan.to_payload()}
        if plan is not None
        else previous
    )


def _previous_identity(request: dict[str, Any]) -> SelectedPresentationIdentity | None:
    plan = resolved_figure_plan_from_payload(request.get("resolved_figure_plan"))
    rule_id = plan.rule_id if plan is not None else request.get("rule_id")
    if not isinstance(rule_id, str) or not rule_id:
        return None
    identity = resolve_selected_presentation_identity(
        request, current_rule=get_rule(rule_id)
    )
    if plan is not None:
        primary = next(
            task for task in plan.tasks if task.figure_id == plan.primary_figure_id
        )
        if identity != SelectedPresentationIdentity(
            rule_id=plan.rule_id, template=primary.template
        ):
            raise ValueError(
                "Previous workflow selection conflicts with its resolved FigurePlan."
            )
    return identity


def _reuse_workflow_display(
    request: dict[str, Any],
    previous: dict[str, Any] | None,
    identity: SelectedPresentationIdentity,
) -> dict[str, Any]:
    options = request.get("render_options") or {}
    if (
        previous is None
        or "show_y_ticks" in options
        or previous.get("input") != request.get("input")
        or _previous_identity(previous) != identity
    ):
        return request
    old_options = previous.get("render_options") or {}
    show = old_options.get("show_y_ticks") if isinstance(old_options, dict) else None
    if not isinstance(show, bool):
        return request
    explicit = set(_explicit_render_options(request))
    if "show_y_ticks" in _explicit_render_options(previous):
        explicit.add("show_y_ticks")
    return {
        **request,
        "render_options": {**options, "show_y_ticks": show},
        "explicit_render_option_keys": sorted(explicit),
    }


def record_workflow_selection(
    source_request: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """Freeze execution binding/display without declaring an automatic rule explicit."""
    result = deepcopy(source_request)
    if "resolved_figure_plan" in request:
        result["resolved_figure_plan"] = deepcopy(request["resolved_figure_plan"])
    options = request.get("render_options") or {}
    if "show_y_ticks" in options:
        result["render_options"] = {
            **result.get("render_options", {}),
            "show_y_ticks": options["show_y_ticks"],
        }
        result["explicit_render_option_keys"] = list(
            request["explicit_render_option_keys"]
        )
    return result


def _validate_semantic_template(
    semantic: dict[str, Any],
    *,
    request: dict[str, Any],
) -> None:
    rule_id = semantic.get("rule_id")
    if isinstance(rule_id, str) and rule_id.strip():
        resolve_rule_template(
            get_rule(rule_id),
            (
                request.get("template")
                if isinstance(request.get("template"), str)
                else None
            ),
        )


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
    new_creation: bool = False,
    previous_request: dict[str, Any] | None = None,
    selected_template: str | None = None,
) -> dict[str, Any]:
    """Bind rule defaults while preserving only declared user overrides."""

    template = selected_template or str(
        request.get("template") or semantic.get("template") or "curve"
    )
    if new_creation:
        request = _reuse_workflow_display(
            request,
            previous_request,
            SelectedPresentationIdentity(
                rule_id=str(semantic.get("rule_id") or "") or None, template=template
            ),
        )
    effective = dict(request)
    request_options_payload = request.get("render_options")
    request_options = (
        dict(request_options_payload)
        if isinstance(request_options_payload, dict)
        else {}
    )
    semantic_options = project_semantic_render_options(
        semantic.get("render_options"),
        template=template,
    )
    merged = {**request_options, **semantic_options}
    if isinstance(request_options.get("show_y_ticks"), bool):
        merged["show_y_ticks"] = request_options["show_y_ticks"]
    if (
        figure_plan is not None
        and figure_plan.selection_policy == "registered_single_curve"
    ):
        source_labels = _single_curve_source_axis_labels(resolved_scientific_source)
        axis_plan_payload = semantic.get("axis_plan")
        axis_plan = axis_plan_payload if isinstance(axis_plan_payload, dict) else {}
        for axis_name, option_name in (
            ("x", "x_label_override"),
            ("y", "y_label_override"),
        ):
            axis_payload = axis_plan.get(axis_name)
            axis = axis_payload if isinstance(axis_payload, dict) else {}
            display_label = source_labels.get(axis_name) or axis.get("display_label")
            if isinstance(display_label, str) and display_label.strip():
                merged[option_name] = display_label.strip()
    explicit_payload = request.get("explicit_render_option_keys")
    explicit_keys = (
        {str(key) for key in explicit_payload if str(key) in request_options}
        if isinstance(explicit_payload, list | tuple | set)
        else set(request_options)
    )
    merged.update({key: request_options[key] for key in explicit_keys})
    effective["render_options"] = merged
    # Persist the pre-merge intent: terminal family requests must not mistake
    # inherited scientific defaults for user overrides (or lose legacy ones).
    effective["explicit_render_option_keys"] = sorted(explicit_keys)
    if new_creation:
        transform = (
            resolved_scientific_source.transform
            if resolved_scientific_source is not None
            else None
        )
        effective = freeze_new_spectral_axis_display(
            effective,
            rule_id=str(semantic.get("rule_id") or ""),
            template=template,
            transform_contract=transform.contract.to_payload()
            if transform is not None
            else None,
        )
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
