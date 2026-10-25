"""Read exact registered semantic namespaces without granting sibling discovery."""

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import stat
from typing import Any

from .errors import ProjectConflict, ProjectRecoveryRequired, ProjectStoreError
from .io import StoreIO, directory, parts, read_file, sha
from .locators import original_for_logical

OWNER = ".sciplot_semantic_owner.json"


def identity(fd: int) -> dict[str, int]:
    value = os.fstat(fd)
    return {"device": value.st_dev, "inode": value.st_ino, "mode": stat.S_IMODE(value.st_mode)}


def census(fd: int, *, allowed: set[str] | None = None, prefix: str = "") -> dict[str, Any]:
    result = {}
    names = sorted(os.listdir(fd))
    for name in names:
        relative = prefix + name
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if allowed is not None and relative not in allowed and not any(item.startswith(relative + "/") for item in allowed):
            raise ProjectRecoveryRequired("The semantic namespace exceeds its exact trusted member capability.")
        if stat.S_ISDIR(info.st_mode):
            with directory(fd, (name,)) as child:
                result.update(census(child, allowed=allowed, prefix=relative + "/"))
        elif stat.S_ISREG(info.st_mode):
            data, mode = read_file(fd, name)
            if mode > 0o777:
                raise ProjectStoreError("Semantic namespace records require ordinary permission bits.")
            result[relative] = {"data": data, "sha256": sha(data), "size": len(data), "mode": mode}
        else:
            raise ProjectConflict("A semantic namespace contains symbolic or special records.")
    if sorted(os.listdir(fd)) != names:
        raise ProjectConflict("Semantic namespace membership changed while being observed.")
    return result


@contextmanager
def scope(io: StoreIO, prefix: str) -> Iterator[tuple[int, Path, set[str] | None]]:
    components = parts(prefix)
    key = components[0][1:] if components[0].startswith("@") else ""
    relative = components[1:] if key else components
    if not relative or key not in io.root_fds:
        raise ProjectStoreError("A semantic namespace must be an explicit child in its trusted resource root.")
    io.split(prefix + "/head.json")
    root = io.locations[key] if key else io.root
    allowed = io.location_members.get(key)
    suffix = "/".join(relative) + "/"
    members = {name[len(suffix):] for name in allowed if name.startswith(suffix)} if allowed is not None else None
    with directory(io.root_fds[key], relative) as fd:
        yield fd, root / Path(*relative), members


def capture(io: StoreIO, current: dict[str, Any], prefix: str) -> dict[str, Any]:
    if prefix + "/head.json" not in current["files"]:
        raise ProjectStoreError("Only an explicitly registered semantic namespace can be observed.")
    with scope(io, prefix) as (fd, actual, allowed):
        before = identity(fd)
        members = census(fd, allowed=allowed)
        if before != identity(fd):
            raise ProjectConflict("The observed semantic namespace changed directory identity.")
        info = actual.lstat()
        if (info.st_dev, info.st_ino) != (before["device"], before["inode"]):
            raise ProjectConflict("The observed semantic namespace path was replaced.")
    original = str(Path(original_for_logical(current, prefix + "/head.json")).parent)
    return {"prefix": prefix, "path": str(actual), "origin_root": original,
            "directory": before, "members": members}


def descriptors(members: dict[str, Any]) -> dict[str, Any]:
    return {name: {key: value[key] for key in ("sha256", "size", "mode")} for name, value in members.items()}
