"""A mutable mapping request destination is not a scientific input version."""
from pathlib import Path
import os
import stat

from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.source_locations import selected_source_resolver
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.candidate_runtime import ProjectCandidateResolver
from sciplot_core.project_store.io import directory, parts
from sciplot_core.project_store.locators import logical_for_literal
from sciplot_core.project_store.source_resolver import ProjectSourceResolver
from sciplot_core.data_mapping.execution_inputs import mapping_imported_execution


def _ordinary(fd: int, components: tuple[str, ...], mode: int | None = None) -> None:
    with directory(fd, components[:-1]) as parent:
        info = os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or mode is not None and stat.S_IMODE(info.st_mode) != mode):
        raise ProjectConflict("A mapping request destination must remain an ordinary unaliased member.")


def require_mapping_candidate(execution: Path, candidate: Path) -> None:
    """Check destination structure only; seed bytes retain immutable authority.

    A complete explicit import replays its sealed inputs, not the obsolete
    destination on another host. This does not grant that destination any IO.
    """
    path = canonical_path(candidate)
    selected = selected_source_resolver()
    if isinstance(selected, ProjectCandidateResolver):
        logical = selected.logical_resource(path)
        if logical is not None:
            entry = selected.snapshot['files'].get(logical)
            if entry is None:
                raise ProjectConflict("A mapping request destination is not an admitted candidate member.")
            with selected._namespace(logical) as (fd, local):
                _ordinary(fd, parts(local), entry['mode'])
            return
    if isinstance(selected, ProjectSourceResolver):
        logical = logical_for_literal(selected.snapshot, str(path))
        if logical is not None:
            path = selected.store.projection_path(logical)  # Preserve current preimage validation.
        elif (any(path.is_relative_to(root) for root in selected._primary_roots)
              or any(selected._in_resource(path, root, members) for root, members in selected._resource_roots)):
            raise ProjectConflict("A mapping request destination is outside the admitted member set.")
        elif mapping_imported_execution(execution):
            return  # No live destination claim in an explicitly imported historical execution.
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _ordinary(fd, path.parts[1:])
    finally:
        os.close(fd)
