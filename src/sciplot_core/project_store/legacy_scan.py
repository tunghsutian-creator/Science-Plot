"""Inventory a legacy layout only during its explicit Store admission."""

import os
import stat
from typing import Any

from .errors import ProjectStoreError
from .io import STORE, StoreIO, directory, read_file


def scan_legacy(io: StoreIO) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}

    def walk(fd: int, prefix: str) -> None:
        for name in sorted(os.listdir(fd)):
            if name == STORE or name.startswith(".sciplot-write-"):
                continue
            if not prefix and name == ".sciplot_resources":
                if not any(path.is_relative_to(io.root / name) for path in io.locations.values()):
                    raise ProjectStoreError("An unregistered directory occupies the reserved resource-view namespace.")
                continue
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            logical = prefix + name
            if stat.S_ISDIR(info.st_mode):
                with directory(fd, (name,)) as child:
                    walk(child, logical + "/")
            elif stat.S_ISREG(info.st_mode):
                data, mode = read_file(fd, name)
                if not 0 <= mode <= 0o777:
                    raise ProjectStoreError("Legacy project import refuses special permission bits.")
                files[logical] = {**io.put(data), "mode": mode}
            else:
                raise ProjectStoreError("Portable project import refuses symlink or special members.")

    for key, fd in io.root_fds.items():
        permitted = io.location_members.get(key)
        if key and permitted is not None:
            for relative in permitted:
                logical = f"@{key}/{relative}"
                value = io.physical(logical)
                if value is not None:
                    data, mode = value
                    files[logical] = {**io.put(data), "mode": mode}
        else:
            walk(fd, f"@{key}/" if key else "")
    return files
