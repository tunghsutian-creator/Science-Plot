"""Public write admission against the selected saved figure's actual authority."""
from pathlib import Path
from typing import Any

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.project_lifecycle.repository_router import ComposedProjectRepository
from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets
from sciplot_core.studio_core.legacy_saved_plot import conversion_required


def require_public_editable(target: Path, *, figure_id: str | None = None,
                            prior_review: dict[str, Any] | None = None) -> None:
    from sciplot_core.workflow.native_suite_objects import resolve_native_object

    target = canonical_path(target)
    if resolve_native_object(target, figure_id, repair=False) is not None:
        return
    repository = ComposedProjectRepository()
    with repository.invocation_scope():
        saved = FilesystemProjectTargets(repository).read_legacy_saved(target, figure_id)
    if saved is not None and not _known_review(target, prior_review):
        raise conversion_required(saved[1])


def _known_review(target: Path, review: dict[str, Any] | None) -> bool:
    """Only a stored review may use the existing authenticated apply owner."""
    if review is None:
        return False
    operation_id = review.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        return False
    from sciplot_core.project_commands import ProjectCommands
    from sciplot_core.project_store.io import STORE
    from sciplot_core.studio_core.document_edit_legacy import read_edit_operation
    from sciplot_core.studio_core.document_edit_state import history_directory
    from sciplot_core.studio_core.project_command_scope import project_store
    from sciplot_core.studio_core.project_query import resolve_project_path

    project = resolve_project_path(target)
    if (project / STORE / "head.json").is_file():
        record = ProjectCommands(project_store(project)).query(operation_id)
        if record is not None and record.get("metadata", {}).get("kind") == "document_edit" and (
                record.get("phase") in {"needs_review", "accepted", "complete"}):
            return True  # The actual apply owner still verifies the unchanged signed review.
    return ((history_directory(project, operation_id) / "outcome.json").is_file() and
            read_edit_operation(project, operation_id).get("result_is_current") is True)
