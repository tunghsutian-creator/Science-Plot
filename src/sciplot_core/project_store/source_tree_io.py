"""Descriptor-anchored observation of one selected file or complete raw tree."""

import os
from pathlib import Path
import stat
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256

from .errors import ProjectConflict, ProjectStoreError
from .io import directory, read_file, sha


def _identity(value: os.stat_result) -> dict[str, int]:
    return {"device": value.st_dev, "inode": value.st_ino, "mode": value.st_mode}


def _stamp(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _files(fd: int, *, prefix: str = "", allowed: set[str] | None = None) -> tuple[list[dict[str, str]], dict[str, Any]]:
    files: list[dict[str, str]] = []
    identities: dict[str, dict[str, Any]] = {}
    before = _stamp(os.fstat(fd))
    names = sorted(os.listdir(fd))
    stamps = {}
    for name in names:
        relative = prefix + name
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        stamps[name] = _stamp(info)
        if allowed is not None and relative not in allowed and not any(item.startswith(relative + "/") for item in allowed):
            raise ProjectConflict("The selected source tree exceeds its exact registered file capability.")
        identities[relative] = {**_identity(info), "_stamp": stamps[name]}
        if stat.S_ISDIR(info.st_mode):
            with directory(fd, (name,)) as child:
                children, descendants = _files(child, prefix=relative + "/", allowed=allowed)
                files.extend(children)
                identities.update(descendants)
        elif stat.S_ISREG(info.st_mode):
            data, _mode = read_file(fd, name)
            files.append({"path": relative, "content_sha256": sha(data)})
        else:
            raise ProjectConflict("A selected source tree contains a symbolic or special member.")
        if _stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) != stamps[name]:
            raise ProjectConflict("A selected source tree member changed inode or permissions while being read.")
    if (sorted(os.listdir(fd)) != names or _stamp(os.fstat(fd)) != before
            or any(_stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) != stamps[name] for name in names)):
        raise ProjectConflict("A selected source tree changed membership or identity while being read.")
    for relative, observed in identities.items():
        components = Path(relative[len(prefix):]).parts
        with directory(fd, components[:-1]) as parent:
            if _stamp(os.stat(components[-1], dir_fd=parent, follow_symlinks=False)) != observed["_stamp"]:
                raise ProjectConflict("A selected source tree changed an earlier member during observation.")
    return files, identities


def observe(locator: str, *, allowed: set[str] | None = None) -> tuple[str, dict[str, Any]]:
    path = Path(locator)
    if (not path.is_absolute() or str(path) != locator or any(part in {".", ".."} for part in path.parts)
            or path == Path("/")):
        raise ProjectStoreError("A source-tree witness requires one exact canonical absolute source.")
    try:
        base = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with directory(base, path.parts[1:-1]) as parent:
                info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                root = _identity(info)
                if stat.S_ISDIR(info.st_mode):
                    with directory(parent, (path.name,)) as source:
                        files, members = _files(source, allowed=allowed)
                        members = {name: {key: value for key, value in entry.items() if key != "_stamp"}
                                   for name, entry in members.items()}
                    payload: dict[str, Any] = {"kind": "directory", "files": files}
                elif stat.S_ISREG(info.st_mode):
                    data, _mode = read_file(parent, path.name)
                    members = {}
                    payload = {"kind": "file", "content_sha256": sha(data)}
                else:
                    raise ProjectConflict("A selected source tree is not an ordinary file or directory.")
                if _stamp(info) != _stamp(os.stat(path.name, dir_fd=parent, follow_symlinks=False)):
                    raise ProjectConflict("The selected source tree changed root identity while being read.")
                actual = path.lstat()
                if root != _identity(actual):
                    raise ProjectConflict("The selected source tree locator changed ownership while being read.")
        finally:
            os.close(base)
    except OSError as exc:
        raise ProjectConflict("The exact selected source tree is missing, aliased, or no longer readable.") from exc
    return canonical_json_sha256(payload, allow_nan=False), {"root": root, "members": members}
