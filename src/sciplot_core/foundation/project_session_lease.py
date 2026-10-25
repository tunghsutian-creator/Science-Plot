"""Kernel exclusion for unidentified legacy native sessions and project writers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
from typing import Any


class ProjectSessionBusy(ValueError):
    reason_code = "project_busy"


def _reject_symbolic_path(path: Path) -> None:
    if any(member.is_symlink() for member in (path, *path.parents)):
        raise ValueError(f"A project session cannot follow symbolic links: {path}")


class ProjectSessionLease:
    """Retain the existing namespace; process death releases the kernel lease."""

    def __init__(self, project: Path, *, native: bool) -> None:
        _reject_symbolic_path(project)
        self.project = project.resolve()
        digest = hashlib.sha256(str(self.project).encode()).hexdigest()
        directory = self.project.parent / ".sciplot_session_locks"
        _reject_symbolic_path(directory)
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / f"{digest}.lock"
        _reject_symbolic_path(path)
        self.fd: int | None = os.open(
            path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(self.fd, (fcntl.LOCK_SH if native else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.close()
            raise ProjectSessionBusy(
                "This project has a writable Veusz session or an external edit in "
                "progress. Close its writable windows and retry from current state.") from exc
        except BaseException:
            self.close()
            raise

    def close(self, *_args: Any) -> None:
        if self.fd is not None:
            descriptor, self.fd = self.fd, None
            os.close(descriptor)

    def __enter__(self) -> ProjectSessionLease:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


@contextmanager
def external_project_session(project: Path) -> Iterator[None]:
    with ProjectSessionLease(project, native=False):
        yield
