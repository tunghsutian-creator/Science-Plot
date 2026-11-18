"""Publish a complete set of prepared Managed attachments in one generation.

Native work and science run before this storage-only owner. Recovery resumes
an already accepted exact command, without rerunning that work.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from sciplot_core.project_commands import PreparedMutation, ProjectCommand, ProjectCommands, SourceTreeRead
from sciplot_core.project_store import FileProjectStore

from .attachment_index import Attachment, INDEX, OWNER, encode, owner_marker, read_index, register_entry
from .attachment_sources import prepared_sources, record_sources
from .errors import EngineError


@dataclass(frozen=True)
class PreparedFigure:
    attachment: Attachment
    members: dict[str, bytes | None]
    assets: dict[str, bytes]


def publish_attachment_group(store: FileProjectStore, snapshot: dict[str, Any], *, key: str,
                             selected_figures: tuple[str, ...], figures: tuple[PreparedFigure, ...],
                             required_outputs: tuple[str, ...], outputs: dict[str, bytes],
                             source_tree: SourceTreeRead) -> dict[str, Any]:
    """Publish members, native outputs, and group results without a callback."""
    if (not figures or len(set(selected_figures)) != len(selected_figures)
            or tuple(figure.attachment.entry["figure_id"] for figure in figures) != selected_figures):
        raise EngineError("semantic_attachment_group_incomplete", "Prepare every selected figure once, in the selected order.")
    index = read_index(store, snapshot)
    writes: dict[str, bytes | None] = {}
    sources = []
    for figure in figures:
        attachment = figure.attachment
        entry = attachment.entry
        prefix = entry["namespace"] + "/"
        if (attachment.store.root != store.root or entry["id"] in index["attachments"]
                or prefix + "head.json" not in figure.members
                or not all(name.startswith(prefix) and isinstance(data, bytes) for name, data in figure.members.items())):
            raise EngineError("semantic_attachment_group_member_invalid", "A group member must prepare a new canonical head in this project.")
        register_entry(index, attachment)
        member = {**figure.members, prefix + OWNER: owner_marker(attachment, snapshot["project_id"])}
        for name, data in figure.members.items():
            if data is not None and ("/revisions/" in name or "/models/" in name):
                sources.extend(record_sources(name, json.loads(data)))
        output = attachment.output
        if output is None or not output.is_relative_to(store.root):
            raise EngineError("semantic_attachment_group_member_invalid", "Group artifacts must belong to the selected project.")
        asset_prefix = output.relative_to(store.root).as_posix() + "/"
        _require_assets(figure, prefix, asset_prefix, store)
        _add_fresh(writes, snapshot, member)
        _add_fresh(writes, snapshot, figure.assets)
    if (not required_outputs or len(set(required_outputs)) != len(required_outputs)
            or set(outputs) != set(required_outputs) or any(name.startswith(".sciplot_semantic/") for name in outputs)):
        raise EngineError("semantic_attachment_group_incomplete", "Prepare explicit group results outside individual attachment namespaces.")
    _add_fresh(writes, snapshot, outputs)
    writes[INDEX] = encode(index)
    mutation = PreparedMutation.from_values(writes, {"figure_ids": list(selected_figures), "group_outputs": sorted(outputs),
        "artifacts": {name: hashlib.sha256(data).hexdigest()
                      for figure in figures for name, data in sorted(figure.assets.items())}},
        prepared_sources=prepared_sources(store, sources, snapshot=snapshot))
    command = ProjectCommand.create("semantic_record", key, project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"],
        read_set={name: snapshot["files"].get(name, {}).get("sha256") for name in writes}, write_set=sorted(writes),
        request={"prepared_digest": mutation.prepared_digest, "adapter": "managed_attachment_group"},
        source_trees=(source_tree,))
    return ProjectCommands(store).publish_prepared(command, mutation)


def _require_assets(figure: PreparedFigure, prefix: str, asset_prefix: str, store: FileProjectStore) -> None:
    formats = [Path(name).suffix for name in figure.assets]
    if (any(formats.count(extension) != 1 for extension in (".vsz", ".pdf", ".tiff"))
            or not all(name.startswith(asset_prefix) for name in figure.assets)):
        raise EngineError("semantic_attachment_group_incomplete", "Every selected figure needs its complete native and export set.")
    head = json.loads(figure.members[prefix + "head.json"] or b"")
    revision = json.loads(figure.members.get(prefix + "revisions/00000000.json") or b"{}")
    binding = revision.get("binding", {})
    from .repository import digest

    if (head != {"revision": 0, "sha256": digest(revision)} or revision.get("document", {}).get("plot_type") != "ManagedPlot"
            or not isinstance(binding.get("document"), str)):
        raise EngineError("semantic_attachment_group_member_invalid", "Only an exact new Managed revision can be published in a new group.")
    document = Path(binding["document"])
    native = figure.assets.get(store.logical_path(document))
    marker = json.loads(figure.assets.get(store.logical_path(document.parent / "build.json"), b"{}"))
    if native is None or (marker.get("document_sha256"), marker.get("ir_hash")) != (
            hashlib.sha256(native).hexdigest(), binding.get("ir_hash")):
        raise EngineError("semantic_attachment_group_incomplete", "The published native bytes need their exact Managed compiler seal.")


def _add_fresh(writes: dict[str, bytes | None], snapshot: dict[str, Any], members: dict[str, Any]) -> None:
    if set(members).intersection(writes) or set(members).intersection(snapshot["files"]):
        raise EngineError("semantic_attachment_group_conflict", "A new group cannot overwrite existing or competing members.")
    writes.update(members)


def resume_attachment_group(store: FileProjectStore, key: str) -> dict[str, Any]:
    app = ProjectCommands(store)
    prior = app.query(key)
    if (prior is None or prior.get("phase") not in {"accepted", "complete"}
            or prior.get("metadata", {}).get("request", {}).get("adapter") != "managed_attachment_group"):
        raise EngineError("semantic_attachment_group_not_accepted", "Only an exact accepted group publication can resume without native work.")
    return app.resume(ProjectCommand.from_payload(prior["metadata"]))
