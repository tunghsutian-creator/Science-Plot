"""Complete offline bundle copies preserve identities and original serialized bytes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any, Protocol, TypeVar

from .errors import ProjectConflict, ProjectStoreError
from .io import STORE, StoreIO, directory, install, parts, read_file, sha
from .resources import ResourceRoot

class BundleStore(Protocol):
    root: Path
    locations: dict[str, Path]
    location_members: dict[str, tuple[str, ...] | None]

    def _locked(self, *, import_legacy: bool = False, repair: bool = False,
                allow_pending: bool = False) -> AbstractContextManager[tuple[StoreIO, dict[str, Any]]]: ...


StoreT = TypeVar("StoreT", bound=BundleStore)


def _members(fd: int, prefix: tuple[str, ...] = ()) -> dict[str, tuple[bytes, int]]:
    import stat

    result = {}
    for name in sorted(os.listdir(fd)):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            with directory(fd, (name,)) as child:
                result.update(_members(child, (*prefix, name)))
        elif stat.S_ISREG(info.st_mode):
            result["/".join((*prefix, name))] = read_file(fd, name)
        else:
            raise ProjectStoreError("Portable bundles refuse symbolic or special members.")
    return result


def export_bundle(store: BundleStore, destination: Path) -> Path:
    target = Path(destination).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError("A portable bundle destination must be new.")
    with store._locked() as (io, current):
        members = _members(io.fd)
        target.mkdir(mode=0o700)
        descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            checks = {}
            for name, (data, mode) in members.items():
                components = parts(name)
                with directory(descriptor, ("store", *components[:-1]), create=True) as parent:
                    install(parent, components[-1], data, mode=mode, exclusive=True)
                checks[name] = {"sha256": sha(data), "size": len(data), "mode": mode}
            header = {"kind": "sciplot_project_bundle", "version": 1,
                "project_id": current["project_id"], "generation": current["generation"],
                "location_ids": sorted(store.locations), "location_members": store.location_members, "members": checks}
            install(descriptor, "bundle.json", (json.dumps(header, sort_keys=True,
                    ensure_ascii=False, allow_nan=False) + "\n").encode(), exclusive=True)
        finally:
            os.close(descriptor)
    return target


def import_bundle(bundle: Path, destination: Path, *,
                  factory: Callable[[Path, Mapping[str, Path | ResourceRoot]], StoreT]) -> StoreT:
    import sciplot_core.project_store.projection as projection
    import sciplot_core.project_store.state as state

    source = Path(bundle).expanduser().resolve(strict=True)
    target = Path(destination).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError("Cold import requires a new destination; never replace existing work.")
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        header = json.loads(read_file(source_fd, "bundle.json")[0])
        if header.get("kind") != "sciplot_project_bundle" or header.get("version") != 1:
            raise ProjectStoreError("Unsupported complete project bundle.")
        ids = header["location_ids"]
        if not isinstance(ids, list) or any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) for key in ids):
            raise ProjectStoreError("Invalid portable resource-root IDs.")
        with directory(source_fd, ("store",)) as store_fd:
            members = _members(store_fd)
        if set(members) != set(header["members"]):
            raise ProjectConflict("The portable bundle file membership changed.")
        for name, (data, _mode) in members.items():
            entry = header["members"][name]
            if sha(data) != entry["sha256"] or len(data) != entry["size"]:
                raise ProjectConflict("Portable project bytes differ from their complete bundle inventory.")
        target.mkdir(mode=0o700)
        root_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for name, (data, _mode) in members.items():
                components = parts(name)
                with directory(root_fd, (STORE, *components[:-1]), create=True) as parent:
                    install(parent, components[-1], data, mode=header["members"][name]["mode"], exclusive=True)
            locations = {}
            for key in ids:
                with directory(root_fd, (".sciplot_resources", key), create=True):
                    pass
                allowed = header.get("location_members", {}).get(key)
                locations[key] = ResourceRoot(target / ".sciplot_resources" / key,
                                              tuple(allowed) if allowed is not None else None)
        finally:
            os.close(root_fd)
    finally:
        os.close(source_fd)
    store = factory(target, locations)
    with StoreIO(store.root, store.locations, store.location_members).locked() as io:
        current = state.head(io)
        if current is None or (current["project_id"], current["generation"]) != (header["project_id"], header["generation"]):
            raise ProjectConflict("The portable head differs from its complete bundle binding.")
        io.write("local_locations.json", {"ids": ids, "members": store.location_members})
        source_versions = {source_id: {version: entry["sha256"]
            for version, entry in versions.items()} for source_id, versions in current["sources"].items()}
        import sciplot_core.project_store.commands as commands

        try:
            with directory(io.fd, ("commands",)) as command_fd:
                command_names = sorted(name for name in os.listdir(command_fd) if name.endswith(".json"))
        except FileNotFoundError:
            command_names = []
        for name in command_names:
            record = io.read("commands/" + name)
            if record and record.get("native_workspace") is not None:
                import sciplot_core.project_store.native_work as native_work
                from .io import digest

                _path, identity = native_work.verify(io, record, relocating=True)
                bindings = io.read("local_native_work.json") or {"bindings": {}}
                bindings["bindings"][digest(record["command_id"])] = identity
                io.write("local_native_work.json", bindings)
            if record and record.get("draft") is not None:
                commands.public(io, record)
                for source_id, versions in record["draft"].get("sources", {}).items():
                    for version, entry in versions.items():
                        io.get(entry)
                        source_versions.setdefault(source_id, {})[version] = entry["sha256"]
        io.write("local_sources.json", {"versions": source_versions})
        io.write("relocation.json", {"generation": current["generation"], "files": sorted(current["files"]), "complete": False})
        projection.relocate(io, current)
    return store
