"""One authenticated physical-absence preimage for explicit generated export."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
import os
from typing import Any, Protocol

from sciplot_core.project_commands import MissingGeneratedOutput, ProjectCommand, ProjectionRead
from .committed_outcomes import require as committed_outcome
from .errors import ProjectConflict
from .generated_output_owners import catalog_matches, logical, receipt_matches
from .io import StoreIO, directory, sha
import sciplot_core.project_store.state as state


class OutputStore(Protocol):
    def _locked(self) -> AbstractContextManager[tuple[StoreIO, dict[str, Any]]]: ...


def values(record: dict[str, Any]) -> dict[str, MissingGeneratedOutput]:
    supplied = record.get("metadata", {}).get("missing_outputs", [])
    if not supplied:
        return {}
    command = ProjectCommand.from_payload(record["metadata"])
    if (command.command_digest != record["command_digest"] or command.project_id != record["project_id"]
            or command.key != record["command_id"] or command.expected_generation != record["expected_generation"]
            or dict(command.read_set) != record["read_set"]
            or list(command.write_set) != record["write_set"]
            or [item.to_payload() for item in command.projected_reads] != record.get("projected_reads", [])):
        raise ProjectConflict("Missing-output admission differs from its exact typed command.")
    return {item.resource: item for item in command.missing_outputs}


@contextmanager
def _proof(io: StoreIO, current: dict[str, Any]) -> Iterator[state.CheckedHead]:
    checked = state.checked_head(io)
    if checked is None:
        raise ProjectConflict("Missing outputs require a checked current generation.")
    try:
        if checked.current != current:
            raise ProjectConflict("Missing outputs require the exact current checked generation.")
        yield checked
    finally:
        checked.close()


def _latest(io: StoreIO, current: dict[str, Any], name: str, checked: state.CheckedHead) -> dict[str, Any] | None:
    cursor = current
    while True:
        writers = [item for item in cursor["commands"].values()
                   if item["generation"] == cursor["generation"] and name in item["write_set"]]
        if len(writers) > 1:
            raise ProjectConflict("One generated output has ambiguous publication ownership.")
        if writers:
            outcome = writers[0]
            record = state.command(io, outcome["command_id"], outcome["command_digest"])
            if record is None or record["phase"] != "complete":
                raise ProjectConflict("Only a completed current output producer can authorize a fresh export.")
            committed_outcome(io, current, record, checked=checked)
            return record
        if cursor.get("parent") is None:
            return None
        cursor = state.reachable(io, current, cursor["parent"], checked=checked)


def _role(io: StoreIO, current: dict[str, Any], item: MissingGeneratedOutput, checked: state.CheckedHead) -> None:
    name = item.resource
    entry = current["files"].get(name)
    if entry is None or (entry["sha256"], entry["mode"]) != (item.before_sha256, item.mode):
        raise ProjectConflict("The missing output no longer has its exact registered byte/mode preimage.")
    forbidden = set(current.get("input_resources", [])) | set(current.get("history_resources", []))
    for versions in current.get("sources", {}).values():
        forbidden.update(logical(current, source["locator"]) for source in versions.values())
    if name in forbidden:
        raise ProjectConflict("An original input/source/history cannot become a missing generated output.")
    latest = _latest(io, current, name, checked)
    if item.owner_key is not None:
        if (latest is None or (latest["command_id"], latest["command_digest"]) != (item.owner_key, item.owner_digest)
                or latest["metadata"]["kind"] not in {"native_export", "export", "publish", "native_import", "native_create"}
                or not receipt_matches(current, name, latest["result"])):
            raise ProjectConflict("The missing output is not owned by its current complete export receipt.")
    else:
        assert item.catalog is not None
        if latest is not None:
            fixed = latest["metadata"].get("request", {}).get("adapter")
            if (latest["metadata"]["kind"] != "native_create"
                    or fixed not in {"prepared_native_suite", "analysis_native_suite"}
                    or item.catalog.resource not in latest["write_set"]):
                raise ProjectConflict("A catalog cannot replace a later registered output writer.")
        if not catalog_matches(io, current, name, item.catalog):
            raise ProjectConflict("The admitted catalog does not prove this exact generated destination.")
    if latest is not None:
        entry = latest["draft"]["writes"].get(name)
        if entry is None or any(entry[key] != current["files"][name][key] for key in ("sha256", "size", "mode")):
            raise ProjectConflict("The output's current bytes differ from its sealed producing write.")


def _absent(io: StoreIO, name: str, expected: tuple[int, ...] | None = None) -> tuple[int, ...]:
    root, components = io.split(name)
    # An existing anchored parent is required; missing arbitrary scaffolds are
    # not a file-absence observation or a new directory creation permission.
    with directory(root, components[:-1]) as parent:
        info = os.fstat(parent)
        identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
        if expected is not None and identity != expected:
            raise ProjectConflict("The missing generated output's observed parent changed.")
        try:
            os.stat(components[-1], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return identity
        raise ProjectConflict("A declared missing generated output is physically present.")


def require(io: StoreIO, current: dict[str, Any], record: dict[str, Any]) -> dict[str, MissingGeneratedOutput]:
    declared = values(record)
    if not declared:
        return declared
    with _proof(io, current) as checked:
        for item in declared.values():
            _role(io, checked.current, item, checked)
            _absent(io, item.resource, item.parent_identity)
    return declared


def discover(store: OutputStore, resources: Sequence[str], *,
             catalogs: Sequence[ProjectionRead] = ()) -> tuple[MissingGeneratedOutput, ...]:
    """Return proved exact absences; no caller can supply an ownership predicate."""
    result = []
    with store._locked() as (io, bound), _proof(io, bound) as checked:
        current = checked.current
        for name in sorted(set(resources)):
            entry = current["files"].get(name)
            if entry is None:
                continue  # Ordinary new-output absence already has its normal read=None guard.
            physical = io.physical(name)
            if physical is not None:
                if (sha(physical[0]), physical[1]) != (entry["sha256"], entry["mode"]):
                    raise ProjectConflict("An export output changed outside its registered owner.")
                continue
            latest = _latest(io, current, name, checked)
            parent = _absent(io, name)
            if latest is not None and receipt_matches(current, name, latest["result"]):
                item = MissingGeneratedOutput(name, entry["sha256"], entry["mode"],
                                              latest["command_id"], latest["command_digest"], parent_identity=parent)
            else:
                matches = [selector for selector in catalogs if catalog_matches(io, current, name, selector)]
                if not matches:
                    raise ProjectConflict("Missing resource lacks an admitted generated-output catalog or complete producer.")
                item = MissingGeneratedOutput(name, entry["sha256"], entry["mode"], catalog=matches[0], parent_identity=parent)
            _role(io, current, item, checked)
            result.append(item)
    return tuple(result)


def validate_writes(record: dict[str, Any], writes: dict[str, Any]) -> None:
    for item in values(record).values():
        candidate = writes.get(item.resource)
        if candidate is None or candidate["mode"] != item.mode:
            raise ProjectConflict("Missing-output publication requires exact-mode non-deleted fresh output bytes.")


def completed_writes(store: OutputStore, records: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Use installed immutable bytes, including selected projection merges."""
    result = {}
    with store._locked() as (io, current), _proof(io, current) as checked:
        for record in records:
            committed = committed_outcome(io, checked.current, record, checked=checked)
            if committed is None or record["phase"] != "complete":
                raise ProjectConflict("Export replay requires its exact completed outcome.")
            result[record["command_id"]] = {name: committed.generation["files"].get(name) for name in record["write_set"]}
    return result


def projection_names(record: dict[str, Any], outcome: dict[str, Any]) -> frozenset[str]:
    """Installation rights derive from the new immutable outcome, never hints."""
    metadata = outcome["metadata"]
    if metadata != record["metadata"]:
        raise ProjectConflict("The missing-output projection metadata differs from its immutable outcome.")
    return frozenset(values(record))


def require_projection_parent(io: StoreIO, record: dict[str, Any], name: str) -> None:
    item = values(record).get(name)
    if item is not None:
        _absent(io, name, item.parent_identity)


def pending_barrier(app: Any, resources: Sequence[str], *, document: str | None = None) -> None:
    """Existing admitted effects cannot be hidden by a new absence/formats key."""
    from sciplot_core.project_commands import ProjectCommandUnknown
    for record in app.commands():
        if record["phase"] in {"complete", "rejected"}:
            continue
        request = record["metadata"].get("request", {})
        if set(record["write_set"]) & set(resources) or document is not None and request.get("document") == document:
            resumed = app.resume(ProjectCommand.from_payload(record["metadata"]))
            if resumed["phase"] != "complete":
                raise ProjectCommandUnknown()
