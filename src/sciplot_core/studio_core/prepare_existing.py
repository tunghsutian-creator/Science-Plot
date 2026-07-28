"""Reuse an existing Studio document without regenerating user edits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.operation_modes import normal_mode_payload

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
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.launchers import (
    _write_export_edited_launcher,
    _write_studio_launcher,
    _write_veusz_launcher,
)
from sciplot_core.studio_core.registry_state import (
    _registered_generated_hash,
    _studio_block,
    _veusz_spec_path,
)
from sciplot_core.studio_core.registry_writes import _register_studio_block


def reuse_existing_studio_document(
    *,
    project_dir: Path,
    request_path: Path,
    document_path: Path,
) -> dict[str, Any]:
    """Refresh Studio metadata while preserving the exact-current VSZ."""

    request = _read_json(request_path)
    if _converge_studio_request_review_notes(request):
        request_path.write_text(
            json.dumps(json_safe(request), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    impact_queue = _impact_condition_figure_queue(
        request,
        base_dir=request_path.parent,
        project_dir=project_dir,
    )
    figure_set = _prepare_studio_figure_set(
        project_dir=project_dir,
        request_path=request_path,
        request=request,
        primary_document=document_path,
        preserve_existing=True,
        queue_override=impact_queue or None,
    )
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
        "series_count": studio_block["series_count"],
        "document_state": studio_block["document_state"],
        "studio": studio_block,
        "figure_set": figure_set,
        "preserved_existing_document": True,
    }
