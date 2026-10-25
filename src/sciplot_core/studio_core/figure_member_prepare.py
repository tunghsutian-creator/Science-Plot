"""Prepare and validate one disposable native figure before aggregate installation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.figure_plan import FigureTask
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.preparation_source_attestation import PreparationSourceAttestation
from sciplot_core.studio_core.figure_task_evidence import validate_veusz_spec_figure_task
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.preparation_candidate import require_preparation_candidate
from sciplot_core.studio_core.registry_state import _veusz_spec_path
from sciplot_core.studio_core.series_request import _series_from_request
from sciplot_core.studio_core.veusz_document import _write_veusz_document
from sciplot_core.terminal_source_binding import MaterializedTerminalSourceBinding


@dataclass(frozen=True)
class PreparedFigureMember:
    document: Path
    spec: Path
    document_hash: str
    spec_hash: str
    series_count: int


def prepare_figure_member(*, project_dir: Path, request_path: Path, document_path: Path,
                          figure_request: dict[str, Any], terminal_source_binding: MaterializedTerminalSourceBinding | None,
                          prepared_source_attestation: PreparationSourceAttestation | None,
                          task: FigureTask | None, figure_id: str) -> PreparedFigureMember:
    """Own per-member parse/render/validation and cleanup, without any live writer."""
    require_preparation_candidate(project_dir)
    if not document_path.is_relative_to(project_dir):
        raise ValueError("A prepared native member must belong to this private candidate.")
    staged_document = document_path.with_name(f".sciplot-figure-set-transaction-{uuid4().hex}.vsz")
    staged_spec = _veusz_spec_path(staged_document)
    try:
        series, axis_info, _steps, _source = _series_from_request(
            figure_request, base_dir=request_path.parent,
            _terminal_source_binding=terminal_source_binding,
            _prepared_source_attestation=None if terminal_source_binding is not None else prepared_source_attestation)
        _write_veusz_document(staged_document, request=figure_request, series=series, axis_info=axis_info)
        document_hash = existing_file_sha256(staged_document)
        spec_hash = existing_file_sha256(staged_spec)
        spec_kind = _read_json(staged_spec).get("kind")
        if not document_hash or not spec_hash or spec_kind != "sciplot_veusz_plot_spec":
            raise RuntimeError(f"Staged figure generation was incomplete for {figure_id}.")
        if task is not None:
            validate_veusz_spec_figure_task(_read_json(staged_spec), expected=task,
                                          source=f"staged Studio figure `{figure_id}` Veusz spec")
        return PreparedFigureMember(staged_document, staged_spec, document_hash, spec_hash, len(series))
    except BaseException:
        staged_document.unlink(missing_ok=True)
        staged_spec.unlink(missing_ok=True)
        raise
