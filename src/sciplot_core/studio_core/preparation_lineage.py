"""Bind the scientific study, lineage and publication intent once before native preparation."""

from pathlib import Path
from typing import Any

from sciplot_core.presentation_identity import SelectedPresentationIdentity, project_selected_presentation_to_request
from sciplot_core.publication import build_publication_intent, build_transform_ledger, link_intent_to_transform_ledger
from sciplot_core.studio_core.mechanical_plan_context import normalized_studio_study_model


def bind_preparation_lineage(request: dict[str, Any], primary_render_request: dict[str, Any], *,
                             planning_study_model: dict[str, Any], terminal_series_order: list[str],
                             source_root: Path, transform_steps: list[dict[str, Any]],
                             presentation_identity: SelectedPresentationIdentity) -> None:
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
