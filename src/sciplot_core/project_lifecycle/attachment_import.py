"""Exact one-namespace legacy import; no sibling discovery or old writer reuse."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from sciplot_core.project_commands import PreparedFile, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.errors import ProjectRecoveryRequired
from .attachment_index import Attachment, INDEX, OWNER, attachment_id, encode, owned_marker, read_index
from .attachment_projection import derived_relative
from .attachment_sources import prepared_sources, record_sources
from .attachment_fence import prepare_shell, transfer_lease
from .attachment_transfer import resume_transfer
from .errors import EngineError
from .namespace_capture import namespace_bytes as _namespace_bytes
from .frozen_namespace import FrozenNamespaceRepository
from .legacy_namespace import capture, LegacyNamespace
from .attachment_retirement import retire_artifacts, retire_namespace
from .attachment_store import with_backup


def entry_for(store: FileProjectStore, *, key: str, figure_id: str, origin: Path,
              plot_id: str, managed_output: str | None = None) -> dict[str, Any]:
    snapshot = store.snapshot(import_legacy=True)
    identity = attachment_id(snapshot["project_id"], key)
    return {"id": identity, "namespace": ".sciplot_semantic/" + identity, "figure_id": figure_id,
            "plot_id": plot_id, "origin_root": str(origin), "project_origin": snapshot["locators"][""],
            "namespace_origin": str(store.root / ".sciplot_semantic" / identity),
            "resource_roots": deepcopy(snapshot["locators"]), "managed_output": managed_output,
            "archived_derivatives": {}}


def attach_existing(store: FileProjectStore, root: Path, *, figure_id: str | None, validate: Any) -> Attachment:
    from .store_composition import project_identity, tracked_namespace_store

    tracked = tracked_namespace_store(root)
    if tracked is not None and project_identity(tracked[0]) != project_identity(store):
        raise EngineError("semantic_attachment_project_conflict", "This exact legacy namespace is already tracked by another project generation.")
    observed = capture(store, root.expanduser().absolute())
    with transfer_lease(observed.physical) as parent:
        observed = capture(store, observed.origin)
        return _attach_existing(store, observed, figure_id=figure_id, parent=parent, validate=validate)


def _attach_existing(store: FileProjectStore, observed: LegacyNamespace, *, figure_id: str | None,
                     parent: Any, validate: Any) -> Attachment:
    root = observed.physical
    prior = owned_marker(root)
    if figure_id is None and prior is not None:
        figure_id = prior[1].get("figure_id")
    try:
        snapshot = store.snapshot(import_legacy=True)
    except ProjectRecoveryRequired:
        prior = owned_marker(root)
        pending = ProjectCommands(store).query("attach:" + prior[1]["attachment_id"]) if prior is not None else None
        if pending is None:
            raise
        if figure_id is None:
            figure_id = pending["metadata"]["request"].get("figure_id")
        if not isinstance(figure_id, str):
            raise EngineError("semantic_attachment_owner_conflict", "The pending transfer has no exact original figure identity.") from None
        return resume_transfer(store, root, figure_id, pending, parent=parent, namespace_bytes=_namespace_bytes)
    index = read_index(store, snapshot)
    if prior is not None:
        origin, owner = prior
        if origin != root or owner["project_id"] != snapshot["project_id"]:
            raise EngineError("semantic_attachment_owner_conflict", "This namespace already belongs to another attached project.")
        existing = index["attachments"].get(owner["attachment_id"])
        if existing is not None:
            if (existing.get("transfer_root", existing["origin_root"]) != str(root) or owner["origin_root"] != str(root)
                    or figure_id not in {existing["figure_id"], existing["plot_id"]}):
                raise EngineError("semantic_attachment_owner_conflict", "A supplied ownership pointer cannot adopt another namespace or figure.")
            return Attachment(store, existing)
    modes, members = observed.modes, observed.members
    local = FrozenNamespaceRepository(observed.origin, root, members)
    raw = local._head_envelope(observed.origin) if figure_id is None else None
    if figure_id is None:
        assert raw is not None
        figure_id = raw["binding"].get("figure_id", raw["document"]["plot_id"])
    identity = attachment_id(snapshot["project_id"], "legacy:" + figure_id)
    commands = ProjectCommands(store)
    pending = commands.query("attach:" + identity)
    if pending is not None and pending["phase"] != "reserved":
        return resume_transfer(store, root, figure_id, pending, parent=parent, namespace_bytes=_namespace_bytes)
    raw = raw or local._head_envelope(observed.origin)  # Raw seal before any runtime view.
    head = raw["document"]
    for item in index["attachments"].values():
        if item["plot_id"] == head["plot_id"]:
            if item["origin_root"] != str(observed.origin):
                raise EngineError("semantic_attachment_duplicate_head", "One plot cannot acquire competing current semantic namespaces.")
            return Attachment(store, item)
    entry = entry_for(store, key="legacy:" + figure_id, figure_id=figure_id, origin=observed.origin,
                      plot_id=head["plot_id"], managed_output=raw["binding"].get("output"))
    entry.update(transfer_root=str(root), legacy_prefix=observed.prefix, transfer_directory=observed.directory)
    entry["original_members"] = sorted(members)
    if prior is not None and prior[1]["attachment_id"] != entry["id"]:
        raise EngineError("semantic_attachment_owner_conflict", "The pending attachment belongs to another stable figure.")
    if json.loads(members["head.json"]) != local.read(observed.origin / "head.json"):
        raise EngineError("semantic_attachment_import_changed", "The original head changed during attachment import.")
    artifacts = validate(local, raw, Attachment(store, entry))
    entry["archived_artifacts"] = {}
    entry["artifact_root"] = str(artifacts.root) if artifacts.root is not None else None
    if entry["managed_output"] is not None:
        entry["output_owner"] = "derived"
    writes: dict[str, bytes | PreparedFile | None] = {}
    for relative, data in members.items():
        if derived_relative(Path(relative)):
            logical = entry["namespace"] + "/archive/" + relative
            entry["archived_derivatives"][relative] = logical
        else:
            logical = entry["namespace"] + "/" + relative
        writes[logical] = PreparedFile(data, modes[relative])
    for relative, data in artifacts.members.items():
        logical = entry["namespace"] + "/archive/managed-output/" + relative
        entry["archived_artifacts"][relative] = logical
        writes[logical] = PreparedFile(data, artifacts.modes[relative])
    marker = {"kind": "sciplot_semantic_owner", "version": 1, "origin_root": str(root), "figure_id": figure_id,
              "project": str(store.root), "project_id": snapshot["project_id"], "attachment_id": entry["id"]}
    if pending is not None:
        marker["history_root"] = pending["metadata"]["request"]["history_root"]
    else:
        marker = prepare_shell(root, marker, hashlib.sha256(members["head.json"]).hexdigest())
    entry["history_root"] = marker["history_root"]
    transfers, memberships = retire_namespace(store, observed, marker, entry, snapshot, writes)
    retire_artifacts(store, artifacts, snapshot, writes)
    if transfers:
        store = with_backup(store, entry["id"], Path(marker["history_root"]))
        commands = ProjectCommands(store)
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
            "origin_root": str(root), "history_root": entry["history_root"], "figure_id": figure_id,
            "project_path": str(store.root), "scientific_origin": str(observed.origin)},
        read_memberships=memberships, namespace_transfers=transfers)
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
