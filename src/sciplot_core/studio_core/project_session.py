"""Cross-process exclusion between native document sessions and external edits."""

from __future__ import annotations

import fcntl
import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sciplot_core.studio_core.context import _project_context_for_document
from sciplot_core.studio_core.source_update_commit import reject_symlink_path


class ProjectSessionBusy(ValueError):
    """A native writable session or another external transaction owns the project."""


class ProjectSessionLease:
    def __init__(self, project: Path, *, native: bool) -> None:
        reject_symlink_path(project)
        self.project = project.resolve()
        digest = hashlib.sha256(str(self.project).encode()).hexdigest()
        directory = self.project.parent / ".sciplot_session_locks"
        reject_symlink_path(directory)
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / f"{digest}.lock"
        reject_symlink_path(path)
        self.fd: int | None = os.open(
            path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            operation = fcntl.LOCK_SH if native else fcntl.LOCK_EX
            fcntl.flock(self.fd, operation | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.close()
            raise ProjectSessionBusy(
                "This project has a writable Veusz session or an external edit in "
                "progress. Close its writable windows and retry from current state."
            ) from exc
        except BaseException:
            self.close()
            raise

    def close(self, *_args: Any) -> None:
        if self.fd is not None:
            descriptor, self.fd = self.fd, None
            os.close(descriptor)


@contextmanager
def external_project_session(project: Path) -> Iterator[None]:
    lease = ProjectSessionLease(project, native=False)
    try:
        yield
    finally:
        lease.close()


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
