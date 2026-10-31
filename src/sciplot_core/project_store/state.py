"""One immutable complete generation and its single authoritative head."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
from threading import get_ident
from typing import Any, cast
from types import MappingProxyType

from sciplot_core.project_commands.resources import PreparedFile
from uuid import uuid4

from .errors import ProjectConflict, ProjectRecoveryRequired, ProjectStoreError
from .io import StoreIO, digest, parts
from .root_bindings import identities
from .command_records import command_path as command_path, read_command as read_command, read_commands as read_commands


def boundary(_name: str) -> None:
    """Named storage boundaries; fault tests replace this function in owned children."""


def generation(io: StoreIO, identity: str) -> dict[str, Any]:
    if not isinstance(identity, str) or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
        raise ProjectStoreError("Invalid immutable project generation identity.")
    value = io.read(f"generations/{identity}.json")
    if (value is None or value.get("generation") != identity
            or value.get("kind") != "sciplot_project_generation" or value.get("version") != 1):
        io.validation_failed()
        raise ProjectStoreError("The immutable project generation is missing.")
    return value


_CHECKED_HEAD = object()


class CheckedHead:
    """A verified immutable parent chain, private to one live IO validation batch."""
    def __init__(self, io: StoreIO, value: dict[str, Any], generations: dict[str, dict[str, Any]], *,
                 _verification: object | None = None) -> None:
        if _verification is not _CHECKED_HEAD:
            raise ProjectConflict("Only a fully verified head may construct its local history proof.")
        self.current = value
        self._generations = MappingProxyType(generations)
        self._io, self._fd, self._epoch = io, io.fd, io.validation_epoch
        self._lease_epoch = io.lease_epoch
        self._owner, self._root = (os.getpid(), get_ident()), io.root
        self._roots = dict(io.root_fds)
        self._locations, self._members = dict(io.locations), dict(io.location_members)
        self._backups = dict(io.namespace_backups)
        window = cast(_CheckedWindow | None, io._checked_window)
        self._window_anchor = window.anchor if window is not None else None
        self._active = True

    def require_identity(self, io: StoreIO) -> None:
        if self._window_anchor is not None:
            self._window_anchor.require_identity(io)
        if (not self._active or io is not self._io or io.fd != self._fd or io.fd < 0
                or io.lease_epoch != self._lease_epoch
                or self._owner != (os.getpid(), get_ident()) or io.root != self._root
                or io.root_fds != self._roots or io.locations != self._locations
                or io.location_members != self._members or io.namespace_backups != self._backups):
            raise ProjectConflict("A checked history cannot cross its IO, head or mutation boundary.")

    def require(self, io: StoreIO, current: dict[str, Any]) -> None:
        self.require_identity(io)
        if io.validation_epoch != self._epoch or current is not self.current:
            raise ProjectConflict("A checked history cannot cross its IO, head or mutation boundary.")

    def borrow(self, io: StoreIO) -> CheckedHead:
        self.require(io, self.current)
        return CheckedHead(io, self.current, dict(self._generations), _verification=_CHECKED_HEAD)

    def reachable(self, io: StoreIO, current: dict[str, Any], identity: str) -> dict[str, Any]:
        self.require(io, current)
        if identity not in self._generations:
            raise ProjectConflict("The expected generation is not committed project history.")
        return self._generations[identity]

    def close(self) -> None:
        self._active = False


class _CheckedWindow:
    """A finite caller-owned window, never a second durable or public head."""
    def __init__(self, io: StoreIO, checked: CheckedHead) -> None:
        self.anchor = checked.borrow(io)
        self.proof: CheckedHead | None = checked.borrow(io)

    def discard(self) -> None:
        if self.proof is not None:
            self.proof.close()
            self.proof = None

    def borrow(self, io: StoreIO) -> CheckedHead | None:
        self.anchor.require_identity(io)
        io.verify_roots()
        if self.proof is not None and self.proof._epoch != io.validation_epoch:
            self.discard()
        return self.proof.borrow(io) if self.proof is not None else None

    def remember(self, io: StoreIO, checked: CheckedHead) -> None:
        self.anchor.require_identity(io)
        self.discard()
        self.proof = checked.borrow(io)


@contextmanager
def validation_window(io: StoreIO, checked: CheckedHead) -> Iterator[None]:
    existing = cast(_CheckedWindow | None, io._checked_window)
    window = _CheckedWindow(io, checked)
    io._checked_window = window
    try:
        yield
    except BaseException:
        if existing is not None:
            existing.discard()
        raise
    finally:
        window.discard()
        window.anchor.close()
        io._checked_window = existing


def checked_head(io: StoreIO) -> CheckedHead | None:
    window = cast(_CheckedWindow | None, io._checked_window)
    if window is not None:
        borrowed = window.borrow(io)
        if borrowed is not None:
            return borrowed
    try:
        checked = _read_checked_head(io)
    except (OSError, ProjectStoreError):
        io.validation_failed()
        raise
    if window is not None and checked is not None:
        window.remember(io, checked)
    return checked


def _read_checked_head(io: StoreIO) -> CheckedHead | None:
    pointer = io.read("head.json")
    if pointer is None:
        return None
    value = generation(io, pointer["generation"])
    if (pointer.get("kind") != "sciplot_project_head" or pointer.get("version") != 1
            or pointer.get("sha256") != digest(value) or pointer.get("project_id") != value["project_id"]):
        raise ProjectConflict("The project head and complete generation disagree.")
    for name, item in value["files"].items():
        parts(name)
        io.get(item)
    for versions in value.get("sources", {}).values():
        for item in versions.values():
            io.get(item)
    cursor, generations = value, {value["generation"]: value}
    while cursor.get("parent") is not None:
        parent = generation(io, cursor["parent"])
        if (parent["generation"] in generations or cursor.get("parent_sha256") != digest(parent)
                or parent["project_id"] != value["project_id"] or parent["sequence"] != cursor["sequence"] - 1):
            raise ProjectConflict("The immutable complete project history changed or split.")
        generations[parent["generation"]] = parent
        cursor = parent
    return CheckedHead(io, value, generations, _verification=_CHECKED_HEAD)


def head(io: StoreIO) -> dict[str, Any] | None:
    checked = checked_head(io)
    if checked is None:
        return None
    try:
        return deepcopy(checked.current) if io._checked_window is not None else checked.current
    finally:
        checked.close()


def reachable(io: StoreIO, current: dict[str, Any], identity: str, *, checked: CheckedHead | None = None) -> dict[str, Any]:
    if checked is not None:
        return checked.reachable(io, current, identity)
    value = current
    while value["generation"] != identity:
        if value.get("parent") is None:
            raise ProjectConflict("The expected generation is not committed project history.")
        value = generation(io, value["parent"])
    return value


def write_generation(io: StoreIO, value: dict[str, Any]) -> None:
    io.write(f"generations/{value['generation']}.json", value, exclusive=True)


def publish_head(io: StoreIO, value: dict[str, Any]) -> None:
    io.write("head.json", {"kind": "sciplot_project_head", "version": 1,
             "project_id": value["project_id"], "generation": value["generation"],
             "sequence": value["sequence"], "sha256": digest(value)})


def import_legacy(io: StoreIO) -> dict[str, Any]:
    files = io.scan()
    for item in files.values():
        item["file_id"] = uuid4().hex
    project_id = uuid4().hex
    sources: dict[str, dict[str, Any]] = {}
    for name, item in files.items():
        if Path(name).suffix.casefold() in {".csv", ".tsv", ".xlsx", ".xls", ".txt"}:
            components = name.split("/")
            locator = (io.locations[components[0][1:]] / Path(*components[1:])
                       if components[0].startswith("@") else io.root / name)
            sources[item["file_id"]] = {item["sha256"]: {**item, "source_id": item["file_id"],
                "version": item["sha256"], "logical": name, "locator": str(locator)}}
    value = {"kind": "sciplot_project_generation", "version": 1,
        "project_id": project_id, "generation": uuid4().hex, "sequence": 0, "parent": None,
        "files": files, "sources": sources, "commands": {},
        "resource_roots": identities(io),
        "locators": {"": str(io.root), **{key: str(path) for key, path in io.locations.items()}},
        "origin": "explicit_legacy_import"}
    write_generation(io, value)
    boundary("before_head")
    io.verify_roots()
    publish_head(io, value)
    boundary("after_head")
    return value


def command(io: StoreIO, command_id: str, command_digest: str | None = None, *,
            checked: CheckedHead | None = None) -> dict[str, Any] | None:
    from .errors import ProjectCommandConflict

    if checked is not None:
        checked.require(io, checked.current)
    value = read_command(io, command_path(command_id))
    if checked is not None:
        checked.require(io, checked.current)
    if value is None:
        current = checked.current if checked is not None else head(io)
        if current is not None and command_id in current["commands"]:
            raise ProjectRecoveryRequired("A committed command has no exact derived receipt; it is not a new command.")
    if value is not None and (value.get("command_id") != command_id
            or (command_digest is not None and value.get("command_digest") != command_digest)):
        raise ProjectCommandConflict("The command key already binds a different request.")
    return value


def sealed_draft(io: StoreIO, record: dict[str, Any]) -> dict[str, Any]:
    draft = record.get("draft")
    if not isinstance(draft, dict):
        raise ProjectConflict("The command has no exact sealed input candidate.")
    expected = digest({"command_digest": record["command_digest"], "candidate": draft})
    frozen = io.read(f"drafts/{digest(record['command_id'])}/{expected}.json")
    if expected != record.get("decision_id") or frozen != draft:
        raise ProjectConflict("The sealed command candidate changed.")
    return draft


def save_command(io: StoreIO, value: dict[str, Any]) -> None:
    io.write(command_path(value["command_id"]), value)


def import_writes(io: StoreIO, writes: Mapping[str, bytes | Path | PreparedFile | None]) -> dict[str, Any]:
    from .io import parts

    result: dict[str, Any] = {}
    for name, source in sorted(writes.items()):
        parts(name)
        io.split(name)
        if source is None:
            result[name] = None
            continue
        if isinstance(source, bytes):
            data, mode = source, 0o600
        elif isinstance(source, PreparedFile):
            source.__post_init__()
            data, mode = source.data, source.mode
        elif isinstance(source, Path):
            from .io import read_file
            import os

            parent = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                data, mode = read_file(parent, source.name)
            finally:
                os.close(parent)
        else:
            raise ProjectStoreError("Writes must contain bytes, trusted staged Paths, or explicit deletion.")
        if not 0 <= mode <= 0o777:
            raise ProjectStoreError("A staged project output has unsupported special permission bits.")
        result[name] = {**io.put(data), "mode": mode}
    return result
