"""Stage the primary Studio document and commit its generated figure set."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.figure_plan import FigureTask, ResolvedFigurePlan
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.presentation_identity import SelectedPresentationIdentity
from sciplot_core.studio_render.models import StudioSeries

from sciplot_core.studio_core.figure_set_prepare import _prepare_studio_figure_set
from sciplot_core.studio_core.figure_task_evidence import (
    validate_veusz_spec_figure_task,
)
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.presentation_evidence import (
    validate_veusz_spec_presentation,
)
from sciplot_core.studio_core.registry_state import (
    _registered_generated_hash,
    _veusz_spec_path,
)
from sciplot_core.studio_core.veusz_document import _write_veusz_document


def _prepare_generated_figure_set_transaction(
    *,
    project_dir: Path,
    request_path: Path,
    request: dict[str, Any],
    document_path: Path,
    primary_render_request: dict[str, Any],
    series: list[StudioSeries],
    axis_info: dict[str, Any],
    presentation_identity: SelectedPresentationIdentity,
    primary_task: FigureTask | None,
    selected_figure_queue: list[dict[str, Any]],
    source_bound_queue: list[dict[str, Any]],
    source_bound_attestation: PreparationSourceAttestation | None,
    figure_plan: ResolvedFigurePlan | None,
    figure_set_path_replacer: Callable[[Path, Path], None] | None,
) -> dict[str, Any] | None:
    """Stage and validate the primary document inside one figure-set transaction."""

    transaction_id = uuid4().hex
    staged_stem = f".sciplot-studio-prepare-{transaction_id}"
    staged_request = request_path.with_name(f"{staged_stem}.json")
    staged_document = document_path.with_name(f"{staged_stem}.vsz")
    staged_spec = _veusz_spec_path(staged_document)
    prior_generated_hash = _registered_generated_hash(project_dir)
    try:
        staged_request.write_text(
            json.dumps(json_safe(request), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _read_json(staged_request)
        _write_veusz_document(
            staged_document,
            request=primary_render_request,
            series=series,
            axis_info=axis_info,
        )
        generated_hash = existing_file_sha256(staged_document)
        if not generated_hash or not existing_file_sha256(staged_spec):
            raise RuntimeError("The staged primary Studio document is incomplete.")
        staged_spec_payload = _read_json(staged_spec)
        validate_veusz_spec_presentation(
            staged_spec_payload,
            expected=presentation_identity,
            source="staged primary Veusz spec",
        )
        if primary_task is not None:
            validate_veusz_spec_figure_task(
                staged_spec_payload,
                expected=primary_task,
                source="staged primary Veusz spec",
            )
        return _prepare_studio_figure_set(
            project_dir=project_dir,
            request_path=request_path,
            request=request,
            primary_document=document_path,
            primary_series_count=len(series),
            primary_generated_hash=generated_hash,
            primary_prior_generated_hash=prior_generated_hash,
            primary_staged_document=staged_document,
            primary_staged_spec=staged_spec,
            staged_request=staged_request,
            preserve_existing=False,
            queue_override=selected_figure_queue or source_bound_queue or None,
            figure_plan=figure_plan,
            prepared_source_attestation=source_bound_attestation,
            path_replacer=figure_set_path_replacer,
        )
    finally:
        staged_request.unlink(missing_ok=True)
        staged_document.unlink(missing_ok=True)
        staged_spec.unlink(missing_ok=True)
