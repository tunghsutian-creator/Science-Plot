"""Read sealed native edit reviews without applying or repairing a project."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import CommandKind, ProjectCommand, ProjectCommands
from sciplot_core.studio_core.document_edit_state import check_artifact
from sciplot_core.studio_core.project_command_scope import project_store
from sciplot_core.studio_core.project_query import resolve_project_path


def reviewed_edit(record: dict[str, Any], project: Path) -> dict[str, Any]:
    if record.get("metadata", {}).get("kind") != "document_edit":
        raise ValueError("This saved command is not a reviewed native document edit")
    frozen = record["draft"]
    if any(canonical_json_sha256(record.get(key), allow_nan=False) !=
           canonical_json_sha256(frozen[key], allow_nan=False) for key in ("review", "result")):
        raise ValueError("The native review receipt differs from its sealed candidate")
    review: dict[str, Any] = deepcopy(frozen["review"])
    result = frozen["result"]
    paths = record["artifact_paths"]
    native_hash = review["candidate"]["sha256"]
    if (frozen["writes"][result["document_relative"]]["sha256"] != native_hash
            or frozen["artifacts"]["after.vsz"]["sha256"] != native_hash
            or frozen["artifacts"]["before.vsz"]["sha256"] != result["base_sha256"]
            or frozen["artifacts"]["candidate.png"]["sha256"] != review["preview"]["sha256"]):
        raise ValueError("The sealed native candidate does not match its exact audited review")
    if "companion" in result:
        companion = result["companion"]
        if (frozen["writes"][companion["relative"]]["sha256"] != companion["result_sha256"]
                or frozen["artifacts"]["after.spec.json"]["sha256"] != review["candidate_spec"]["sha256"]
                or frozen["artifacts"]["before.spec.json"]["sha256"] != companion["base_sha256"]):
            raise ValueError("The sealed specification does not match its exact audited native pair")
    review.update(operation_id=record["command_id"], decision_id=record["decision_id"],
                  project=str(project), document=str(project / result["document_relative"]))
    review["candidate"]["path"] = paths["after.vsz"]
    review["preview"]["path"] = paths["candidate.png"]
    if "candidate_spec" in review:
        review["candidate_spec"]["path"] = paths["after.spec.json"]
        review["spec"] = str(project / result["companion"]["relative"])
    return review


def verified_document_edit_review(project: Path, supplied: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select one typed sealed review; runtime paths come only from its owner.

    This is historical candidate evidence. Current input/figure preconditions
    belong to the caller's read/commit boundary and are not inferred here.
    """
    if (supplied.get("kind") != "sciplot_document_edit_preview"
            or type(supplied.get("version")) is not int or supplied["version"] != 3
            or supplied.get("status") != "ready"):
        raise ValueError("A complete version-3 native document edit review is required")
    project = resolve_project_path(project)
    store = project_store(project)
    record = ProjectCommands(store).query(str(supplied.get("operation_id") or ""))
    if record is None or record.get("phase") not in {"needs_review", "accepted", "complete"}:
        raise ValueError("No frozen native review belongs to this selected project")
    command = ProjectCommand.from_payload(record["metadata"])
    if (command.kind != CommandKind.DOCUMENT_EDIT or command.key != record["command_id"]
            or command.project_id != record["project_id"] or command.project_id != store.snapshot()["project_id"]
            or command.command_digest != record["command_digest"]
            or canonical_json_sha256(record["metadata"], allow_nan=False) != command.command_digest
            or dict(command.read_set) != record["read_set"] or list(command.write_set) != record["write_set"]):
        raise ValueError("The native review changed its typed command identity or read/write witness")
    expected = reviewed_edit(record, project)
    intent, result = json.loads(command.request_json), record["draft"]["result"]
    if (result["base_files"] != record["read_set"] or intent["expected_files"] != result["base_files"]
            or intent["document_relative"] != result["document_relative"]
            or intent["figure_id"] != expected["figure_id"] or result["figure_id"] != expected["figure_id"]
            or result["base_sha256"] != expected["document_sha256"]
            or record["read_set"].get(result["document_relative"]) != expected["document_sha256"]
            or intent["changes"] != expected["changes"] or intent["operations"] != expected.get("operations")
            or expected.get("scientific_audit", {}).get("status") != "passed"):
        raise ValueError("The native review differs from its sealed figure, input or audited edit intent")
    rebound = deepcopy({key: value for key, value in supplied.items() if key != "review_path"})
    for key in ("project", "document", "spec"):
        if key in expected:
            rebound[key] = expected[key]
    for key in ("candidate", "preview", "candidate_spec"):
        if key in expected and isinstance(rebound.get(key), dict):
            rebound[key]["path"] = expected[key]["path"]
    if canonical_json_sha256(rebound, allow_nan=False) != canonical_json_sha256(expected, allow_nan=False):
        raise ValueError("The relocated native preview changed its sealed intent or scientific evidence")
    for key in ("candidate", "preview", "candidate_spec"):
        if key in expected:
            check_artifact(expected[key])
    return expected, record


def rebind_document_edit_review(project: Path, original: dict[str, Any]) -> dict[str, Any]:
    """Rebind known runtime paths while retaining sealed scientific literals."""
    return verified_document_edit_review(project, original)[0]
