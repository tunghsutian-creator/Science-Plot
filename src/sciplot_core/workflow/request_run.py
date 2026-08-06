"""Execute one normalized request inside a managed output transaction."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.assisted_cleanup import (
    consume_ready_cleanup_result,
    write_cleanup_request,
)
from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    resolve_preparation_figure_plan,
)
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import get_rule, resolve_rule_template
from sciplot_core.one_step import build_one_step_project
from sciplot_core.policy import layout_policy_for_semantic
from sciplot_core.publication import (
    build_publication_intent,
    build_transform_step,
    get_publication_profile,
)
from sciplot_core.semantic import build_intervention_request, classify_source
from sciplot_core.study_model import study_model_from_request

from sciplot_core.workflow.project_state import _write_one_step_status
from sciplot_core.workflow.request_io import (
    _archive_raw_input,
    _load_request,
    _managed_output_transaction,
    _resolve_request_path,
)
from sciplot_core.workflow.request_publish import publish_request_result
from sciplot_core.workflow.request_rendering import execute_request_render
from sciplot_core.workflow.route_intent import (
    WorkflowRouteIntent,
    resolve_workflow_route_intent,
)
from sciplot_core.workflow.source_binding import (
    verify_workflow_figure_plan_source_binding,
)


def run_request(
    request_path: Path,
    *,
    _classifier: Callable[..., dict[str, Any]] = classify_source,
) -> dict[str, Any]:
    """Execute a request transactionally under its declared output path."""

    request_path = request_path.expanduser().resolve()
    source_request = _load_request(request_path)
    base_dir = request_path.parent
    output_dir = _resolve_request_path(
        source_request.get("output"),
        base_dir=base_dir,
        field="output",
    )
    with _managed_output_transaction(output_dir):
        return _run_request_in_managed_output(
            request_path=request_path,
            source_request=source_request,
            base_dir=base_dir,
            output_dir=output_dir,
            classifier=_classifier,
        )


def _run_request_in_managed_output(
    *,
    request_path: Path,
    source_request: dict[str, Any],
    base_dir: Path,
    output_dir: Path,
    classifier: Callable[..., dict[str, Any]] = classify_source,
) -> dict[str, Any]:
    """Resolve inputs, enforce semantic gates, then render and publish."""

    original_input_path = _resolve_request_path(
        source_request.get("input"),
        base_dir=base_dir,
        field="input",
    )
    mapped_request, mapping_application = resolve_data_mapping_request(
        source_request,
        base_dir=base_dir,
    )
    request, cleanup_application = consume_ready_cleanup_result(
        mapped_request,
        output_dir=output_dir,
        request_path=request_path,
    )
    if mapping_application is not None and cleanup_application is not None:
        raise ValueError(
            "A confirmed DataMappingProposal and assisted cleanup cannot both "
            "replace the same input in one run."
        )
    route_intent = resolve_workflow_route_intent(request)
    input_path = _resolve_request_path(
        request.get("input"),
        base_dir=base_dir,
        field="input",
    )
    raw_archive = _archive_request_inputs(
        original_input_path=original_input_path,
        input_path=input_path,
        output_dir=output_dir,
        mapping_application=mapping_application,
        cleanup_application=cleanup_application,
    )
    atomic_write_json(
        output_dir / "request_snapshot.json",
        json_safe(request),
    )
    requested_rule_id = (
        request.get("rule_id") if isinstance(request.get("rule_id"), str) else None
    )
    semantic = classifier(input_path, requested_rule_id=requested_rule_id)
    _validate_semantic_template(semantic, request=request)
    study_model = study_model_from_request(
        request=request,
        semantic=semantic,
        input_path=input_path,
    )
    semantic_rule_id = str(semantic.get("rule_id") or "").strip()
    effective_template = (
        resolve_rule_template(
            semantic_rule_id,
            (
                request.get("template")
                if isinstance(request.get("template"), str)
                else None
            ),
        )
        if semantic_rule_id
        else str(request.get("template") or semantic.get("template") or "curve")
    )
    try:
        figure_plan = resolve_preparation_figure_plan(
            persisted=request.get("resolved_figure_plan"),
            rule_id=semantic_rule_id,
            template=effective_template,
            study_model=study_model,
            input_path=input_path,
            request=request,
        )
    except FigurePlanResolutionError as exc:
        raise ValueError(f"{exc.reason_code}: {exc}") from exc
    request = deepcopy(request)
    if figure_plan is not None:
        request["resolved_figure_plan"] = figure_plan.to_payload()
    else:
        request.pop("resolved_figure_plan", None)
    atomic_write_json(
        output_dir / "request_snapshot.json",
        json_safe(request),
    )
    verify_workflow_figure_plan_source_binding(
        figure_plan,
        input_path=input_path,
        raw_archive=raw_archive,
    )
    publication_intent = build_publication_intent(
        study_model,
        request=request,
        existing=(
            request.get("publication_intent")
            if isinstance(request.get("publication_intent"), dict)
            else None
        ),
    )
    publication_profile = get_publication_profile(
        publication_intent["target_profile_id"]
    )
    transform_steps = _initial_transform_steps(
        mapping_application=mapping_application,
        cleanup_application=cleanup_application,
        original_input_path=original_input_path,
        input_path=input_path,
    )
    layout_policy = layout_policy_for_semantic(
        semantic,
        template=request.get("template"),
    )
    _enforce_intervention_gate(
        request_path=request_path,
        request=request,
        route_intent=route_intent,
        semantic=semantic,
        input_path=input_path,
        output_dir=output_dir,
        raw_archive=raw_archive,
        study_model=study_model,
        layout_policy=layout_policy,
    )
    rendered = execute_request_render(
        request=request,
        route_intent=route_intent,
        semantic=semantic,
        study_model=study_model,
        input_path=input_path,
        output_dir=output_dir,
        base_dir=base_dir,
        transform_steps=transform_steps,
    )
    return publish_request_result(
        request_path=request_path,
        source_request=source_request,
        request=request,
        mapping_application=mapping_application,
        cleanup_application=cleanup_application,
        semantic=semantic,
        input_path=input_path,
        raw_archive=raw_archive,
        study_model=study_model,
        publication_intent=publication_intent,
        publication_profile=publication_profile,
        transform_steps=transform_steps,
        layout_policy=layout_policy,
        output_dir=output_dir,
        rendered=rendered,
    )


def _archive_request_inputs(
    *,
    original_input_path: Path,
    input_path: Path,
    output_dir: Path,
    mapping_application: dict[str, Any] | None,
    cleanup_application: dict[str, Any] | None,
) -> dict[str, Any]:
    raw_archive = _archive_raw_input(
        original_input_path if mapping_application is not None else input_path,
        output_dir,
    )
    if (
        mapping_application is not None
        and original_input_path.resolve() != input_path.resolve()
    ):
        raw_archive["effective_input"] = _archive_raw_input(input_path, output_dir)
    if (
        cleanup_application is not None
        and original_input_path.resolve() != input_path.resolve()
    ):
        raw_archive["pre_cleanup_input"] = _archive_raw_input(
            original_input_path,
            output_dir,
        )
    return raw_archive


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


def _initial_transform_steps(
    *,
    mapping_application: dict[str, Any] | None,
    cleanup_application: dict[str, Any] | None,
    original_input_path: Path,
    input_path: Path,
) -> list[dict[str, Any]]:
    steps = [
        deepcopy(step)
        for step in (
            mapping_application.get("transform_steps", [])
            if mapping_application is not None
            else []
        )
        if isinstance(step, dict)
    ]
    if cleanup_application is not None:
        steps.append(
            build_transform_step(
                step_id="assisted_cleanup",
                operation="confirmed_cleanup",
                input_path=original_input_path,
                output_path=input_path,
                implementation_ref=(
                    "sciplot_core.assisted_cleanup.consume_ready_cleanup_result"
                ),
                parameters={
                    "cleanup_result": cleanup_application["cleanup_result"],
                    "mapping_proposal": cleanup_application["mapping_proposal"],
                    "request_patch": cleanup_application["request_patch"],
                    "human_confirmed": True,
                },
            )
        )
    return steps


def _enforce_intervention_gate(
    *,
    request_path: Path,
    request: dict[str, Any],
    route_intent: WorkflowRouteIntent,
    semantic: dict[str, Any],
    input_path: Path,
    output_dir: Path,
    raw_archive: dict[str, Any],
    study_model: dict[str, Any],
    layout_policy: Any,
) -> None:
    pending_rule_blocked = semantic.get("rule_readiness") == "pending"
    if not (
        semantic.get("needs_ai_intervention")
        and (route_intent.uses_semantic_preparation or pending_rule_blocked)
    ):
        return
    intervention = build_intervention_request(
        input_path=input_path,
        output_dir=output_dir,
        semantic=semantic,
        request=request,
    )
    intervention_path = output_dir / "intervention_request.json"
    intervention_path.write_text(
        json.dumps(json_safe(intervention), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_cleanup_request(
        output_dir,
        input_path=input_path,
        reason=str(intervention.get("category") or "semantic_intervention"),
        semantic=semantic,
        request=request,
        intervention_request=intervention_path,
        provider="codex",
    )
    one_step_status = build_one_step_project(
        input_path=input_path,
        request_path=request_path,
        request=request,
        semantic=semantic,
        raw_archive=raw_archive,
        study_model=study_model,
        layout_policy=layout_policy,
        layout_quality={},
        qa=None,
        delivery_package=None,
        intervention_request=intervention,
    )
    _write_one_step_status(output_dir, one_step_status)
    failure = (
        f"Requested material rule `{semantic.get('rule_id')}` is pending fixture-backed acceptance."
        if pending_rule_blocked
        else "SciPlot could not auto-detect this input."
    )
    raise ValueError(f"{failure} Intervention request written to {intervention_path}.")
