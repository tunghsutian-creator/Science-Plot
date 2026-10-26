"""Bind native Task revisions to their one sealed command owner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import CommandKind, ProjectCommand, ProjectCommands
from sciplot_core.project_commands.errors import ProjectCommandUnknown
from sciplot_core.project_store.preconditions import require_reads
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.document_edit_review import reviewed_edit, verified_document_edit_review
from sciplot_core.studio_core.document_edit_state import native_edit_request_key
from sciplot_core.studio_core.project_command_scope import figure_read_state, project_store
from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.task_editing import unchanged_style_review
from sciplot_core.task_storage import save_task


def native_task_request_id(state: dict[str, Any], revision: int | None = None) -> str | None:
    scope = state.get("native_command_scope")
    revision = len(state.get("edit_revisions") or []) + 1 if revision is None else revision
    if scope is None:
        return None
    # The stored scope survives relocation; never derive it again from today's path.
    native_edit_request_key("scope", scope)
    first = state.get("native_scope_start_revision")
    if type(first) is not int or first < 1:
        raise ValueError("The native task command scope has no exact first revision.")
    return (canonical_json_sha256({"scope": scope, "revision": revision})
            if revision >= first else None)


def initialize_native_task(root: Path, state: dict[str, Any], *, new_revision: bool) -> str | None:
    if "native_command_scope" not in state and (new_revision or not state.get("preview_attempt")):
        state["native_command_scope"] = canonical_json_sha256({
            "kind": "native_task", "task_dir": state["task_dir"],
            "created_at": state["created_at"], "request": state["request"],
        })
        state["native_scope_start_revision"] = len(state.get("edit_revisions") or []) + 1
        save_task(root, state)  # Freeze the operation identity before any native effect.
    return native_task_request_id(state)


def _owned_records(repository: Any, state: dict[str, Any]) -> list[tuple[ProjectCommand, dict[str, Any]]]:
    if "native_command_scope" not in state:
        return []  # Historical unscoped previews can be shared by other Tasks.
    project_id = repository.snapshot()["project_id"]
    app, records = ProjectCommands(repository), []
    for revision in range(state["native_scope_start_revision"], len(state.get("edit_revisions") or []) + 2):
        identity = native_task_request_id(state, revision)
        assert identity is not None
        key = native_edit_request_key(project_id, identity)
        record = app.query(key)
        if record is None:
            continue
        command = ProjectCommand.from_payload(record["metadata"])
        if (command.kind != CommandKind.DOCUMENT_EDIT or command.project_id != project_id
                or command.key != key or command.command_digest != record["command_digest"]
                or json.loads(command.request_json).get("request_id") != identity):
            raise ValueError("The task's native revision belongs to a different sealed command.")
        if record["phase"] not in {"needs_review", "rejected"}:
            # Never hide an accepted, completed or uncertain effect behind Task cancellation.
            raise ProjectCommandUnknown()
        verified_document_edit_review(repository.root, reviewed_edit(record, repository.root))
        records.append((command, record))
    return records


def _reject(repository: Any, records: list[tuple[ProjectCommand, dict[str, Any]]]) -> None:
    app = ProjectCommands(repository)
    for command, record in records:
        retired = app.decide(command, decision_id=record["decision_id"], accept=False)
        if retired["phase"] != "rejected":
            raise ValueError("The native candidate did not reach its no-effect terminal decision.")


def finish_native_task_preview(state: dict[str, Any], review: dict[str, Any],
                               request_id: str | None) -> dict[str, Any]:
    if review.get("version") != 3:
        return review  # Historical v2 contracts retain their original path.
    project = Path(review["project"])
    verified, record = verified_document_edit_review(project, review)
    if record["metadata"]["request"].get("request_id") != request_id:
        raise ValueError("The native preview does not belong to this exact task revision.")
    repository = project_store(project)
    with repository._locked() as (io, current):
        require_reads(io, current, record)
        with project_runtime(repository, generation=current["generation"]):
            selected = resolve_project_figure(project, verified["figure_id"])
            observed = figure_read_state(project, selected)
        if observed["source_files"] != record["metadata"]["request"]["source_files"]:
            raise ValueError("The task preview's scientific source versions changed.")
        noop = unchanged_style_review(verified)
        if not noop and record["phase"] != "needs_review":
            raise ValueError("This changed native candidate already has a terminal decision.")
        if request_id is not None:
            records = _owned_records(repository, state)
            _reject(repository, [(command, item) for command, item in records
                                  if noop or item["command_id"] != record["command_id"]])
        # Legacy unscoped evidence is not retrospectively this Task's exclusive command.
    return {**verified, **({"review_path": review["review_path"]} if "review_path" in review else {})}


def cancel_native_task(root: Path, state: dict[str, Any]) -> None:
    review = json.loads((root / "review.json").read_text())
    if review.get("operation_id") != state.get("operation_id"):
        raise ValueError("The task's native review changed before cancellation.")
    if review.get("version") != 3:
        return
    project = Path(state["project"])
    verified_document_edit_review(project, review)  # Historical identity, not current source freshness.
    repository = project_store(project)
    with repository._locked():
        _reject(repository, _owned_records(repository, state))
