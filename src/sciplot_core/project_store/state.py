"""One immutable complete generation and its single authoritative head."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO, digest


def boundary(_name: str) -> None:
    """Named storage boundaries; fault tests replace this function in owned children."""


def generation(io: StoreIO, identity: str) -> dict[str, Any]:
    if not isinstance(identity, str) or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
        raise ProjectStoreError("Invalid immutable project generation identity.")
    value = io.read(f"generations/{identity}.json")
    if value is None or value.get("generation") != identity:
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
    for item in value["files"].values():
        io.get(item)
    for versions in value.get("sources", {}).values():
        for item in versions.values():
            io.get(item)
    return value


def write_generation(io: StoreIO, value: dict[str, Any]) -> None:
    io.write(f"generations/{value['generation']}.json", value, exclusive=True)


def publish_head(io: StoreIO, value: dict[str, Any]) -> None:
    boundary("before_head")
    io.verify_roots()
    io.write("head.json", {"kind": "sciplot_project_head", "version": 1,
             "project_id": value["project_id"], "generation": value["generation"],
             "sequence": value["sequence"], "sha256": digest(value)})
    boundary("after_head")


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
        "locators": {"": str(io.root), **{key: str(path) for key, path in io.locations.items()}},
        "origin": "explicit_legacy_import"}
    write_generation(io, value)
    publish_head(io, value)
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


def save_command(io: StoreIO, value: dict[str, Any]) -> None:
    io.write(command_path(value["command_id"]), value)


def require_reads(io: StoreIO, current: Mapping[str, Any], record: Mapping[str, Any]) -> None:
    from .errors import ProjectRecoveryRequired

    baseline = generation(io, record["expected_generation"])
    if baseline["project_id"] != current["project_id"]:
        raise ProjectConflict("The expected generation belongs to another project.")
    for name, expected in record["read_set"].items():
        old = baseline["files"].get(name)
        latest = current["files"].get(name)
        if expected != (old["sha256"] if old else None) or expected != (latest["sha256"] if latest else None):
            raise ProjectConflict(f"A declared project read changed: {name}")
        physical = io.physical(name)
        actual = io.put(physical[0])["sha256"] if physical else None
        if actual != expected:
            raise ProjectConflict(f"Outside bytes changed a declared project read: {name}")
    projected = record.get("projected_reads", [])
    if projected:
        from sciplot_core.project_commands.read_projections import projection_digest

        for item in projected:
            name = item["resource"]
            before = baseline["files"].get(name)
            after = current["files"].get(name)
            if before is None or after is None:
                raise ProjectConflict("A projected read resource is missing.")
            physical = io.physical(name)
            if physical is None or io.put(physical[0])["sha256"] != after["sha256"]:
                raise ProjectRecoveryRequired("A projected resource has unregistered outside bytes.")
            for entry in (before, after):
                if projection_digest(io.get(entry), kind=item["kind"], key=item["key"]) != item["sha256"]:
                    raise ProjectConflict("The selected project membership or source projection changed.")


def import_writes(io: StoreIO, writes: Mapping[str, bytes | Path | None]) -> dict[str, Any]:
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
        result[name] = {**io.put(data), "mode": mode}
    return result
