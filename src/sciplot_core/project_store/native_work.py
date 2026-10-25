"""Finite NativeSuite creation evidence lives below the same command record."""

import os
from pathlib import Path
from typing import Any

from .errors import ProjectCommandConflict, ProjectRecoveryRequired
from .io import StoreIO, digest, directory
import sciplot_core.project_store.state as state

_ADAPTER = "native_suite_create_v1"


def _binding(record: dict[str, Any]) -> dict[str, str]:
    return {"project_id": record["project_id"], "command_id": record["command_id"],
            "command_digest": record["command_digest"], "adapter": _ADAPTER}


def verify(io: StoreIO, record: dict[str, Any], *, relocating: bool = False) -> tuple[Path, dict[str, int]]:
    reference = record.get("native_workspace")
    relative = "native_work/" + digest(record["command_id"])
    if not isinstance(reference, dict) or reference.get("adapter") != _ADAPTER or reference.get("relative") != relative:
        raise ProjectRecoveryRequired("The native working root is not bound to this exact command.")
    if io.read(relative + "/binding.json") != _binding(record):
        raise ProjectRecoveryRequired("The native working root lost its exact owner binding.")
    with directory(io.fd, (*relative.split("/"), "candidate")) as fd:
        info = os.fstat(fd)
    identity = {"device": info.st_dev, "inode": info.st_ino}
    local = io.read("local_native_work.json") or {"bindings": {}}
    expected = local["bindings"].get(digest(record["command_id"]), reference)
    if not relocating and any(identity[name] != expected.get(name) for name in identity):
        raise ProjectRecoveryRequired("The native working root changed its owned directory identity.")
    return io.root / ".sciplot_store" / relative / "candidate", identity


def claim(io: StoreIO, record: dict[str, Any], adapter: str) -> Path:
    if adapter != _ADAPTER or record.get("metadata", {}).get("kind") != "native_create":
        raise ProjectCommandConflict("Only the fixed NativeSuite creation adapter owns native working roots.")
    if record.get("native_workspace") is not None:
        return verify(io, record)[0]
    if record["phase"] not in {"reserved", "applying"}:
        raise ProjectCommandConflict("A completed or decided command cannot claim new native execution state.")
    relative = "native_work/" + digest(record["command_id"])
    with directory(io.fd, tuple(relative.split("/")), create=True) as parent:
        try:
            os.mkdir("candidate", mode=0o700, dir_fd=parent)
        except FileExistsError as exc:
            raise ProjectRecoveryRequired("An unbound native working root needs explicit inspection.") from exc
        os.fsync(parent)
    io.write(relative + "/binding.json", _binding(record), exclusive=True)
    with directory(io.fd, (*relative.split("/"), "candidate")) as fd:
        info = os.fstat(fd)
        record["native_workspace"] = {"adapter": adapter, "relative": relative,
                                     "device": info.st_dev, "inode": info.st_ino}
    state.save_command(io, record)
    return verify(io, record)[0]


def append_failure(io: StoreIO, record: dict[str, Any], *, original_error: str,
                   renderer_dispatch_entered: bool, owned_invocation_closed: bool) -> dict[str, Any]:
    verify(io, record)
    if (not isinstance(original_error, str) or not original_error or len(original_error) > 16384
            or type(renderer_dispatch_entered) is not bool or type(owned_invocation_closed) is not bool):
        raise ValueError("Native failure evidence requires the exact bounded error and explicit invocation facts.")
    if record["phase"] != "applying":
        raise ProjectCommandConflict("Failure evidence cannot replace a completed or decided command outcome.")
    fact = {"original_error": original_error, "renderer_dispatch_entered": renderer_dispatch_entered,
            "owned_invocation_closed": owned_invocation_closed}
    facts = record.setdefault("native_failures", [])
    if fact not in facts:
        facts.append(fact)
        state.save_command(io, record)
    return record
