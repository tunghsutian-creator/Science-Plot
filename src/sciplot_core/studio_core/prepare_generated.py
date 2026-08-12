"""Generate a new exact-current Studio document and its project metadata."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    request_for_figure_task,
    resolve_preparation_figure_plan,
    validate_preparation_figure_plan,
)
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import get_rule
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.presentation_identity import (
    project_selected_presentation_to_request,
    require_selected_template,
)
from sciplot_core.publication import (
    build_publication_intent,
    build_transform_ledger,
    link_intent_to_transform_ledger,
)
from sciplot_core.readiness import load_validated_envelope_registry
from sciplot_core.readiness.rule_certification import (
    current_certified_rule_contract_snapshot,
)
from sciplot_core.semantic_sources.scientific_source import (
    ScientificSourceResolutionError,
    resolve_scientific_source,
)
from sciplot_core.studio_render.models import StudioPreparationBlocked
from sciplot_core.studio_render.value_parsing import _string_list
from sciplot_core.terminal_source_binding import (
    SealedTerminalSourceBinding,
    TerminalSourceBindingError,
)

from sciplot_core.studio_core.context import (
    _converge_studio_request_review_notes,
)
from sciplot_core.studio_core.figure_requests import (
    _impact_condition_figure_queue,
    _impact_condition_figure_request,
    _rheology_frequency_primary_request,
)
from sciplot_core.studio_core.figure_task_evidence import (
    figure_queue_from_plan,
    generic_figure_queue_from_plan,
    primary_figure_task,
)
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.launchers import (
    _write_export_edited_launcher,
    _write_studio_launcher,
    _write_veusz_launcher,
)
from sciplot_core.studio_core.mechanical_plan_context import (
    initial_studio_study_model,
    normalized_studio_study_model,
    studio_presentation_identity,
)
from sciplot_core.studio_core.prepare_generated_transaction import (
    _prepare_generated_figure_set_transaction,
)
from sciplot_core.studio_core.registry_state import (
    _studio_block,
    _veusz_spec_path,
)
from sciplot_core.studio_core.registry_writes import _register_studio_block
from sciplot_core.studio_core.request_paths import _resolve_request_input
from sciplot_core.studio_core.rule_contract_binding import (
    STUDIO_RULE_CONTRACT_BINDING_KEY,
    current_studio_rule_contract_binding,
)
from sciplot_core.studio_core.request_overrides import (
    _apply_studio_request_overrides,
)
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.studio_core.terminal_task_request import (
    is_terminal_worker_request,
    terminal_figure_task_from_request,
)
from sciplot_core.studio_core.source_bound_prepare import (
    prepare_source_bound_figure_queue,
)


def generate_studio_document(
    *,
    project_dir: Path,
    request_path: Path,
    rule_id: str | None,
    template: str | None,
    project_name: str | None,
    figure_set_path_replacer: Callable[[Path, Path], None] | None = None,
    _terminal_source_binding: SealedTerminalSourceBinding | None = None,
    _terminal_source_prepared: bool = False,
) -> dict[str, Any]:
    """Build a generated VSZ plus the publication and figure-set contracts."""

    _apply_studio_request_overrides(
        project_dir,
        request_path=request_path,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    request = _read_json(request_path)
    _converge_studio_request_review_notes(request)
    effective_request, data_mapping_application = resolve_data_mapping_request(
        request,
        base_dir=request_path.parent,
    )
    if data_mapping_application is not None:
        request["transform_ledger"] = deepcopy(effective_request["transform_ledger"])

    terminal_worker = is_terminal_worker_request(
        request,
        request_path=request_path,
    )
    if _terminal_source_binding is not None and not terminal_worker:
        raise TerminalSourceBindingError(
            "terminal_source_binding_request_mismatch",
            "A materialized terminal source is valid only in the internal worker.",
        )
    if _terminal_source_prepared and not terminal_worker:
        raise ValueError(
            "A prepared terminal source is valid only in the internal worker."
        )
    terminal_task = terminal_figure_task_from_request(request)
    request_rule_id = str(request.get("rule_id") or "").strip()
    current_rule = get_rule(request_rule_id) if request_rule_id else None
    presentation_identity = studio_presentation_identity(
        request,
        current_rule=current_rule,
        request_rule_id=request_rule_id,
        terminal_task=terminal_task,
        terminal_worker=terminal_worker,
        has_terminal_source_binding=_terminal_source_binding is not None,
    )
    project_selected_presentation_to_request(request, presentation_identity)
    document_path = project_dir / "studio" / "document.vsz"
    document_path.parent.mkdir(parents=True, exist_ok=True)
    rule_binding = current_studio_rule_contract_binding(
        current_rule,
        registry=load_validated_envelope_registry(),
        snapshot_factory=current_certified_rule_contract_snapshot,
    )
    if rule_binding is not None:
        request[STUDIO_RULE_CONTRACT_BINDING_KEY] = rule_binding.to_payload()
    else:
        request.pop(STUDIO_RULE_CONTRACT_BINDING_KEY, None)
    source_input = _resolve_request_input(request, base_dir=request_path.parent)
    planning_study_model = initial_studio_study_model(
        request,
        current_rule=current_rule,
        request_rule_id=request_rule_id,
        presentation_template=presentation_identity.template,
        source_input=source_input,
        project_dir=project_dir,
    )
    try:
        resolved_scientific_source = (
            resolve_scientific_source(
                source_input,
                rule_id=request_rule_id,
                request=request,
                template=presentation_identity.template,
                study_model=planning_study_model,
            )
            if not terminal_worker and source_input is not None
            else None
        )
        if resolved_scientific_source is not None:
            figure_plan = validate_preparation_figure_plan(
                persisted=request.get("resolved_figure_plan"),
                rule_id=request_rule_id,
                current_plan=resolved_scientific_source.figure_plan,
            )
        else:
            figure_plan = (
                resolve_preparation_figure_plan(
                    persisted=request.get("resolved_figure_plan"),
                    rule_id=request_rule_id,
                    template=presentation_identity.template,
                    study_model=planning_study_model,
                    input_path=source_input,
                    request=request,
                )
                if not terminal_worker
                and (
                    request_rule_id or request.get("resolved_figure_plan") is not None
                )
                else None
            )
    except (FigurePlanResolutionError, ScientificSourceResolutionError) as exc:
        raise StudioPreparationBlocked(exc.reason_code, str(exc)) from exc
    primary_task = terminal_task or (
        primary_figure_task(figure_plan) if figure_plan is not None else None
    )
    if primary_task is not None:
        require_selected_template(
            primary_task.template,
            expected=presentation_identity,
            source=f"resolved FigurePlan primary task `{primary_task.figure_id}`",
        )
    if figure_plan is not None:
        request["resolved_figure_plan"] = figure_plan.to_payload()
    else:
        request.pop("resolved_figure_plan", None)
    impact_queue = (
        []
        if terminal_worker
        else _impact_condition_figure_queue(
            request,
            base_dir=request_path.parent,
            project_dir=project_dir,
            figure_plan=figure_plan,
        )
    )
    performance_queue = figure_queue_from_plan(figure_plan, "performance_comparison")
    generic_queue = generic_figure_queue_from_plan(
        figure_plan,
        render_adapter=(
            current_rule.render_adapter if current_rule is not None else None
        ),
    )
    selected_figure_queue = impact_queue or performance_queue or generic_queue
    primary_impact_figure = (
        next(
            (
                item
                for item in impact_queue
                if primary_task is not None and item.get("id") == primary_task.figure_id
            ),
            None,
        )
        if impact_queue
        else None
    )
    if primary_impact_figure is not None:
        primary_render_request = _impact_condition_figure_request(
            request,
            primary_impact_figure,
        )
    elif figure_plan is not None and figure_plan.rule_id == "rheology_frequency_sweep":
        primary_render_request = _rheology_frequency_primary_request(
            request,
            figure_plan=figure_plan,
        )
    elif primary_task is not None:
        primary_render_request = request_for_figure_task(request, primary_task)
    else:
        primary_render_request = request
    binding_option = (
        {"_terminal_source_binding": _terminal_source_binding.materialized}
        if _terminal_source_binding is not None
        else {}
    )
    (
        source_bound_queue,
        source_bound_attestation,
        source_bound_preparation_steps,
    ) = prepare_source_bound_figure_queue(
        figure_plan=figure_plan,
        source_input=source_input,
        request=primary_render_request,
        base_dir=request_path.parent,
        resolved_scientific_source=resolved_scientific_source,
    )
    series, axis_info, transform_steps, source_root = _series_from_request(
        primary_render_request,
        base_dir=request_path.parent,
        **binding_option,
        _terminal_source_prepared=_terminal_source_prepared,
        _prepared_source_attestation=source_bound_attestation,
        _prepared_transform_steps=source_bound_preparation_steps,
        _resolved_scientific_source=resolved_scientific_source,
    )
    terminal_series_order = _string_list(
        axis_info.get("semantic_terminal_series_order")
    )
    if terminal_series_order:
        request["series_order"] = terminal_series_order
        primary_render_request["series_order"] = terminal_series_order
    if isinstance(axis_info.get("data_mapping_coverage"), dict):
        request["data_mapping_coverage"] = json_safe(axis_info["data_mapping_coverage"])

    study_model = normalized_studio_study_model(planning_study_model)
    request["study_model"] = study_model
    project_selected_presentation_to_request(request, presentation_identity)
    render_defaults = study_model.get("render_defaults")
    if terminal_series_order and isinstance(render_defaults, dict):
        render_defaults["series_order"] = terminal_series_order
    transform_ledger = build_transform_ledger(
        study_model,
        request=request,
        input_path=source_root,
        steps=transform_steps,
        existing=request.get("transform_ledger")
        if isinstance(request.get("transform_ledger"), dict)
        else None,
    )
    publication_intent = build_publication_intent(
        study_model,
        request=request,
        existing=request.get("publication_intent")
        if isinstance(request.get("publication_intent"), dict)
        else None,
    )
    publication_intent = link_intent_to_transform_ledger(
        publication_intent, transform_ledger
    )
    study_model["publication_intent_ref"] = "publication_intent.json"
    for target in (request, primary_render_request):
        target["publication_intent"] = publication_intent
        target["transform_ledger"] = transform_ledger
    figure_set = _prepare_generated_figure_set_transaction(
        project_dir=project_dir,
        request_path=request_path,
        request=request,
        document_path=document_path,
        primary_render_request=primary_render_request,
        series=series,
        axis_info=axis_info,
        presentation_identity=presentation_identity,
        primary_task=primary_task,
        selected_figure_queue=selected_figure_queue,
        source_bound_queue=source_bound_queue,
        source_bound_attestation=source_bound_attestation,
        figure_plan=figure_plan,
        figure_set_path_replacer=figure_set_path_replacer,
    )
    spec_path = _veusz_spec_path(document_path)
    launcher = _write_studio_launcher(project_dir)
    veusz_launcher = _write_veusz_launcher(project_dir, document_path)
    export_edited_launcher = _write_export_edited_launcher(project_dir)
    generated_hash = existing_file_sha256(document_path)
    studio_block = _studio_block(
        document_path=document_path,
        spec_path=spec_path,
        launcher=launcher,
        veusz_launcher=veusz_launcher,
        export_edited_launcher=export_edited_launcher,
        request_path=request_path,
        series_count=len(series),
        generated_hash=generated_hash,
        figure_set=figure_set,
        rule_contract_binding=(
            rule_binding.to_payload() if rule_binding is not None else None
        ),
        resolved_figure_plan=(
            figure_plan.to_payload() if figure_plan is not None else None
        ),
        presentation_identity=presentation_identity.to_payload(),
    )
    _register_studio_block(project_dir, studio_block)
    pending_rule_review = request.get("pending_rule_review") is True
    publication_rule_blocked = bool(
        pending_rule_review
        or (rule_binding is not None and rule_binding.certification_status != "current")
    )
    return {
        "kind": "sciplot_studio_prepare",
        "operation_mode": normal_mode_payload(route="studio"),
        "pending_rule_review": pending_rule_review,
        "publication_rule_blocked": publication_rule_blocked,
        "autonomous_rule_ready": not publication_rule_blocked,
        "project_dir": str(project_dir),
        "request": str(request_path),
        "document": str(document_path),
        "launcher": str(launcher),
        "veusz_launcher": str(veusz_launcher),
        "export_edited_launcher": str(export_edited_launcher),
        "series_count": len(series),
        "document_state": studio_block["document_state"],
        "studio": studio_block,
        "figure_set": figure_set,
        "template": presentation_identity.template,
        "presentation_identity": presentation_identity.to_payload(),
        "rule_contract_binding": (
            rule_binding.to_payload() if rule_binding is not None else None
        ),
    }
