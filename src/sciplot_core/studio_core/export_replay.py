"""Select current immutable export receipts and bind fresh automatic intentions."""

from __future__ import annotations

from typing import Any

from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectCommandUnknown
from sciplot_core.project_store import FileProjectStore, ProjectConflict

_AUTOMATIC = {"output_preimage", "output_predecessors"}


def _business(request: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in request.items() if key not in _AUTOMATIC}


def _scope(request: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(request.get(key) for key in ("document", "figure_id", "standalone_receipt", "authority"))


def current_export(app: ProjectCommands, store: FileProjectStore, request: dict[str, Any], *,
                   kind: str, whole_output: bool = False) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Use the sole command history; a changed artifact never reexecutes its old key."""
    records = [record for record in app.commands() if record.get("metadata", {}).get("kind") == kind
               and _scope(record["metadata"]["request"]) == _scope(request)]
    # An earlier admitted execution cannot be hidden by changing formats or the
    # automatic key. Resume only the exact frozen command, never its producer.
    for index, record in enumerate(records):
        if record["phase"] != "complete":
            completed = app.resume(ProjectCommand.from_payload(record["metadata"]))
            if completed["phase"] != "complete":
                raise ProjectCommandUnknown()
            records[index] = completed
    snapshot = store.snapshot()
    owned = {name for record in records for name in record.get("draft", {}).get("writes", {})}
    targets = set(snapshot["files"]) if whole_output else owned
    if any(name in snapshot.get("outside_changes", {}) for name in targets) or (
            whole_output and snapshot.get("outside_changes")):
        raise ProjectConflict("Export output bytes changed outside their registered command; all files were preserved")
    for name in targets:
        entry = snapshot["files"].get(name)
        if entry is not None:
            actual = store.projection_path(name)
            if actual.stat().st_mode & 0o777 != entry["mode"]:
                raise ProjectConflict("An export output mode changed outside its registered command")

    def matches(record: dict[str, Any]) -> bool:
        writes = record["draft"]["writes"]
        expected = {name for name, value in writes.items() if value is not None}
        if whole_output and set(snapshot["files"]) != expected:
            return False
        return all((snapshot["files"].get(name) is None if entry is None else
                    snapshot["files"].get(name, {}).get("sha256") == entry["sha256"]
                    and snapshot["files"][name]["mode"] == entry["mode"])
                   for name, entry in writes.items())

    ordered = sorted(records, key=lambda record: int(record.get("generation_sequence") or 0), reverse=True)
    for record in ordered:
        if _business(record["metadata"]["request"]) == request and matches(record):
            return record, {}
    # Existing outputs may be superseded only through another complete export.
    # Foreign registered writers and unregistered physical edits cannot supply
    # a new automatic overwrite permission.
    predecessors = set()
    for name in targets:
        current = snapshot["files"].get(name)
        for record in ordered:
            writes = record["draft"]["writes"]
            if name not in writes:
                continue
            entry = writes[name]
            if ((current is None and entry is None) or current is not None and entry is not None
                    and (current["sha256"], current["mode"]) == (entry["sha256"], entry["mode"])):
                predecessors.add(record["command_id"])
                break
        else:
            if records and current is not None:
                raise ProjectConflict("An existing output was not installed by a matching complete export")
    if not records:
        return None, {}
    preimage = {name: ({key: snapshot["files"][name][key] for key in ("sha256", "mode")}
                       if name in snapshot["files"] else None) for name in sorted(targets)}
    return None, {"output_preimage": preimage, "output_predecessors": sorted(predecessors)}
