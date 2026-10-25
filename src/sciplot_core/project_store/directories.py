"""Closed directory views contain only exact registered generation members."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any
from uuid import uuid4

from .errors import ProjectConflict, ProjectStoreError
from .io import STORE, StoreIO, digest, directory, install, parts, read_file, sha
import sciplot_core.project_store.state as state


def _prefix(value: dict[str, Any], literal: Path, locations: dict[str, Path]) -> tuple[str, str] | None:
    matches = {}
    for key, root in [*value["locators"].items(), *[(key, str(path)) for key, path in locations.items()]]:
        parent = Path(root)
        if not literal.is_relative_to(parent):
            continue
        relative = literal.relative_to(parent)
        suffix = "" if relative == Path(".") else relative.as_posix() + "/"
        if suffix:
            parts(suffix.rstrip("/"))
        prefix = f"@{key}/" + suffix if key else suffix
        members = {name: entry for name, entry in value["files"].items()
                   if name.startswith(prefix) and (prefix or not name.startswith("@"))}
        if members:
            original = str(Path(value["locators"][key]) / relative)
            matches[prefix] = original
    if len(matches) > 1:
        raise ProjectConflict("The source directory matches multiple registered generation roots.")
    return next(iter(matches.items())) if matches else None


def _names(fd: int, prefix: str = "") -> set[str]:
    result = set()
    for name in os.listdir(fd):
        if name == STORE:
            continue
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            with directory(fd, (name,)) as child:
                result.update(_names(child, prefix + name + "/"))
        elif stat.S_ISREG(info.st_mode):
            result.add(prefix + name)
        else:
            raise ProjectConflict("A registered source directory contains symbolic or special outside members.")
    return result


def _verify_tree(fd: int, members: dict[str, Any], io: StoreIO) -> None:
    if _names(fd) != set(members):
        raise ProjectConflict("A closed directory view has unregistered or missing members.")
    for relative, entry in members.items():
        components = parts(relative)
        with directory(fd, components[:-1]) as parent:
            if read_file(parent, components[-1])[0] != io.get(entry):
                raise ProjectConflict("A closed directory member differs from its immutable identity.")


def version(members: dict[str, Any]) -> str:
    return digest({"kind": "directory", "files": [
        {"path": name, "content_sha256": entry["sha256"]} for name, entry in sorted(members.items())]})


def resolve(io: StoreIO, value: dict[str, Any], literal: Path, *, expected_sha256: str | None = None) -> Path | None:
    selected = _prefix(value, literal, {"": io.root, **io.locations})
    if selected is None:
        return None
    prefix, original = selected
    members = {name[len(prefix):]: entry for name, entry in value["files"].items()
               if name.startswith(prefix) and (prefix or not name.startswith("@"))}
    if not members:
        return None
    if expected_sha256 is not None and version(members) != expected_sha256:
        raise ProjectConflict("The registered source directory has another explicit version.")
    for relative, entry in members.items():
        physical = io.physical(prefix + relative)
        if physical is None or sha(physical[0]) != entry["sha256"]:
            raise ProjectConflict("The registered source directory changed outside its generation.")
    components = tuple(prefix.rstrip("/").split("/")) if prefix else ()
    key = components[0][1:] if components and components[0].startswith("@") else ""
    relative_parts = components[1:] if key else components
    if io.location_members.get(key) is None:
        with directory(io.root_fds[key], relative_parts) as actual:
            if _names(actual) != set(members):
                raise ProjectConflict("The original source directory has unregistered outside members.")
    descriptor = {"generation": value["generation"], "prefix": prefix, "original": original, "members": members}
    identity = digest(descriptor)
    base = ("directories", value["generation"])
    with directory(io.fd, base, create=True) as parent:
        try:
            with directory(parent, (identity,)) as view:
                _verify_tree(view, members, io)
        except FileNotFoundError:
            temporary = ".stage-" + uuid4().hex
            os.mkdir(temporary, mode=0o700, dir_fd=parent)
            with directory(parent, (temporary,)) as stage:
                for relative, entry in members.items():
                    leaf = parts(relative)
                    with directory(stage, leaf[:-1], create=True) as folder:
                        install(folder, leaf[-1], io.get(entry), mode=0o400, exclusive=True)
                _verify_tree(stage, members, io)
            metadata = "/".join((*base, identity + ".json"))
            try:
                io.write(metadata, descriptor, exclusive=True)
            except FileExistsError:
                if io.read(metadata) != descriptor:
                    raise ProjectConflict("The closed directory descriptor changed.") from None
            os.rename(temporary, identity, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
    return io.root / STORE / Path(*base, identity)


def owned_view(io: StoreIO, value: dict[str, Any], actual: Path, *, expected_sha256: str | None = None) -> tuple[Path, str] | None:
    base = io.root / STORE / "directories"
    if not actual.is_relative_to(base):
        return None
    components = actual.relative_to(base).parts
    if len(components) < 2:
        raise ProjectStoreError("The directory cache path has no registered view identity.")
    generation, identity, *relative = components
    state.reachable(io, value, generation)
    descriptor = io.read(f"directories/{generation}/{identity}.json")
    if descriptor is None or digest(descriptor) != identity:
        raise ProjectConflict("The directory cache descriptor no longer matches its registered identity.")
    with directory(io.fd, ("directories", generation, identity)) as view:
        _verify_tree(view, descriptor["members"], io)
    if not relative:
        if expected_sha256 is not None and version(descriptor["members"]) != expected_sha256:
            raise ProjectConflict("The cached source directory has another explicit version.")
        for name, entry in descriptor["members"].items():
            current = value["files"].get(descriptor["prefix"] + name)
            physical = io.physical(descriptor["prefix"] + name)
            if current is None or current["sha256"] != entry["sha256"] or physical is None or sha(physical[0]) != entry["sha256"]:
                raise ProjectConflict("The cached directory no longer matches the selected source generation.")
        return actual, descriptor["original"]
    name = "/".join(relative)
    entry = descriptor["members"].get(name)
    current = value["files"].get(descriptor["prefix"] + name)
    if entry is None or current is None or entry["sha256"] != current["sha256"]:
        raise ProjectConflict("The cached source member is not the selected generation version.")
    if expected_sha256 is not None and entry["sha256"] != expected_sha256:
        raise ProjectConflict("The cached source member has another explicit version.")
    physical = io.physical(descriptor["prefix"] + name)
    if physical is None or sha(physical[0]) != entry["sha256"]:
        raise ProjectConflict("The original registered source member changed outside its generation.")
    return actual, str(Path(descriptor["original"]) / Path(*relative))
