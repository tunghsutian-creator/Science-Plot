"""One physical command identity for direct reads and every directory scan."""

from collections.abc import Iterable
import os
from typing import Any

from .errors import ProjectCommandConflict, ProjectRecoveryRequired, ProjectStoreError
from .io import StoreIO, digest, directory


def command_path(command_id: str) -> str:
    if not isinstance(command_id, str) or not command_id or len(command_id) > 4096:
        raise ProjectStoreError("A bounded command identity is required.")
    return f"commands/{digest(command_id)}.json"


def read_command(io: StoreIO, path: str) -> dict[str, Any] | None:
    record = io.read(path)
    if record is None:
        return None
    command_id = record.get("command_id")
    if not isinstance(command_id, str) or command_path(command_id) != path:
        raise ProjectCommandConflict("A command receipt's file and stable key disagree.")
    return record


def read_commands(io: StoreIO, *, expected: Iterable[str] = ()) -> tuple[dict[str, Any], ...]:
    """Reconcile the one command directory against authoritative committed keys."""
    try:
        with directory(io.fd, ("commands",)) as parent:
            names = sorted(name for name in os.listdir(parent) if name.endswith(".json"))
    except FileNotFoundError:
        names = []
    records = []
    for name in names:
        record = read_command(io, "commands/" + name)
        if record is None:
            raise ProjectRecoveryRequired("A command receipt disappeared during its owned directory read.")
        records.append(record)
    if set(expected) - {record["command_id"] for record in records}:
        raise ProjectRecoveryRequired("A committed command has no exact derived receipt; inspect it before recovery.")
    return tuple(records)
