"""Generate a new exact-current Studio document and its project metadata."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.publication import (
    build_publication_intent,
    build_transform_ledger,
    link_intent_to_transform_ledger,
)
from sciplot_core.study_model import normalize_study_model
from sciplot_core.studio_render.value_parsing import _string_list

from sciplot_core.studio_core.context import (
    _converge_studio_request_review_notes,
)
from sciplot_core.studio_core.document_archive import (
    _archive_manual_document_if_needed,
)
from sciplot_core.studio_core.figure_requests import (
    _impact_condition_figure_queue,
    _impact_condition_figure_request,
    _rheology_frequency_primary_request,
)
from sciplot_core.studio_core.figure_set_prepare import (
    _prepare_studio_figure_set,
)
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.launchers import (
    _write_export_edited_launcher,
    _write_studio_launcher,
    _write_veusz_launcher,
)
from sciplot_core.studio_core.registry_state import _studio_block
from sciplot_core.studio_core.registry_writes import _register_studio_block
from sciplot_core.studio_core.request_overrides import (
    _apply_studio_request_overrides,
)
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.studio_core.veusz_document import _write_veusz_document


def generate_studio_document(
    *,
    project_dir: Path,
    request_path: Path,
    rule_id: str | None,
    template: str | None,
    project_name: str | None,
    figure_set_path_replacer: Callable[[Path, Path], None] | None = None,
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

    document_path = project_dir / "studio" / "document.vsz"
    document_path.parent.mkdir(parents=True, exist_ok=True)
    _archive_manual_document_if_needed(project_dir, document_path)
    impact_queue = _impact_condition_figure_queue(
        request,
        base_dir=request_path.parent,
        project_dir=project_dir,
    )
    primary_render_request = (
        _impact_condition_figure_request(request, impact_queue[0])
        if impact_queue
        else _rheology_frequency_primary_request(request)
    )
    series, axis_info, transform_steps, source_root = _series_from_request(
        primary_render_request,
        base_dir=request_path.parent,
    )
    terminal_series_order = _string_list(
        axis_info.get("semantic_terminal_series_order")
    )
    if terminal_series_order:
        request["series_order"] = terminal_series_order
        primary_render_request["series_order"] = terminal_series_order
    if isinstance(axis_info.get("data_mapping_coverage"), dict):
        request["data_mapping_coverage"] = json_safe(axis_info["data_mapping_coverage"])

    study_model = normalize_study_model(
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {
            "kind": "sciplot_study_model",
            "version": 1,
            "samples": [],
            "figure_queue": [],
        }
    )
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
    request["study_model"] = study_model
    request["publication_intent"] = publication_intent
    request["transform_ledger"] = transform_ledger
    request_path.write_text(
        json.dumps(json_safe(request), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    spec_path = _write_veusz_document(
        document_path,
        request=primary_render_request,
        series=series,
        axis_info=axis_info,
    )
    figure_set = _prepare_studio_figure_set(
        project_dir=project_dir,
        request_path=request_path,
        request=request,
        primary_document=document_path,
        primary_series_count=len(series),
        primary_generated_hash=existing_file_sha256(document_path),
        preserve_existing=False,
        queue_override=impact_queue or None,
        path_replacer=figure_set_path_replacer,
    )
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
    )
    _register_studio_block(project_dir, studio_block)
    return {
        "kind": "sciplot_studio_prepare",
        "operation_mode": normal_mode_payload(route="studio"),
        "pending_rule_review": request.get("pending_rule_review") is True,
        "autonomous_rule_ready": request.get("pending_rule_review") is not True,
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
    }
