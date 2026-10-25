"""Exact one-namespace legacy import; no sibling discovery or old writer reuse."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from sciplot_core.project_commands import PreparedFile, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.io import read_file
from sciplot_core.project_store.errors import ProjectRecoveryRequired
from .attachment_index import Attachment, INDEX, OWNER, attachment_id, encode, owned_marker, read_index
from .attachment_projection import derived_relative
from .attachment_sources import prepared_sources, record_sources
from .attachment_fence import prepare_shell, transfer_lease
from .attachment_transfer import resume_transfer
from .errors import EngineError
from .repository import FileProjectRepository


def entry_for(store: FileProjectStore, *, key: str, figure_id: str, origin: Path,
              plot_id: str, managed_output: str | None = None) -> dict[str, Any]:
    snapshot = store.snapshot(import_legacy=True)
    identity = attachment_id(snapshot["project_id"], key)
    return {"id": identity, "namespace": ".sciplot_semantic/" + identity, "figure_id": figure_id,
            "plot_id": plot_id, "origin_root": str(origin), "project_origin": snapshot["locators"][""],
            "resource_roots": deepcopy(snapshot["locators"]), "managed_output": managed_output,
            "archived_derivatives": {}}


def _namespace_bytes(root: Path, *, modes: dict[str, int] | None = None) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise EngineError("semantic_attachment_import_invalid", "Import requires this exact existing semantic namespace.")
    result = {}
    for directory, names, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in names:
            if (parent / name).is_symlink():
                raise EngineError("semantic_attachment_import_invalid", "A semantic namespace cannot contain symbolic directories.")
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for name in sorted(files):
                path = parent / name
                if path == root / OWNER:
                    continue
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise EngineError("semantic_attachment_import_invalid", "A semantic namespace must contain regular files.")
                relative = path.relative_to(root).as_posix()
                data, mode = read_file(descriptor, name)
                result[relative] = data
                if modes is not None:
                    modes[relative] = mode
        finally:
            os.close(descriptor)
    return result


def attach_existing(store: FileProjectStore, root: Path, *, figure_id: str) -> Attachment:
    root = root.expanduser().absolute()
    with transfer_lease(root) as parent:
        return _attach_existing(store, root, figure_id=figure_id, parent=parent)


def _attach_existing(store: FileProjectStore, root: Path, *, figure_id: str, parent: Any) -> Attachment:
    try:
        snapshot = store.snapshot(import_legacy=True)
    except ProjectRecoveryRequired:
        prior = owned_marker(root)
        pending = ProjectCommands(store).query("attach:" + prior[1]["attachment_id"]) if prior is not None else None
        if pending is None:
            raise
        return resume_transfer(store, root, figure_id, pending, parent=parent, namespace_bytes=_namespace_bytes)
    index = read_index(store, snapshot)
    prior = owned_marker(root)
    if prior is not None:
        origin, owner = prior
        if origin != root or owner["project_id"] != snapshot["project_id"]:
            raise EngineError("semantic_attachment_owner_conflict", "This namespace already belongs to another attached project.")
        existing = index["attachments"].get(owner["attachment_id"])
        if existing is not None:
            return Attachment(store, existing)
    identity = attachment_id(snapshot["project_id"], "legacy:" + figure_id)
    commands = ProjectCommands(store)
    pending = commands.query("attach:" + identity)
    if pending is not None and pending["phase"] != "reserved":
        return resume_transfer(store, root, figure_id, pending, parent=parent, namespace_bytes=_namespace_bytes)
    local = FileProjectRepository()
    raw = local._head_envelope(root)  # Original pointer, seals and CAS before any runtime view.
    head = raw["document"]
    for item in index["attachments"].values():
        if item["plot_id"] == head["plot_id"]:
            if item["origin_root"] != str(root):
                raise EngineError("semantic_attachment_duplicate_head", "One plot cannot acquire competing current semantic namespaces.")
            return Attachment(store, item)
    entry = entry_for(store, key="legacy:" + figure_id, figure_id=figure_id, origin=root,
                      plot_id=head["plot_id"], managed_output=raw["binding"].get("output"))
    if prior is not None and prior[1]["attachment_id"] != entry["id"]:
        raise EngineError("semantic_attachment_owner_conflict", "The pending attachment belongs to another stable figure.")
    modes: dict[str, int] = {}
    members = _namespace_bytes(root, modes=modes)
    if json.loads(members["head.json"]) != local.read(root / "head.json"):
        raise EngineError("semantic_attachment_import_changed", "The original head changed during attachment import.")
    writes: dict[str, bytes | PreparedFile] = {}
    for relative, data in members.items():
        if derived_relative(Path(relative)):
            logical = entry["namespace"] + "/archive/" + relative
            entry["archived_derivatives"][relative] = logical
        else:
            logical = entry["namespace"] + "/" + relative
        writes[logical] = PreparedFile(data, modes[relative])
    marker = {"kind": "sciplot_semantic_owner", "version": 1, "origin_root": str(root), "figure_id": figure_id,
              "project": str(store.root), "project_id": snapshot["project_id"], "attachment_id": entry["id"]}
    if pending is not None:
        marker["history_root"] = pending["metadata"]["request"]["history_root"]
    else:
        marker = prepare_shell(root, marker, hashlib.sha256(members["head.json"]).hexdigest())
    entry["history_root"] = marker["history_root"]
    index["attachments"][entry["id"]] = entry
    writes[INDEX] = encode(index)
    new_marker = {**marker, "origin_root": str(store.root / entry["namespace"])}
    writes[entry["namespace"] + "/" + OWNER] = encode(new_marker)
    sources = []
    for relative, data in members.items():
        if relative.startswith("revisions/") and relative.endswith(".json"):
            sources.extend(record_sources(relative, json.loads(data)))
    captured_sources = prepared_sources(store, sources)
    verify_original_bytes(root, members, modes=modes)
    mutation = ProjectMutation(writes, {"attachment_id": entry["id"], "plot_id": entry["plot_id"]},
                               prepared_sources=captured_sources)
    command = ProjectCommand.create("attachment_import", "attach:" + entry["id"], project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={name: snapshot["files"].get(name, {}).get("sha256") for name in writes},
        write_set=sorted(writes), request={"prepared_digest": mutation.prepared_digest, "attachment_id": entry["id"],
            "origin_root": str(root), "history_root": entry["history_root"], "figure_id": figure_id})
    if pending is not None:
        command = ProjectCommand.from_payload(pending["metadata"])
    prepared = commands.stage_prepared(command, mutation)
    return resume_transfer(store, root, figure_id, prepared, parent=parent, namespace_bytes=_namespace_bytes)


def verify_original_bytes(root: Path, expected: dict[str, bytes], *, modes: dict[str, int] | None = None) -> None:
    actual_modes: dict[str, int] = {}
    actual = _namespace_bytes(root, modes=actual_modes)
    if set(actual) != set(expected) or any(hashlib.sha256(actual[name]).digest() != hashlib.sha256(data).digest()
                                          for name, data in expected.items()) or modes is not None and actual_modes != modes:
        raise EngineError("semantic_attachment_import_changed", "The frozen old semantic namespace changed before publication.")
