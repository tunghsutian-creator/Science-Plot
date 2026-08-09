"""Reuse an existing Studio document without regenerating user edits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.figure_plan import (
    FigurePlanResolutionError,
    resolve_current_figure_plan,
)
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.mechanical_figure_contract import MECHANICAL_RULE_IDS
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.presentation_identity import (
    project_selected_presentation_to_request,
    resolve_selected_presentation_identity,
)
from sciplot_core.studio_render.models import StudioPreparationBlocked

from sciplot_core.studio_core.context import (
    _converge_studio_request_review_notes,
)
from sciplot_core.studio_core.export_execution import _count_veusz_series
from sciplot_core.studio_core.figure_requests import (
    _impact_condition_figure_queue,
)
from sciplot_core.studio_core.figure_set_prepare import (
    _prepare_studio_figure_set,
)
from sciplot_core.studio_core.figure_set_state import _read_studio_figure_set
from sciplot_core.studio_core.figure_set_storage import (
    _commit_studio_figure_set_transaction,
)
from sciplot_core.studio_core.figure_task_evidence import (
    validate_figure_registry_against_plan,
)
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.launchers import (
    _write_export_edited_launcher,
    _write_studio_launcher,
    _write_veusz_launcher,
)
from sciplot_core.studio_core.presentation_evidence import (
    validate_prepared_studio_presentation,
)
from sciplot_core.studio_core.registry_state import (
    _registered_generated_hash,
    _studio_block,
    _veusz_spec_path,
)
from sciplot_core.studio_core.registry_writes import _register_studio_block
from sciplot_core.studio_core.request_paths import _resolve_request_input
from sciplot_core.studio_core.rule_readiness import (
    resolve_studio_rule_publication_readiness,
)


def reuse_existing_studio_document(
    *,
    project_dir: Path,
    request_path: Path,
    document_path: Path,
) -> dict[str, Any]:
    """Refresh Studio metadata while preserving the exact-current VSZ."""

    request = _read_json(request_path)
    request_changed = _converge_studio_request_review_notes(request)
    rule_readiness = resolve_studio_rule_publication_readiness(request)
    request_rule_id = rule_readiness.rule_id or ""
    current_rule = rule_readiness.current_rule
    presentation_identity = resolve_selected_presentation_identity(
        request,
        current_rule=current_rule,
    )
    request_changed = (
        project_selected_presentation_to_request(request, presentation_identity)
        or request_changed
    )
    try:
        figure_plan = (
            resolve_current_figure_plan(
                persisted=request.get("resolved_figure_plan"),
                rule_id=request_rule_id,
                template=presentation_identity.template,
                study_model=(
                    request.get("study_model")
                    if isinstance(request.get("study_model"), dict)
                    else {}
                ),
                input_path=_resolve_request_input(
                    request,
                    base_dir=request_path.parent,
                ),
                request=request,
            )
            if request_rule_id or request.get("resolved_figure_plan") is not None
            else None
        )
    except FigurePlanResolutionError as exc:
        raise StudioPreparationBlocked(exc.reason_code, str(exc)) from exc
    validate_prepared_studio_presentation(
        project_dir=project_dir,
        document_path=document_path,
        identity=presentation_identity,
        figure_plan=figure_plan,
    )
    if (
        figure_plan is not None
        and request.get("resolved_figure_plan") != figure_plan.to_payload()
    ):
        request["resolved_figure_plan"] = figure_plan.to_payload()
        request_changed = True
    impact_queue = _impact_condition_figure_queue(
        request,
        base_dir=request_path.parent,
        project_dir=project_dir,
        figure_plan=figure_plan,
    )
    staged_request = (
        request_path.with_name(f".sciplot-studio-reuse-{uuid4().hex}.json")
        if request_changed
        else None
    )
    try:
        if staged_request is not None:
            staged_request.write_text(
                json.dumps(json_safe(request), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            _read_json(staged_request)
        if figure_plan is not None and figure_plan.rule_id in MECHANICAL_RULE_IDS:
            figure_set = _read_studio_figure_set(project_dir)
            if figure_set is None:
                raise StudioPreparationBlocked(
                    "mechanical_figure_set_mismatch",
                    "Mechanical exact-current reuse requires its complete "
                    "registered figure set.",
                )
            try:
                validate_figure_registry_against_plan(figure_set, figure_plan)
            except (TypeError, ValueError) as exc:
                raise StudioPreparationBlocked(
                    "mechanical_figure_set_mismatch",
                    str(exc),
                ) from exc
            replacements: list[dict[str, Any]] = []
            if staged_request is not None:
                staged_hash = existing_file_sha256(staged_request)
                if not staged_hash:
                    raise RuntimeError("The staged Studio request is empty.")
                replacements.append(
                    {
                        "staged": staged_request,
                        "target": request_path,
                        "expected_hash": staged_hash,
                        "kind": "request",
                    }
                )
            _commit_studio_figure_set_transaction(
                project_dir=project_dir,
                replacements=replacements,
                manual_archive_requests=[],
                registry=None,
            )
        else:
            figure_set = _prepare_studio_figure_set(
                project_dir=project_dir,
                request_path=request_path,
                request=request,
                primary_document=document_path,
                staged_request=staged_request,
                preserve_existing=True,
                queue_override=impact_queue or None,
                figure_plan=figure_plan,
            )
    finally:
        if staged_request is not None:
            staged_request.unlink(missing_ok=True)
    launcher = _write_studio_launcher(project_dir)
    veusz_launcher = _write_veusz_launcher(project_dir, document_path)
    export_edited_launcher = _write_export_edited_launcher(project_dir)
    studio_block = _studio_block(
        document_path=document_path,
        spec_path=_veusz_spec_path(document_path),
        launcher=launcher,
        veusz_launcher=veusz_launcher,
        export_edited_launcher=export_edited_launcher,
        request_path=request_path,
        series_count=_count_veusz_series(document_path),
        generated_hash=_registered_generated_hash(project_dir),
        figure_set=figure_set,
        rule_contract_binding=(
            rule_readiness.prepared_binding.to_payload()
            if rule_readiness.prepared_binding is not None
            else None
        ),
        resolved_figure_plan=(
            figure_plan.to_payload() if figure_plan is not None else None
        ),
        presentation_identity=presentation_identity.to_payload(),
    )
    _register_studio_block(project_dir, studio_block)
    return {
        "kind": "sciplot_studio_prepare",
        "operation_mode": normal_mode_payload(route="studio"),
        "pending_rule_review": rule_readiness.pending_rule_review,
        "publication_rule_blocked": rule_readiness.publication_blocked,
        "autonomous_rule_ready": not rule_readiness.publication_blocked,
        "project_dir": str(project_dir),
        "request": str(request_path),
        "document": str(document_path),
        "launcher": str(launcher),
        "veusz_launcher": str(veusz_launcher),
        "export_edited_launcher": str(export_edited_launcher),
        "series_count": studio_block["series_count"],
        "document_state": studio_block["document_state"],
        "studio": studio_block,
        "figure_set": figure_set,
        "template": presentation_identity.template,
        "presentation_identity": presentation_identity.to_payload(),
        "preserved_existing_document": True,
    }
