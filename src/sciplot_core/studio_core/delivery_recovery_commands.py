"""Freeze an audited visible native adoption in the shared generation store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import NativeAdoption, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store.errors import ProjectConflict
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store, query_for_apply, whole_memberships


def _review(project: Path, record: dict[str, Any]) -> dict[str, Any]:
    return {**record["review"], "version": 2, "project": str(project),
            "command_key": record["command_id"], "decision_id": record["decision_id"]}


def stage_delivery_recovery(project: Path, review: dict[str, Any]) -> dict[str, Any]:
    repository = project_store(project)
    snapshot = repository.snapshot(import_legacy=True)
    document, candidate = Path(review["document"]), Path(review["candidate"])
    target, visible = repository.logical_path(document), repository.logical_path(candidate)
    adopted = candidate.read_bytes()
    observed = file_sha256(candidate)
    if observed != review["hashes"]["candidate"] or file_sha256(document) != review["hashes"]["document"]:
        raise ValueError("The reviewed native recovery inputs changed before freezing")
    reads = {name: value["sha256"] for name, value in snapshot["files"].items()}
    binding = {"project_id": snapshot["project_id"], "generation": snapshot["generation"], "files": reads,
               "read_memberships": whole_memberships(repository, snapshot)}
    writes: dict[str, bytes | Path | None] = {target: adopted}
    adoptions = []
    if reads[visible] != observed:
        audit = canonical_json_sha256({"audit": review["scientific_audit"], "candidate": observed,
                                      "spec": review["fingerprints"]["spec"]})
        adoptions.append(NativeAdoption(visible, reads[visible], observed, audit))
        writes[visible] = adopted
    intent = {"family": "delivery_recovery", "authority": "legacy_native",
              "document_relative": target, "visible_relative": visible,
              "hashes": review["hashes"], "fingerprints": review["fingerprints"]}
    key = canonical_json_sha256({"project_id": snapshot["project_id"], "intent": intent})
    command = command_for_binding(repository, binding, kind="native_import" if adoptions else "native_patch",
        key=key, writes=list(writes), request=intent, native_adoptions=adoptions)
    artifacts = {"before.vsz": document.read_bytes(), "adopted.vsz": adopted,
                 "review.json": json.dumps(review, ensure_ascii=False, allow_nan=False).encode()}
    record = ProjectCommands(repository).preview(command, lambda: ProjectMutation(writes,
        {"document_relative": target, "visible_relative": visible,
         "document_sha256": observed, "previous_document_sha256": review["hashes"]["document"]},
        review=review, artifacts=artifacts,
        sources=[{"source_id": canonical_json_sha256({"project_id": snapshot["project_id"], "visible": visible})[:32],
                  "path": str(candidate), "version": observed}]))
    return _review(project, record)


def decide_delivery_recovery(project: Path, supplied: dict[str, Any]) -> dict[str, Any]:
    app = ProjectCommands(project_store(project))
    record = query_for_apply(app, str(supplied.get("command_key") or ""))
    if record is None or supplied != _review(project, record):
        raise ValueError("The recovery preview is stale or modified; use the exact frozen preview")
    try:
        completed = app.decide(ProjectCommand.from_payload(record["metadata"]),
                               decision_id=record["decision_id"], accept=True)
    except ProjectConflict as exc:
        raise ValueError(f"The recovery preview is stale or modified: {exc}") from exc
    result = completed["result"]
    document = project / result["document_relative"]
    if file_sha256(document) != result["document_sha256"]:
        raise ValueError("The recovered native document has since changed")
    return {"kind": "sciplot_delivery_recovery_result", "version": 1, "status": "recovered",
            "project": str(project), "document": str(document), "candidate": supplied["candidate"],
            "archive": completed["artifact_paths"]["before.vsz"],
            "document_sha256": result["document_sha256"],
            "previous_document_sha256": result["previous_document_sha256"], "export_required": True,
            "project_command": {key: completed[key] for key in ("command_id", "phase", "project_id", "generation")}}
