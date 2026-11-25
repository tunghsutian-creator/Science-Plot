"""Complete offline bundle copies preserve identities and original serialized bytes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any, Protocol, TypeVar

from .errors import ProjectConflict, ProjectStoreError
from .io import STORE, StoreIO, _identity, digest, directory, install, parts, read_file
from .resources import ResourceRoot

from sciplot_core.delivery.install import install_new_delivery
from sciplot_core.foundation.research_destination import require_data_destination

class BundleStore(Protocol):
    root: Path
    locations: dict[str, Path]
    location_members: dict[str, tuple[str, ...] | None]

    def _locked(self, *, import_legacy: bool = False, repair: bool = False,
                allow_pending: bool = False) -> AbstractContextManager[tuple[StoreIO, dict[str, Any]]]: ...


StoreT = TypeVar("StoreT", bound=BundleStore)


def _members(fd: int, prefix: str = "") -> set[str]:
    files: set[str] = set()
    for name in os.listdir(fd):
        kind = os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
        if stat.S_ISDIR(kind):
            with directory(fd, (name,)) as child:
                files.update(_members(child, prefix + name + "/"))
        elif stat.S_ISREG(kind):
            files.add(prefix + name)
        else:
            raise ProjectStoreError("Portable bundles refuse symbolic or special members.")
    return files


def _copy_member(source: int, target: int, name: str, *, mode: int | None = None) -> dict[str, Any]:
    components = parts(name)
    if mode is not None and (type(mode) is not int or not 0 <= mode <= 0o777):
        raise ProjectStoreError("Portable project files require ordinary permission bits.")
    with directory(source, components[:-1]) as origin, directory(target, components[:-1], create=True) as dest:
        filename = components[-1]
        descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=origin)
        with os.fdopen(descriptor, "rb") as incoming:
            info = os.fstat(incoming.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ProjectStoreError("Portable bundles accept only ordinary files.")
            permissions = stat.S_IMODE(info.st_mode) if mode is None else mode
            if permissions > 0o777:
                raise ProjectStoreError("Portable project files require ordinary permission bits.")
            identity = _identity(info)
            hash_bytes = hashlib.sha256()
            count = 0
            output = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, permissions, dir_fd=dest)
            with os.fdopen(output, "wb") as copied:
                while chunk := incoming.read(1024 * 1024):
                    copied.write(chunk)
                    hash_bytes.update(chunk)
                    count += len(chunk)
                os.fchmod(copied.fileno(), permissions)
                copied.flush()
                os.fsync(copied.fileno())
            if (count != info.st_size or _identity(os.fstat(incoming.fileno())) != identity
                    or _identity(os.stat(filename, dir_fd=origin, follow_symlinks=False)) != identity):
                raise ProjectConflict("A project member changed during the portable copy.")
        os.fsync(dest)
    return {"sha256": hash_bytes.hexdigest(), "size": count, "mode": permissions}


def _closure(io: StoreIO, current: dict[str, Any], paths: set[str]) -> tuple[set[str], dict[str, int]]:
    import sciplot_core.project_store.state as state

    # Keep command receipts (including unknown outcomes) and native work exactly
    # as admitted. Only prune abandoned generations, unbound draft descriptors,
    # unreachable CAS objects and prepared input views rebuilt on cold import.
    reachable = {"head.json"}
    blobs: dict[str, int] = {}

    def select(entries: Any) -> None:
        for entry in entries:
            if entry is None:
                continue
            key, size = entry["sha256"], entry["size"]
            if (not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
                    or type(size) is not int or size < 0):
                raise ProjectConflict("Invalid content identity in complete project history.")
            name = f"objects/{key[:2]}/{key}"
            if blobs.setdefault(name, size) != size:
                raise ProjectConflict("One project object has conflicting recorded sizes.")
            reachable.add(name)

    cursor = current
    while True:
        reachable.add(f"generations/{cursor['generation']}.json")
        select(cursor["files"].values())
        select(entry for items in cursor["sources"].values() for entry in items.values())
        if cursor["parent"] is None:
            break
        cursor = state.generation(io, cursor["parent"])
    for record in state.read_commands(io, expected=current["commands"]):
        if record.get("draft") is None:
            continue
        draft = state.sealed_draft(io, record)
        prefix = f"drafts/{digest(record['command_id'])}/{record['decision_id']}"
        reachable.add(prefix + ".json")
        reachable.update(name for name in paths if name.startswith(prefix + "/"))
        select(draft["writes"].values())
        select(draft["artifacts"].values())
        select(entry for items in draft["sources"].values() for entry in items.values())
    if not reachable <= paths:
        raise ProjectConflict("The portable generation or command closure lost a required member or blob.")
    copied = reachable | {name for name in paths if name.split("/", 1)[0] not in
                          {"generations", "objects", "drafts", "prepared_inputs"}}
    return copied, blobs


def _target(destination: Path) -> Path:
    target = Path(destination).expanduser().absolute()
    require_data_destination(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("A portable project destination must be new.")
    # Match the Store's canonical root convention (including the Mac /var alias).
    return target.parent.resolve(strict=True) / target.name


def export_bundle(store: BundleStore, destination: Path) -> Path:
    target = _target(destination)
    with store._locked() as (io, current):
        from .namespace_transfers import reject_pending_bundle
        from .root_bindings import require

        reject_pending_bundle(io, current)
        require(io, current)
        paths = _members(io.fd)
        members, blobs = _closure(io, current, paths)
        with TemporaryDirectory(prefix=".sciplot-bundle-", dir=target.parent) as temporary:
            candidate = Path(temporary) / "bundle"
            candidate.mkdir(mode=0o700)
            descriptor = os.open(candidate, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                with directory(descriptor, ("store",), create=True) as folder:
                    checks = {name: _copy_member(io.fd, folder, name) for name in sorted(members)}
                for name, size in blobs.items():
                    if (checks[name]["sha256"], checks[name]["size"]) != (Path(name).name, size):
                        raise ProjectConflict("A referenced project blob changed during the portable copy.")
                if _members(io.fd) != paths:
                    raise ProjectConflict("Project file membership changed during portable export.")
                require(io, current)
                header = {"kind": "sciplot_project_bundle", "version": 1,
                          "project_id": current["project_id"], "generation": current["generation"],
                          "location_ids": sorted(store.locations), "location_members": store.location_members, "members": checks}
                install(descriptor, "bundle.json", (json.dumps(header, sort_keys=True,
                        ensure_ascii=False, allow_nan=False) + "\n").encode(), exclusive=True)
            finally:
                os.close(descriptor)
            install_new_delivery(candidate, target)
    return target


def _locations(root: Path, header: dict[str, Any]) -> dict[str, ResourceRoot]:
    ids = header["location_ids"]
    if (not isinstance(ids, list) or any(not isinstance(key, str) or not
            re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) for key in ids) or len(ids) != len(set(ids))):
        raise ProjectStoreError("Invalid portable resource-root IDs.")
    allowed = header.get("location_members", {})
    return {key: ResourceRoot(root / ".sciplot_resources" / key,
                              tuple(allowed[key]) if allowed.get(key) is not None else None) for key in ids}


def _capture_bundle(source: Path, candidate: Path) -> dict[str, Any]:
    source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        raw, _mode = read_file(source_fd, "bundle.json")
        header = json.loads(raw)
        if header.get("kind") != "sciplot_project_bundle" or header.get("version") != 1:
            raise ProjectStoreError("Unsupported complete project bundle.")
        locations = _locations(candidate, header)
        expected = header["members"]
        root_fd = os.open(candidate, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with directory(source_fd, ("store",)) as store_fd, directory(root_fd, (STORE,), create=True) as copied:
                if _members(store_fd) != set(expected):
                    raise ProjectConflict("The portable bundle file membership changed.")
                for name, entry in sorted(expected.items()):
                    if _copy_member(store_fd, copied, name, mode=entry["mode"]) != entry:
                        raise ProjectConflict("Portable project bytes differ from their complete bundle inventory.")
                if _members(store_fd) != set(expected):
                    raise ProjectConflict("The portable bundle file membership changed during copy.")
            if read_file(source_fd, "bundle.json")[0] != raw:
                raise ProjectConflict("The portable bundle inventory changed during copy.")
            for key in locations:
                with directory(root_fd, (".sciplot_resources", key), create=True):
                    pass
        finally:
            os.close(root_fd)
    finally:
        os.close(source_fd)
    return header


def import_bundle(bundle: Path, destination: Path, *,
                  factory: Callable[[Path, Mapping[str, Path | ResourceRoot]], StoreT]) -> StoreT:
    source = Path(bundle).expanduser().resolve(strict=True)
    target = _target(destination)
    with TemporaryDirectory(prefix=".sciplot-import-", dir=target.parent) as temporary:
        candidate = Path(temporary) / "project"
        candidate.mkdir(mode=0o700)
        header = _capture_bundle(source, candidate)
        _restore(factory(candidate, _locations(candidate, header)), header)
        install_new_delivery(candidate, target)
    return factory(target, _locations(target, header))


def _restore(store: BundleStore, header: dict[str, Any]) -> None:
    import sciplot_core.project_store.projection as projection
    import sciplot_core.project_store.state as state

    with StoreIO(store.root, store.locations, store.location_members).locked(writer=True) as io:
        current = state.head(io)
        if current is None or (current["project_id"], current["generation"]) != (header["project_id"], header["generation"]):
            raise ProjectConflict("The portable head differs from its complete bundle binding.")
        from .root_bindings import identities

        _members_to_restore, blobs = _closure(io, current, set(header["members"]))
        if any((header["members"][name]["sha256"], header["members"][name]["size"]) !=
               (Path(name).name, size) for name, size in blobs.items()):
            raise ProjectConflict("A referenced historical or command blob differs from its recorded identity.")
        records = state.read_commands(io, expected=current["commands"])
        io.write("local_resource_roots.json", {"project_id": current["project_id"], "generation": current["generation"],
                  "commands": [], "roots": identities(io)})
        io.write("local_locations.json", {"ids": header["location_ids"], "members": store.location_members})
        source_versions = {source_id: {version: entry["sha256"]
            for version, entry in versions.items()} for source_id, versions in current["sources"].items()}
        import sciplot_core.project_store.commands as commands

        for record in records:
            if record.get("native_workspace") is not None:
                import sciplot_core.project_store.native_work as native_work
                _path, identity = native_work.verify(io, record, relocating=True)
                bindings = io.read("local_native_work.json") or {"bindings": {}}
                bindings["bindings"][digest(record["command_id"])] = identity
                io.write("local_native_work.json", bindings)
        checked = state.checked_head(io)
        assert checked is not None
        for record in records:
            if record.get("draft") is not None:
                commands.public(io, record, checked=checked)
                for source_id, versions in record["draft"].get("sources", {}).items():
                    for version, entry in versions.items():
                        try:
                            io.get(entry)
                        except OSError as exc:
                            raise ProjectConflict("The imported sealed source blob is missing.") from exc
                        source_versions.setdefault(source_id, {})[version] = entry["sha256"]
        imported_roots = io.read("local_resource_roots.json")
        assert imported_roots is not None
        imported_roots["commands"] = [record["command_id"] for record in records]
        io.write("local_resource_roots.json", imported_roots)
        from .prepared_inputs import bind_import

        local_sources: dict[str, Any] = {"versions": source_versions}
        for record in records:
            if record.get("draft") is not None:
                bind_import(io, current, record, local_sources)
        io.write("local_sources.json", local_sources)
        io.write("relocation.json", {"generation": current["generation"], "files": sorted(current["files"]), "complete": False})
        projection.relocate(io, current)
