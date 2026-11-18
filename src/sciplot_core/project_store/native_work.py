"""Finite NativeSuite creation evidence lives below the same command record."""

import os
import stat
from pathlib import Path
from typing import Any

from .errors import ProjectCommandConflict, ProjectConflict, ProjectRecoveryRequired
from .io import STORE, StoreIO, digest, directory, member_names, parts, read_file, sha
import sciplot_core.project_store.state as state

_ADAPTER = "native_suite_create_v1"
MANAGED_GROUP_PREPARE = "managed_attachment_group_prepare_v1"


def _adapter(record: dict[str, Any]) -> str | None:
    metadata = record.get("metadata", {})
    if metadata.get("kind") == "native_create":
        return _ADAPTER
    if metadata.get("kind") == "semantic_record" and metadata.get("request", {}).get("adapter") == MANAGED_GROUP_PREPARE:
        return MANAGED_GROUP_PREPARE
    return None


def resolve(io: StoreIO, value: dict[str, Any], actual: Path, *, expected_sha256: str | None = None,
            source_id: str | None = None) -> Path | None:
    base = io.root / STORE / "native_work"
    origin = Path(value["locators"][""]) / STORE / "native_work"
    if actual.is_relative_to(origin):
        relative = actual.relative_to(origin).parts
    elif actual.is_relative_to(base):
        relative = actual.relative_to(base).parts
    else:
        return None
    if len(relative) < 2 or relative[1] != "candidate" or source_id is not None:
        raise ProjectConflict("A private native candidate cannot assert an unrelated scientific source identity.")
    record = state.read_command(io, "commands/" + relative[0] + ".json")
    if record is None:
        raise ProjectRecoveryRequired("This native candidate has no admitted command owner.")
    workspace, _identity = verify(io, record)
    components = parts("/".join(relative))
    with directory(io.fd, ("native_work", *components[:-1])) as parent:
        info = os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
        if stat.S_ISREG(info.st_mode):
            data, _mode = read_file(parent, components[-1], owned=True)
            version = sha(data)
        elif stat.S_ISDIR(info.st_mode):
            with directory(parent, (components[-1],)) as selected:
                members = {}
                for name in member_names(selected):
                    leaf = parts(name)
                    with directory(selected, leaf[:-1]) as folder:
                        members[name] = sha(read_file(folder, leaf[-1], owned=True)[0])
            version = digest({"kind": "directory", "files": [
                {"path": name, "content_sha256": value} for name, value in sorted(members.items())]})
        else:
            raise ProjectConflict("Private native work cannot reconnect through a symbolic or special entry.")
    if expected_sha256 is not None and version != expected_sha256:
        raise ProjectConflict("The private native candidate differs from its exact observed bytes.")
    verify(io, record)
    return workspace / Path(*relative[2:])


def literal(io: StoreIO, value: dict[str, Any], actual: Path) -> str | None:
    selected = resolve(io, value, actual)
    return str(Path(value["locators"][""]) / selected.relative_to(io.root)) if selected is not None else None


def _binding(record: dict[str, Any], adapter: str) -> dict[str, str]:
    return {"project_id": record["project_id"], "command_id": record["command_id"],
            "command_digest": record["command_digest"], "adapter": adapter}


def verify(io: StoreIO, record: dict[str, Any], *, relocating: bool = False) -> tuple[Path, dict[str, int]]:
    reference = record.get("native_workspace")
    relative = "native_work/" + digest(record["command_id"])
    adapter = _adapter(record)
    if adapter is None or not isinstance(reference, dict) or reference.get("adapter") != adapter or reference.get("relative") != relative:
        raise ProjectRecoveryRequired("The native working root is not bound to this exact command.")
    if io.read(relative + "/binding.json") != _binding(record, adapter):
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
    if adapter != _adapter(record):
        raise ProjectCommandConflict("Only the admitted native preparation adapter owns this working root.")
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
    io.write(relative + "/binding.json", _binding(record, adapter), exclusive=True)
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
