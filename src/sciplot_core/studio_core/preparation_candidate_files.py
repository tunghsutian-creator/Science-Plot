"""Descriptor-only snapshots for one host-owned private Studio candidate."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from sciplot_core.project_commands import PreparedFile
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.io import directory, read_file


def _files(root: Path, *, descriptor: int | None = None) -> dict[str, PreparedFile]:
    """Capture ordinary members through directory descriptors, never aliases."""
    def visit(fd: int, prefix: str) -> dict[str, PreparedFile]:
        result = {}
        for name in sorted(os.listdir(fd)):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            logical = prefix + name
            if stat.S_ISDIR(info.st_mode):
                with directory(fd, (name,)) as child:
                    result.update(visit(child, logical + "/"))
            elif stat.S_ISREG(info.st_mode):
                data, mode = read_file(fd, name, owned=True)
                result[logical] = PreparedFile(data, mode)
            else:
                raise ProjectConflict("A private Studio candidate contains an aliased or special member.")
        return result

    if descriptor is not None:
        return visit(descriptor, "")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return visit(fd, "")
    finally:
        os.close(fd)

