"""Cross-process exclusion between native document sessions and external edits."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.studio_core.context import _project_context_for_document
from sciplot_core.foundation.project_session_lease import (
    ProjectSessionBusy as ProjectSessionBusy,
    ProjectSessionLease as ProjectSessionLease,
    external_project_session as external_project_session,
)


def close_window_session(window: Any) -> None:
    lease = getattr(window, "_sciplot_project_session", None)
    if lease is not None:
        lease.close()
    window._sciplot_project_session = None


@contextmanager
def window_document_session(window: Any, target: Path) -> Iterator[None]:
    """Acquire before loading/saving; retain the old lease when the action fails."""
    context = _project_context_for_document(target)
    project = context["project_dir"] if context else None
    previous = getattr(window, "_sciplot_project_session", None)
    if previous is not None and previous.project == project:
        yield
        return
    lease = ProjectSessionLease(project, native=True) if project else None
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
        if lease is not None and hasattr(window, "destroyed"):
            window.destroyed.connect(lease.close)
