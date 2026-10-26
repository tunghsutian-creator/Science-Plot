"""Persist physical resource identities across command retries and explicit moves."""

import os
from collections.abc import Iterable
from typing import Any

from .errors import ProjectConflict, ProjectRecoveryRequired
from .io import StoreIO
from .command_records import read_commands


def identities(io: StoreIO) -> dict[str, dict[str, int]]:
    return {key: {"device": os.fstat(fd).st_dev, "inode": os.fstat(fd).st_ino}
            for key, fd in io.root_fds.items()}


def expected(io: StoreIO, current: dict[str, Any], values: dict[str, Any], *, command_id: str | None = None) -> dict[str, Any]:
    local = io.read("local_resource_roots.json")
    result = dict(values)
    if local is not None:
        if local.get("project_id") != current["project_id"]:
            raise ProjectConflict("The local root bindings belong to another stable project.")
        applies = (command_id in local.get("commands", []) if command_id is not None
                   else current["generation"] == local.get("generation", current["generation"]))
        if applies:
            for key in values:
                if key in local["roots"]:
                    result[key] = local["roots"][key]
    return result


def require(io: StoreIO, current: dict[str, Any], record: dict[str, Any] | None = None,
            *, exemptions: Iterable[str] = ()) -> None:
    actual = identities(io)
    checks = [expected(io, current, current.get("resource_roots", {}))]
    if record is not None and record["command_id"] not in current["commands"]:
        checks.append(expected(io, current, record.get("resource_roots", {}), command_id=record["command_id"]))
    for values in checks:
        for key, original in values.items():
            if key in exemptions:
                continue
            if key not in actual or actual[key] != original:
                raise ProjectRecoveryRequired("A declared resource root changed ownership identity; explicit recovery is required.")
    io.verify_roots()


def scope_local_import(io: StoreIO, current: dict[str, Any]) -> None:
    local = io.read("local_resource_roots.json")
    if local is not None and "generation" not in local:
        names = [record["command_id"] for record in read_commands(io, expected=current["commands"])]
        io.write("local_resource_roots.json", {**local, "generation": current["generation"], "commands": names})
