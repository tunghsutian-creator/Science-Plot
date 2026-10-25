"""Compile terminal artifacts within their enclosing private project command."""

from pathlib import Path
import os
import stat
from typing import Any

from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.project_store.candidate_runtime import ProjectCandidateResolver
from sciplot_core.project_store.errors import ProjectConflict
from sciplot_core.project_store.io import directory
from sciplot_core.studio_core.preparation_candidate import StudioPreparationCandidate, private_preparation_scope
from sciplot_core.terminal_source_binding import SealedTerminalSourceBinding


class _ArtifactCandidate(StudioPreparationCandidate):
    """One native artifact directory, owned by the enclosing project candidate."""

    @property
    def logical_root(self) -> Path:
        selected = selected_source_resolver()
        if not isinstance(selected, ProjectCandidateResolver):
            raise ProjectConflict("A terminal artifact requires its enclosing private project binding.")
        return Path(selected.literal_path(self.project_dir))


def export_private_request(request: Path, *, formats: list[str],
                           terminal_source_binding: SealedTerminalSourceBinding | None,
                           terminal_source_prepared: bool) -> dict[str, Any] | None:
    """Use an inherited, argv-bound private locator; ordinary requests stay public."""
    selected = selected_source_resolver()
    if not isinstance(selected, ProjectCandidateResolver):
        return None
    if (not request.is_relative_to(selected.candidate_root) or request.parent == selected.candidate_root
            or request.name != "plot_request.json"):
        raise ProjectConflict("A bound private worker must select a nested terminal artifact request.")
    # The inherited native-worker locator has already verified host/argv/root
    # identity. Validate this concrete directory too; never infer a new project.
    selected.resolve_path(request)
    project = request.parent
    if (project / ".sciplot_store").exists():
        raise ProjectConflict("A private terminal artifact cannot contain another project authority.")
    with selected._root() as root:
        with directory(root, project.relative_to(selected.candidate_root).parts) as artifact:
            info = os.fstat(artifact)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                raise ProjectConflict("A terminal artifact directory must remain host-owned.")
            os.fchmod(artifact, 0o700)
    candidate = _ArtifactCandidate(selected.store, selected.snapshot, project, project / ".private-resources")
    if candidate._root_identity != (info.st_dev, info.st_ino):
        raise ProjectConflict("The terminal artifact directory changed before private preparation.")
    from sciplot_core.studio_core.preparation_commands import prepare_studio_candidate, audit_studio_candidate
    from sciplot_core.studio_core.native_export_adapter import export_studio_document

    with private_preparation_scope(candidate):
        payload = prepare_studio_candidate(candidate, request_target=True,
            _terminal_source_binding=terminal_source_binding,
            _terminal_source_prepared=terminal_source_prepared)
        audit_studio_candidate(candidate, payload)
        document = Path(payload["document"])
        exported = export_studio_document(document, formats=formats, output_dir=document.parent / "exports")
        payload["exports"] = exported["exports"]
        candidate.finalize()
        if (project / ".sciplot_store").exists():
            raise ProjectConflict("A terminal artifact producer created another project authority.")
        return payload
