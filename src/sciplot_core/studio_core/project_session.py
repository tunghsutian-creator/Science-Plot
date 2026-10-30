"""Cross-process exclusion between native document sessions and external edits."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.studio_core.context import _project_context_for_document
from sciplot_core.foundation.project_session_lease import (
    ProjectSessionBusy as ProjectSessionBusy,
    ProjectSessionLease as ProjectSessionLease,
    external_project_session as external_project_session,
)


@dataclass
class _ScopedNativeSession:
    project: Path
    binding: dict[str, Any]

    def close(self, *_args: Any) -> None:
        """A known draft holds a read witness, not a lifetime project writer lock."""


def _capture_binding(project: Path, target: Path) -> dict[str, Any] | None:
    from sciplot_core.studio_core.project_query import resolve_project_figure
    from sciplot_core.studio_core.native_adoption import adopt_saved_native
    from sciplot_core.studio_core.project_command_scope import figure_read_state, project_store
    from sciplot_core.project_store.errors import ProjectStoreError
    from sciplot_core.project_store.runtime import project_runtime

    try:
        selected = resolve_project_figure(target)
    except (ValueError, OSError, KeyError):
        return None
    # An unidentified or scientifically unbound window remains conservative.
    try:
        repository = project_store(project)
        # Explicit Open/Save As admits a writer. Core owns atomic initialization;
        # a read-only query must never import an old project on its behalf.
        repository.admit_open(before_import=lambda: figure_read_state(project, selected))
        with project_runtime(repository):
            return adopt_saved_native(project, selected)
    except ProjectStoreError:
        # An existing generation must be explicitly recovered or reconciled;
        # falling back to an unidentified window could load a mixed projection.
        raise
    except (ValueError, OSError, KeyError):
        return None


def close_window_session(window: Any) -> None:
    lease = getattr(window, "_sciplot_project_session", None)
    if lease is not None:
        lease.close()
    window._sciplot_project_session = None


@contextmanager
def window_document_session(window: Any, target: Path, *, loading: bool = False) -> Iterator[None]:
    """Acquire before loading/saving; retain the old lease when the action fails."""
    context = _project_context_for_document(target)
    project = context["project_dir"] if context else None
    previous = getattr(window, "_sciplot_project_session", None)
    if previous is not None and previous.project == project and not loading:
        yield
        return
    if previous is not None and previous.project == project and not isinstance(previous, _ScopedNativeSession):
        # Keep unidentified existing windows excluded until explicit close or
        # Save As; never discard their conservative protection during a reload.
        yield
        return
    binding = _capture_binding(project, target) if project else None
    lease = (_ScopedNativeSession(project, binding) if project and binding is not None
             else ProjectSessionLease(project, native=True) if project else None)
    try:
        yield
    except BaseException:
        if lease is not None:
            lease.close()
        raise
    else:
        actual = Path(str(getattr(window, "filename", "") or "")).resolve()
        if actual != target.expanduser().resolve():
            if lease is not None:
                lease.close()
            return
        close_window_session(window)
        window._sciplot_project_session = lease
        if isinstance(lease, _ScopedNativeSession):
            from sciplot_core.studio_core.project_command_scope import project_store
            from sciplot_core.studio_core.persistence import bind_project_document_save

            window.document._sciplot_project_read_set = lease.binding
            window.document._sciplot_project_store = project_store(lease.project)
            bind_project_document_save(window.document, lease.project, target)
        if lease is not None and hasattr(window, "destroyed"):
            window.destroyed.connect(lease.close)
