"""Execute one normalized request inside a managed output transaction."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sciplot_core.assisted_cleanup import (
    consume_ready_cleanup_result,
    write_cleanup_request,
)
from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    ResolvedFigurePlan,
)
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.one_step import build_one_step_project
from sciplot_core.policy import layout_policy_for_semantic
from sciplot_core.publication import (
    build_publication_intent,
    get_publication_profile,
)
from sciplot_core.semantic import build_intervention_request, classify_source
from sciplot_core.semantic_sources.scientific_source import (
    ScientificSourceResolutionError,
)
from sciplot_core.study_model import study_model_from_request

from sciplot_core.workflow.project_state import _write_one_step_status
from sciplot_core.workflow.errors import WorkflowIntervention
from sciplot_core.workflow.request_io import (
    _archive_request_inputs,
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
    initial_transform_steps,
    verify_workflow_figure_plan_source_binding,
)
from sciplot_core.semantic_sources.scientific_source_models import ResolvedScientificSource
from sciplot_core.workflow.scientific_source_resolution import (
    _validate_semantic_template,
    bind_workflow_semantic_render_options,
    record_workflow_selection,
    resolve_workflow_scientific_source,
)


if TYPE_CHECKING:
    from sciplot_core.plan_preview import PlanPreviewResolution


def run_request(
    request_path: Path,
    *,
    _classifier: Callable[..., dict[str, Any]] = classify_source,
    _new_creation: bool = False,
    _previous_request: dict[str, Any] | None = None,
    _incoming_request: dict[str, Any] | None = None,
    _observed_plan: PlanPreviewResolution | None = None,
) -> dict[str, Any]:
    """Execute a request transactionally under its declared output path."""

    request_path = request_path.expanduser().resolve()
    source_request = _load_request(request_path) if _incoming_request is None else deepcopy(_incoming_request)
    from sciplot_core.workflow.project_requests import recognized_project, run_project_request
    from sciplot_core.studio_core.managed_frequency_query import is_frequency_project_request
    if is_frequency_project_request(request_path):
        raise ValueError("Resume this Managed frequency project with its original project creation or task.")

    if recognized_project(request_path):
        return run_project_request(request_path, source_request, execute=_run_request_in_managed_output,
            classifier=_classifier, new_creation=_new_creation, previous_request=_previous_request,
            **({"observed_plan": _observed_plan} if _observed_plan is not None else {}))
    if _incoming_request is not None:
        raise ValueError("An incoming project intent requires the exact registered project request.")
    base_dir = request_path.parent
    output_dir = _resolve_request_path(
        source_request.get("output"),
        base_dir=base_dir,
        field="output",
    )
    from sciplot_core.foundation.research_destination import require_data_destination
    require_data_destination(output_dir)
    from sciplot_core.output_contract import requested_delivery_root
    delivery = require_data_destination(requested_delivery_root({"request": source_request}, run_output=output_dir))
    from .frequency_managed_workflow import managed_frequency_session, reuse_completed_frequency_run

    source_path = resolve_source_path(_resolve_request_path(
        source_request.get("input"), base_dir=base_dir, field="input",
    )).resolve()
    if source_path.is_dir():
        for destination in (output_dir.resolve(), delivery):
            if any(ancestor.is_dir() and ancestor.samefile(source_path)
                   for ancestor in (destination, *destination.parents)):
                raise ValueError(f"Output would write inside the original source: {destination}. Choose a new directory.")

    session, authority = managed_frequency_session(output_dir, source_request, new_creation=_new_creation)
    reference = _resolve_request_path(source_request["data_mapping_execution"], base_dir=base_dir,
        field="data_mapping_execution") if source_request.get("data_mapping_execution") else None
    original = (_resolve_request_path(source_request.get("input"), base_dir=base_dir, field="input")
                if reference is not None and _observed_plan is not None else None)
    with session, mapping_input_reads(str(reference) if reference is not None else None, expected_source=original):
        if authority is not None:
            prior = reuse_completed_frequency_run(authority, source_request, output_dir, request_path=request_path)
            if prior is not None:
                return prior
        from sciplot_core.delivery.filesystem_metadata import is_delivery_finder_metadata
        from sciplot_core.policy import DELIVERY_DIR
        if delivery != (output_dir / DELIVERY_DIR).resolve() and delivery.exists():
            if not delivery.is_dir() or any(not is_delivery_finder_metadata(p) for p in delivery.iterdir()):
                raise ValueError(f"Delivery output is already occupied: {delivery}. Choose a new directory.")
        with _managed_output_transaction(output_dir):
            return _run_request_in_managed_output(
                request_path=request_path,
                source_request=source_request,
                base_dir=base_dir,
                output_dir=output_dir,
                classifier=_classifier,
                new_creation=_new_creation,
                previous_request=_previous_request,
                frequency_authority=authority,
                **({"observed_plan": _observed_plan} if _observed_plan is not None else {}),
            )


def _run_request_in_managed_output(
    *,
    request_path: Path,
    source_request: dict[str, Any],
    base_dir: Path,
    output_dir: Path,
    classifier: Callable[..., dict[str, Any]] = classify_source,
    new_creation: bool = False,
    previous_request: dict[str, Any] | None = None,
    staged_delivery: tuple[Path, Path] | None = None,
    update_project: bool = True,
    previous_delivery: dict[str, Any] | None = None,
    frequency_authority: Path | None = None, frequency_prepared: Any = None,
    frequency_required: bool = False,
    observed_scientific_source: ResolvedScientificSource | None = None,
    observed_plan: PlanPreviewResolution | None = None,
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
    if observed_plan is not None:
        if cleanup_application is not None:
            raise ValueError("Approved plan cannot be replaced by assisted cleanup; make a new plan.")
        observed_scientific_source = observed_plan.scientific_source
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
    if observed_plan is not None:
        _require_approved_original(observed_plan, output_dir / "raw" / Path(raw_archive["path"]).name)
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
        resolved_scientific_source, figure_plan = resolve_workflow_scientific_source(
            input_path=input_path,
            rule_id=semantic_rule_id,
            template=effective_template,
            study_model=study_model,
            request=request,
            observed=observed_scientific_source,
        )
    except (FigurePlanResolutionError, ScientificSourceResolutionError) as exc:
        raise ValueError(f"{exc.reason_code}: {exc}") from exc
    if observed_plan is not None and (
        (figure_plan.to_payload() if figure_plan is not None else None)
        != observed_plan.payload["resolved_figure_plan"]
    ):
        raise ValueError("Workflow figure selection differs from the approved plan; make a new plan.")
    request = deepcopy(request)
    if figure_plan is not None:
        request["resolved_figure_plan"] = figure_plan.to_payload()
    else:
        request.pop("resolved_figure_plan", None)
    request = bind_workflow_semantic_render_options(
        request=request,
        semantic=semantic,
        figure_plan=figure_plan,
        resolved_scientific_source=resolved_scientific_source,
        new_creation=new_creation,
        previous_request=previous_request,
        selected_template=effective_template,
    )
    if new_creation:
        source_request = record_workflow_selection(source_request, request)
        atomic_write_json(request_path, source_request)
    atomic_write_json(
        output_dir / "request_snapshot.json",
        json_safe(request),
    )
    verify_workflow_figure_plan_source_binding(
        figure_plan,
        input_path=input_path,
        raw_archive=raw_archive,
        resolved_scientific_source=resolved_scientific_source,
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
    transform_steps = initial_transform_steps(
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
        figure_plan=figure_plan,
    )
    managed_result = None
    if frequency_authority is not None and resolved_scientific_source is not None:
        from .frequency_managed_workflow import render_managed_frequency

        managed_result = render_managed_frequency(resolved_scientific_source, authority=frequency_authority,
            output=output_dir, source_request=source_request, prepared=frequency_prepared)
    if managed_result is None and (frequency_required or (frequency_authority is not None and frequency_authority.exists())):
        raise ValueError("The Managed frequency output belongs to its exact original request.")
    rendered = execute_request_render(
        request=request,
        route_intent=route_intent,
        semantic=semantic,
        study_model=study_model,
        input_path=input_path,
        output_dir=output_dir,
        base_dir=base_dir,
        transform_steps=transform_steps,
        resolved_scientific_source=resolved_scientific_source,
        _resolved_figure_plan=figure_plan,
        _managed_result=managed_result,
    )
    if observed_plan is not None:
        _require_approved_original(observed_plan, original_input_path)
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
        _staged_delivery=staged_delivery,
        _update_project=update_project,
        previous_delivery=previous_delivery,
    )


def _require_approved_original(observed: PlanPreviewResolution, original: Path) -> None:
    identity = observed.payload["preview_identity"]
    if identity is None or source_tree_sha256(original) != identity["source_tree_sha256"]:
        raise ValueError("Original input changed after plan approval; make a new plan.")


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
    figure_plan: ResolvedFigurePlan | None = None,
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
        _output_namespace=output_dir,
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
        resolved_figure_plan=figure_plan,
    )
    _write_one_step_status(output_dir, one_step_status)
    failure = (
        f"Requested material rule `{semantic.get('rule_id')}` is pending fixture-backed acceptance."
        if pending_rule_blocked
        else "SciPlot could not auto-detect this input."
    )
    raise WorkflowIntervention(f"{failure} Intervention request written to {literal_source_path(intervention_path)}.")
