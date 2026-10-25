"""Build one already-owned private Studio project; never route or publish."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.output_contract import REQUEST_DELIVERY_ROOT_KEY
from sciplot_core.studio_core.export_execution import _project_studio_document
from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.preparation_candidate import StudioPreparationCandidate, require_preparation_candidate
from sciplot_core.studio_core.prepare_existing import reuse_existing_studio_document
from sciplot_core.studio_core.prepare_generated import generate_studio_document
from sciplot_core.terminal_source_binding import SealedTerminalSourceBinding


def prepare_private_studio_project(candidate: StudioPreparationCandidate, *, request_target: bool,
                                   request_relative: str, delivery_root: Path | None,
                                   rule_id: str | None, template: str | None, project_name: str | None,
                                   regenerate_generated: bool,
                                   figure_set_path_replacer: Callable[[Path, Path], None] | None,
                                   terminal_source_binding: SealedTerminalSourceBinding | None,
                                   terminal_source_prepared: bool, new_creation: bool) -> dict[str, Any]:
    """Apply configuration and choose exact reuse or scientific generation privately."""
    project = candidate.project_dir
    require_preparation_candidate(project)
    request = project / request_relative
    if delivery_root is not None:
        payload = _read_json(request)
        payload[REQUEST_DELIVERY_ROOT_KEY] = str(delivery_root.expanduser().resolve())
        candidate.write_request(payload, relative=request_relative)
    document = _project_studio_document(project)
    if document is not None:
        document = resolve_source_path(document)
    if (not request_target and document is not None and rule_id is None
            and template is None and project_name is None and not regenerate_generated):
        return reuse_existing_studio_document(project_dir=project, request_path=request, document_path=document)
    return generate_studio_document(project_dir=project, request_path=request,
        rule_id=rule_id, template=template, project_name=project_name,
        figure_set_path_replacer=figure_set_path_replacer,
        _terminal_source_binding=terminal_source_binding,
        _terminal_source_prepared=terminal_source_prepared, _new_creation=new_creation)
