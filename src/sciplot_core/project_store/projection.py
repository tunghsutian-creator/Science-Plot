"""Recoverable derived views; immutable generations alone own project state."""

from __future__ import annotations

import os
import stat
from typing import Any

from .errors import ProjectConflict, ProjectRecoveryRequired
from .io import StoreIO, directory, install, sha
from .root_bindings import require as require_roots
from .namespace_transfers import root_exemptions, verify_committed
from .committed_outcomes import descendant_writes, require as committed_outcome
import sciplot_core.project_store.state as state


def _directory_identity(fd: int) -> tuple[int, int, int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid


def _retired_source_directories(io: StoreIO, before: dict[str, Any], current: dict[str, Any],
                                names: set[str]) -> list[tuple[str, tuple[int, int, int, int] | None]]:
    """Retire direct leaf-only source parents, never unknown intermediate scaffolds."""
    removed = {name for name in names if name in before["files"] and name not in current["files"]}
    if not removed:
        return []
    protected = set(before.get("input_resources", [])) | set(current.get("input_resources", []))
    protected.update(before.get("history_resources", []))
    protected.update(current.get("history_resources", []))
    produced = set()
    for versions in before.get("sources", {}).values():
        for source in versions.values():
            name = source.get("produced_resource")
            previous = before["files"].get(name)
            if (name in removed and name not in protected
                    and previous is not None and all(source.get(key) == previous[key] for key in ("sha256", "size", "mode"))):
                io.get(source)
                produced.add(name)
    parents = {name.rsplit("/", 1)[0]: name for name in produced if "/" in name}
    result: list[tuple[str, tuple[int, int, int, int] | None]] = []
    for parent, representative in sorted(parents.items(), key=lambda item: item[0].count("/"), reverse=True):
        prefix = parent + "/"
        old = {name for name in before["files"] if name.startswith(prefix)}
        if (not old or not old.issubset(produced) or any("/" in name[len(prefix):] for name in old)
                or any(name.startswith(prefix) for name in current["files"])):
            continue
        root, components = io.split(representative)
        key = representative.split("/", 1)[0][1:] if representative.startswith("@") else ""
        if len(components) < 2 or key and io.location_members.get(key) is not None:
            continue  # A project/capability root is never a retired scaffold.
        allowed = {name[len(prefix):].split("/", 1)[0] for name in old}
        try:
            with directory(root, components[:-1]) as fd:
                if not set(os.listdir(fd)).issubset(allowed):
                    raise ProjectRecoveryRequired("Outside members prevent retiring a produced source directory.")
                result.append((representative, _directory_identity(fd)))
        except FileNotFoundError:
            result.append((representative, None))
        except OSError as exc:
            raise ProjectRecoveryRequired("A produced source directory changed its physical identity.") from exc
    return result


def _retire_source_directories(io: StoreIO, retired: list[tuple[str, tuple[int, int, int, int] | None]],
                               current: dict[str, Any], checked: state.CheckedHead) -> None:
    for representative, expected in retired:
        state.boundary("before_directory_projection")
        checked.require(io, current)
        io.verify_roots()
        root, components = io.split(representative)
        try:
            with directory(root, components[:-2]) as parent:
                try:
                    info = os.stat(components[-2], dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                identity = info.st_dev, info.st_ino, info.st_mode, info.st_uid
                if expected is None or identity != expected or not stat.S_ISDIR(info.st_mode):
                    raise ProjectRecoveryRequired("A retired source directory was replaced during materialization.")
                with directory(parent, (components[-2],)) as fd:
                    if _directory_identity(fd) != expected or os.listdir(fd):
                        raise ProjectRecoveryRequired("Outside members prevent retiring a produced source directory.")
                    latest = os.stat(components[-2], dir_fd=parent, follow_symlinks=False)
                    if (latest.st_dev, latest.st_ino, latest.st_mode, latest.st_uid) != expected:
                        raise ProjectRecoveryRequired("A retired source directory changed before removal.")
                    os.rmdir(components[-2], dir_fd=parent)
                    os.fsync(parent)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ProjectRecoveryRequired("A produced source directory could not be retired safely.") from exc
        state.boundary("after_directory_projection")


def pending(io: StoreIO, current: dict[str, Any]) -> bool:
    relocation = io.read("relocation.json")
    if relocation is not None and relocation.get("complete") is not True:
        return True
    for record in state.read_commands(io, expected=current["commands"]):
        if record.get("install_generation") is not None and record.get("phase") != "complete":
            if record["command_id"] in current["commands"]:
                return True
    return False


def project(io: StoreIO, record: dict[str, Any], current: dict[str, Any]) -> None:
    """Finish only old-or-exact-new projections; never overwrite foreign bytes."""
    if record.get("phase") == "complete":
        raise ProjectRecoveryRequired("A completed receipt cannot reacquire active installation rights.")
    checked = state.checked_head(io)
    if checked is None or checked.current != current:
        raise ProjectRecoveryRequired("The publication head changed before its projection admission.")
    current = checked.current
    committed = committed_outcome(io, current, record, checked=checked)
    if committed is None:
        raise ProjectRecoveryRequired("An unpublished candidate cannot materialize active project bytes.")
    require_roots(io, current, record)
    verify_committed(io, current, record)
    old, names = committed.parent, committed.files
    rewritten = descendant_writes(io, current, committed.generation, checked=checked)
    retired = _retired_source_directories(io, old, current, set(names))
    # Validate the entire installation before the first replacement.
    for name in names:
        before, own, after = old["files"].get(name), committed.generation["files"].get(name), current["files"].get(name)
        physical = io.physical(name)
        actual = (sha(physical[0]), physical[1]) if physical else None
        preimages = (after,) if name in rewritten else (before, own, after)
        allowed = {(entry["sha256"], entry["mode"]) if entry else None for entry in preimages}
        if actual not in allowed:
            raise ProjectRecoveryRequired(f"Outside bytes prevent generation recovery: {name}")
    for name in names:
        after = current["files"].get(name)
        physical = io.physical(name)
        if ((sha(physical[0]), physical[1]) if physical else None) == ((after["sha256"], after["mode"]) if after else None):
            continue
        state.boundary("before_projection")
        checked.require(io, current)
        io.verify_roots()
        fd, components = io.split(name)
        with directory(fd, components[:-1], create=after is not None) as parent:
            # Check again at this physical boundary, after staging predecessor IO.
            current_physical = io.physical(name)
            actual = (sha(current_physical[0]), current_physical[1]) if current_physical else None
            before = old["files"].get(name)
            own = committed.generation["files"].get(name)
            preimages = (after,) if name in rewritten else (before, own, after)
            if actual not in {(entry["sha256"], entry["mode"]) if entry else None for entry in preimages}:
                raise ProjectConflict("A derived view changed during generation materialization.")
            if after is None:
                os.unlink(components[-1], dir_fd=parent)
                os.fsync(parent)
            else:
                install(parent, components[-1], io.get(after), mode=after["mode"])
        state.boundary("after_projection")
    checked.require(io, current)
    _retire_source_directories(io, retired, current, checked)


def recover(io: StoreIO, current: dict[str, Any], *, checked: state.CheckedHead | None = None) -> list[str]:
    if checked is None:
        checked = state.checked_head(io)
        if checked is None or checked.current != current:
            raise ProjectRecoveryRequired("Recovery must bind its exact checked head.")
        current = checked.current
    checked.require(io, current)
    pending_records = []
    for record in state.read_commands(io, expected=current["commands"]):
        committed = committed_outcome(io, current, record, checked=checked)
        if committed is not None and record.get("phase") != "complete":
            pending_records.append((record, committed))
    # Validate every derived record before relocation or any active replacement.
    require_roots(io, current, exemptions=root_exemptions(io, current))
    relocate(io, current)
    recovered: list[str] = []
    for record, committed in pending_records:
        project(io, record, current)
        record.update(phase="complete", generation=committed.generation["generation"], result=committed.outcome["result"])
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
