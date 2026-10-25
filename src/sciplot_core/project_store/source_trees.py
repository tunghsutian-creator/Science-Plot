"""Read-only exact source-tree witnesses; never grant an output resource root."""

import os
from pathlib import Path
import stat
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands.resources import SourceTreeRead

from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO, directory, read_file, sha


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


def _selected(io: StoreIO, current: dict[str, Any], locator: str) -> tuple[str, set[str] | None]:
    literal = Path(locator)
    matches = []
    for key, saved in current["locators"].items():
        if key and key not in io.locations:
            continue
        root = Path(saved)
        if not literal.is_relative_to(root):
            continue
        relative = literal.relative_to(root).as_posix()
        logical = ("@" + key + ("/" + relative if relative != "." else "")) if key else (relative if relative != "." else "")
        if not any(name == logical or name.startswith(logical + "/") or not logical and not name.startswith("@")
                   for name in current["files"]):
            continue
        host = io.locations[key] if key else io.root
        members = io.location_members.get(key)
        prefix = relative + "/" if relative != "." else ""
        allowed = {name[len(prefix):] for name in members if name.startswith(prefix)} if members is not None else None
        if members is not None and relative != "." and relative not in members and not allowed:
            continue
        matches.append((str(host / relative), allowed))
    if len({path for path, _allowed in matches}) > 1:
        raise ProjectConflict("A selected source tree has ambiguous preserved root mappings.")
    return matches[0] if matches else (locator, None)


def require(io: StoreIO, current: dict[str, Any], record: dict[str, Any], *, admit: bool = False) -> None:
    values = record.get("metadata", {}).get("source_trees", [])
    if not isinstance(values, list):
        raise ProjectStoreError("Source trees require closed selected-source read witnesses.")
    if (values and record.get("draft") is not None
            and record["draft"].get("source_tree_origins") != record.get("source_tree_origins")):
        raise ProjectConflict("The selected source-tree admission differs from its sealed candidate proof.")
    seen = set()
    for supplied in values:
        if not isinstance(supplied, dict) or set(supplied) != {"locator", "tree_sha256"}:
            raise ProjectStoreError("A source-tree read must bind only its exact locator and composite hash.")
        guard = SourceTreeRead(**supplied)
        locator = guard.locator
        if not isinstance(locator, str) or locator in seen:
            raise ProjectStoreError("Source-tree reads require distinct canonical source locators.")
        seen.add(locator)
        actual, allowed = _selected(io, current, locator)
        version, observed = observe(actual, allowed=allowed)
        observed["actual"] = actual
        if version != guard.tree_sha256:
            raise ProjectConflict("A selected source tree changed its complete file membership or bytes.")
        if admit:
            record.setdefault("source_tree_origins", {})[locator] = observed
        if record.get("source_tree_origins", {}).get(locator) != observed:
            raise ProjectConflict("A selected source tree changed its admitted inode or permissions.")
