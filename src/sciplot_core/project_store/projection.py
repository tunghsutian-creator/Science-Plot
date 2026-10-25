"""Recoverable derived views; immutable generations alone own project state."""

from __future__ import annotations

import os
from typing import Any

from .errors import ProjectConflict, ProjectRecoveryRequired
from .io import StoreIO, directory, install, sha
from .root_bindings import require as require_roots
from .namespace_transfers import root_exemptions, verify_committed
import sciplot_core.project_store.state as state


def pending(io: StoreIO, current: dict[str, Any]) -> bool:
    relocation = io.read("relocation.json")
    if relocation is not None and relocation.get("complete") is not True:
        return True
    try:
        with directory(io.fd, ("commands",)) as parent:
            names = sorted(name for name in os.listdir(parent) if name.endswith(".json"))
    except FileNotFoundError:
        return False
    for name in names:
        record = io.read("commands/" + name)
        if record and record.get("install_generation") is not None and record.get("phase") != "complete":
            if record["command_id"] in current["commands"]:
                return True
    return False


def project(io: StoreIO, record: dict[str, Any], current: dict[str, Any]) -> None:
    """Finish only old-or-exact-new projections; never overwrite foreign bytes."""
    require_roots(io, current, record)
    verify_committed(io, current, record)
    old = state.generation(io, record["install_parent"])
    names = record["install_files"]
    # Validate the entire installation before the first replacement.
    for name in names:
        before, after = old["files"].get(name), current["files"].get(name)
        physical = io.physical(name)
        actual = (sha(physical[0]), physical[1]) if physical else None
        allowed = {(entry["sha256"], entry["mode"]) if entry else None for entry in (before, after)}
        if actual not in allowed:
            raise ProjectRecoveryRequired(f"Outside bytes prevent generation recovery: {name}")
    for name in names:
        after = current["files"].get(name)
        physical = io.physical(name)
        if ((sha(physical[0]), physical[1]) if physical else None) == ((after["sha256"], after["mode"]) if after else None):
            continue
        state.boundary("before_projection")
        io.verify_roots()
        fd, components = io.split(name)
        with directory(fd, components[:-1], create=after is not None) as parent:
            # Check again at this physical boundary, after staging predecessor IO.
            current_physical = io.physical(name)
            actual = (sha(current_physical[0]), current_physical[1]) if current_physical else None
            before = old["files"].get(name)
            if actual not in {(entry["sha256"], entry["mode"]) if entry else None for entry in (before, after)}:
                raise ProjectConflict("A derived view changed during generation materialization.")
            if after is None:
                os.unlink(components[-1], dir_fd=parent)
                os.fsync(parent)
            else:
                install(parent, components[-1], io.get(after), mode=after["mode"])
        state.boundary("after_projection")


def recover(io: StoreIO, current: dict[str, Any]) -> list[str]:
    require_roots(io, current, exemptions=root_exemptions(io, current))
    relocate(io, current)
    recovered: list[str] = []
    try:
        with directory(io.fd, ("commands",)) as parent:
            names = sorted(name for name in os.listdir(parent) if name.endswith(".json"))
    except FileNotFoundError:
        return recovered
    for name in names:
        record = io.read("commands/" + name)
        assert record is not None
        if record.get("install_generation") is None or record.get("phase") == "complete":
            continue
        installed = record["install_generation"]
        if installed in current.get("commands", {}):
            # This field is not an authoritative pointer; the head command map is.
            raise ProjectRecoveryRequired("An invalid generation installation record was found.")
        outcome = current["commands"].get(record["command_id"])
        if outcome is None:
            # Candidate was frozen but never published; no active bytes were touched.
            continue
        if outcome["command_digest"] != record["command_digest"]:
            raise ProjectRecoveryRequired("Command and immutable generation evidence disagree.")
        published = state.generation(io, installed)
        project(io, record, published)
        record.update(phase="complete", generation=installed, result=outcome["result"])
        state.save_command(io, record)
        recovered.append(record["command_id"])
    return recovered


def relocate(io: StoreIO, current: dict[str, Any]) -> None:
    plan = io.read("relocation.json")
    if plan is None or plan.get("complete") is True:
        return
    if plan.get("generation") != current["generation"] or set(plan["files"]) != set(current["files"]):
        raise ProjectRecoveryRequired("The cold relocation plan no longer matches the complete generation.")
    for name in plan["files"]:
        physical = io.physical(name)
        if physical is not None and (sha(physical[0]), physical[1]) != (current["files"][name]["sha256"], current["files"][name]["mode"]):
            raise ProjectRecoveryRequired("Cold relocation found conflicting outside bytes.")
    for name in plan["files"]:
        if io.physical(name) is not None:
            continue
        entry = current["files"][name]
        fd, components = io.split(name)
        with directory(fd, components[:-1], create=True) as parent:
            install(parent, components[-1], io.get(entry), mode=entry["mode"], exclusive=True)
    io.write("relocation.json", {**plan, "complete": True})
