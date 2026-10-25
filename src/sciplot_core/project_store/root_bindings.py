"""Persist physical resource identities across command retries and explicit moves."""

import os
from collections.abc import Iterable
from typing import Any

from .errors import ProjectConflict, ProjectRecoveryRequired
from .io import StoreIO


def identities(io: StoreIO) -> dict[str, dict[str, int]]:
    return {key: {"device": os.fstat(fd).st_dev, "inode": os.fstat(fd).st_ino}
            for key, fd in io.root_fds.items()}


def expected(io: StoreIO, current: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    local = io.read("local_resource_roots.json")
    result = dict(values)
    if local is not None:
        if local.get("project_id") != current["project_id"]:
            raise ProjectConflict("The local root bindings belong to another stable project.")
        for key in values:
            if key in local["roots"]:
                result[key] = local["roots"][key]
    return result


def require(io: StoreIO, current: dict[str, Any], record: dict[str, Any] | None = None,
            *, exemptions: Iterable[str] = ()) -> None:
    actual = identities(io)
    values = dict(current.get("resource_roots", {}))
    if record is not None:
        values.update(record.get("resource_roots", {}))
    for key, original in expected(io, current, values).items():
        if key in exemptions:
            continue
        if key not in actual or actual[key] != original:
            raise ProjectRecoveryRequired("A declared resource root changed ownership identity; explicit recovery is required.")
    io.verify_roots()


def rebind_local(io: StoreIO, current: dict[str, Any]) -> None:
    if io.read("local_resource_roots.json") is not None:
        io.write("local_resource_roots.json", {"project_id": current["project_id"], "roots": identities(io)})
