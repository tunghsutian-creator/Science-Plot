"""Resume only the exact sealed namespace transfer, with old-writer refusal first."""
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sciplot_core.project_commands import CommandKind, ProjectCommand, ProjectCommands
from sciplot_core.project_store.io import read_file
from sciplot_core.project_store.repository import FileProjectStore
from .attachment_fence import fence
from .attachment_index import Attachment, INDEX, OWNER, validate_index
from .errors import EngineError
from .attachment_store import with_backup


def transfer_boundary(stage: str) -> None:
    """Fault-injection boundary; no execution or persistence policy lives here."""


def candidate_bytes(record: dict[str, Any], logical: str) -> bytes:
    entry = record["draft"]["writes"].get(logical)
    if entry is None:
        raise EngineError("semantic_attachment_import_invalid", "The sealed transfer omitted a required resource.")
    path = Path(record["staged_paths"][logical])
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        data, _mode = read_file(descriptor, path.name)
    finally:
        os.close(descriptor)
    if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["size"]:
        raise EngineError("semantic_attachment_import_changed", "The frozen transfer resource changed.")
    return data


def resume_transfer(store: FileProjectStore, root: Path, figure_id: str, record: dict[str, Any], *,
                    parent: Any, namespace_bytes: Any) -> Attachment:
    command = ProjectCommand.from_payload(record["metadata"])
    request = json.loads(command.request_json)
    with store._locked(allow_pending=True) as (_io, current):
        actual_project_id = current["project_id"]
    if (command.kind != CommandKind.ATTACHMENT_IMPORT or record["command_digest"] != command.command_digest
            or record["project_id"] != command.project_id or command.project_id != actual_project_id
            or request.get("origin_root") != str(root)
            or request.get("figure_id") != figure_id or command.key != "attach:" + request.get("attachment_id", "")):
        raise EngineError("semantic_attachment_owner_conflict", "The saved transfer does not bind this exact project, figure and original namespace.")
    if record["phase"] == "reserved":
        raise EngineError("semantic_attachment_import_pending", "The original namespace is intact; retry the original import to prepare its bytes.")
    review = record.get("review", {})
    if (review.get("publication") != "prepared_storage" or review.get("prepared_digest") != request.get("prepared_digest")
            or record["phase"] not in {"needs_review", "accepted", "complete"}):
        raise EngineError("semantic_attachment_import_invalid", "The transfer has no exact sealed storage candidate.")
    index = validate_index(json.loads(candidate_bytes(record, INDEX)), command.project_id)
    entry = index["attachments"].get(request["attachment_id"])
    if (entry is None or entry["origin_root"] != request.get("scientific_origin", str(root))
            or entry.get("transfer_root", entry["origin_root"]) != str(root) or entry.get("history_root") != request["history_root"]
            or entry["figure_id"] != figure_id):
        raise EngineError("semantic_attachment_owner_conflict", "The frozen attachment index does not bind the original and history locations.")
    expected_marker = {"kind": "sciplot_semantic_owner", "version": 1, "origin_root": str(root),
              "project": request.get("project_path", entry["project_origin"]), "project_id": command.project_id,
              "attachment_id": request["attachment_id"], "history_root": request["history_root"], "figure_id": figure_id}
    prefix = entry["namespace"] + "/"
    marker = json.loads(candidate_bytes(record, prefix + OWNER))
    if not isinstance(marker, dict) or type(marker.get("version")) is not int:
        raise EngineError("semantic_attachment_owner_conflict", "The frozen ownership marker has an invalid format.")
    marker["origin_root"] = str(root)
    if marker != expected_marker:
        raise EngineError("semantic_attachment_owner_conflict", "The frozen ownership marker does not bind this exact original namespace.")
    archived = {logical: relative for relative, logical in entry["archived_derivatives"].items()}
    artifact_names = set(entry.get("archived_artifacts", {}).values())
    if "original_members" in entry:
        expected = {name: record["draft"]["writes"][entry["archived_derivatives"].get(name, prefix + name)]
                    for name in entry["original_members"]}
    else:
        expected = {archived.get(logical, logical.removeprefix(prefix)): value
                    for logical, value in record["draft"]["writes"].items()
                    if logical.startswith(prefix) and logical != prefix + OWNER and logical not in artifact_names}

    def verify_original(location: Path) -> None:
        directory = entry.get("transfer_directory")
        if directory is not None:
            actual_directory = location.stat(follow_symlinks=False)
            if (actual_directory.st_dev, actual_directory.st_ino, actual_directory.st_mode & 0o777) != (
                    directory["device"], directory["inode"], directory["mode"]):
                raise EngineError("semantic_attachment_import_changed", "The original semantic directory inode or mode changed after observation.")
        modes: dict[str, int] = {}
        actual = namespace_bytes(location, modes=modes)
        if (set(actual) != set(expected) or any(expected[name] is None
                or hashlib.sha256(data).hexdigest() != expected[name]["sha256"]
                or len(data) != expected[name]["size"] or modes[name] != expected[name]["mode"]
                for name, data in actual.items())):
            raise EngineError("semantic_attachment_import_changed", "The exact original history differs from its sealed transfer candidate.")

    head_sha = expected["head.json"]["sha256"]
    transfer_boundary("before_fence")
    artifact_root = entry.get("artifact_root")
    if artifact_root is not None and Path(artifact_root).exists():
        modes: dict[str, int] = {}
        actual = namespace_bytes(Path(artifact_root), modes=modes)
        expected_artifacts = entry["archived_artifacts"]
        if set(actual) != set(expected_artifacts) or any(
                hashlib.sha256(data).hexdigest() != record["draft"]["writes"][expected_artifacts[name]]["sha256"]
                or modes[name] != record["draft"]["writes"][expected_artifacts[name]]["mode"] for name, data in actual.items()):
            raise EngineError("managed_external_mutation", "The original native artifacts changed after currentness validation; preserve the pending transfer.")
    fence(root, marker, original_head_sha256=head_sha, verify_original=verify_original, parent=parent)
    transfer_boundary("after_fence")
    if command.namespace_transfers:
        store = with_backup(store, entry["id"], Path(marker["history_root"]))
    commands = ProjectCommands(store)
    if record["phase"] == "needs_review":
        commands.decide(command, decision_id=record["decision_id"], accept=True)
    else:
        commands.resume(command)
    transfer_boundary("after_publication")
    return Attachment(store, entry)
