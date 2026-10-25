"""Host-only capability for serializing manifests inside one private candidate."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from threading import get_ident


@dataclass(frozen=True)
class _Candidate:
    root: Path
    descriptor: int
    process: int
    thread: int

    def verify(self) -> None:
        opened, current = os.fstat(self.descriptor), self.root.lstat()
        if (self.process != os.getpid() or self.thread != get_ident()
                or not stat.S_ISDIR(current.st_mode)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
                or current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) != 0o700
                or (self.root / ".sciplot_store/head.json").exists()):
            raise ValueError("A private manifest capability lost its exact host-owned candidate identity.")


_SELECTED: ContextVar[_Candidate | None] = ContextVar("sciplot_private_project_manifest", default=None)


def private_manifest_descriptor(project: Path) -> int | None:
    selected = _SELECTED.get()
    if selected is None or selected.root != project:
        return None
    selected.verify()
    return selected.descriptor


@contextmanager
def private_project_manifest_scope(project: Path) -> Iterator[Path]:
    """The trusted producer explicitly owns this 0700 clone, with no store head."""
    root = project.expanduser().absolute()
    if root.resolve(strict=True) != root:
        raise ValueError("Private project candidates cannot use symbolic directory aliases.")
    previous = _SELECTED.get()
    if previous is not None:
        if previous.root != root:
            raise ValueError("A private manifest scope cannot expand to another candidate.")
        previous.verify()
        yield root
        previous.verify()
        return
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    candidate = _Candidate(root, descriptor, os.getpid(), get_ident())
    try:
        candidate.verify()
        token = _SELECTED.set(candidate)
        try:
            yield root
            candidate.verify()
        finally:
            _SELECTED.reset(token)
    finally:
        os.close(descriptor)
