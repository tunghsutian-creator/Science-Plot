"""One immutable complete generation and its single authoritative head."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sciplot_core.project_commands.resources import PreparedFile
from uuid import uuid4

from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO, digest, parts
from .root_bindings import identities


def boundary(_name: str) -> None:
    """Named storage boundaries; fault tests replace this function in owned children."""


def generation(io: StoreIO, identity: str) -> dict[str, Any]:
    if not isinstance(identity, str) or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
        raise ProjectStoreError("Invalid immutable project generation identity.")
    value = io.read(f"generations/{identity}.json")
    if (value is None or value.get("generation") != identity
            or value.get("kind") != "sciplot_project_generation" or value.get("version") != 1):
        raise ProjectStoreError("The immutable project generation is missing.")
    return value


def head(io: StoreIO) -> dict[str, Any] | None:
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
    cursor, seen = value, {value["generation"]}
    while cursor.get("parent") is not None:
        parent = generation(io, cursor["parent"])
        if (parent["generation"] in seen or cursor.get("parent_sha256") != digest(parent)
                or parent["project_id"] != value["project_id"] or parent["sequence"] != cursor["sequence"] - 1):
            raise ProjectConflict("The immutable complete project history changed or split.")
        seen.add(parent["generation"])
        cursor = parent
    return value


def reachable(io: StoreIO, current: dict[str, Any], identity: str) -> dict[str, Any]:
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


def command_path(command_id: str) -> str:
    if not isinstance(command_id, str) or not command_id or len(command_id) > 4096:
        raise ProjectStoreError("A bounded command identity is required.")
    return f"commands/{digest(command_id)}.json"


def command(io: StoreIO, command_id: str, command_digest: str | None = None) -> dict[str, Any] | None:
    from .errors import ProjectCommandConflict

    value = io.read(command_path(command_id))
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
