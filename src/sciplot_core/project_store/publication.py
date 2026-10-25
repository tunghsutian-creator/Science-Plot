"""Freeze complete generations, publish one head, recover derived installation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from . import commands, projection, state
from .errors import ProjectCommandConflict, ProjectConflict
from .io import StoreIO


def publish(io: StoreIO, current: dict[str, Any], record: dict[str, Any], *,
            frozen: dict[str, Any]) -> dict[str, Any]:
    outcome = current["commands"].get(record["command_id"])
    if outcome is not None:
        if outcome["command_digest"] != record["command_digest"]:
            raise ProjectCommandConflict("The generation command outcome binds a different request.")
        projection.recover(io, current)
        return state.command(io, record["command_id"], record["command_digest"]) or record
    if record["phase"] not in {"reserved", "applying", "accepted"}:
        raise ProjectCommandConflict("The command cannot publish without its frozen accepted decision.")
    state.require_reads(io, current, record)
    writes = dict(frozen["writes"])
    if set(writes) != set(record["write_set"]):
        raise ProjectConflict("Publication does not cover the exact reserved write set.")
    projected = commands.projected_writes(record)
    for name in {item["resource"] for item in projected}:
        from sciplot_core.project_commands.read_projections import merge_projection

        candidate = writes.get(name)
        present = current["files"].get(name)
        if candidate is None or present is None:
            raise ProjectConflict("A projected update cannot delete or create an entire resource.")
        merged, candidate_bytes = io.get(present), io.get(candidate)
        for selector in (item for item in projected if item["resource"] == name):
            merged = merge_projection(merged, candidate_bytes, kind=selector["kind"], key=selector["key"])
        writes[name] = {**io.put(merged), "mode": present["mode"]}
    value = deepcopy(current)
    value.update(parent=current["generation"], generation=uuid4().hex,
                 sequence=current["sequence"] + 1, origin="command")
    value["locators"].update({key: str(path) for key, path in io.locations.items()})
    for name, entry in writes.items():
        if entry is None:
            value["files"].pop(name, None)
        else:
            prior = current["files"].get(name)
            value["files"][name] = {**entry, "file_id": prior["file_id"] if prior else uuid4().hex}
    for source_id, versions in frozen.get("sources", {}).items():
        destination = value["sources"].setdefault(source_id, {})
        for version, entry in versions.items():
            if version in destination and destination[version] != entry:
                raise ProjectConflict("A stable source version already has different provenance.")
            destination[version] = entry
    outcome = {"command_id": record["command_id"], "command_digest": record["command_digest"],
        "project_id": current["project_id"], "generation": value["generation"],
        "phase": "complete", "result": frozen["result"], "review": record.get("review", {}),
        "metadata": record["metadata"], "read_set": record["read_set"],
        "write_set": record["write_set"], "projected_reads": record.get("projected_reads", []),
        "candidate_digest": record.get("decision_id"), "artifacts": frozen.get("artifacts", {})}
    value["commands"][record["command_id"]] = outcome
    state.boundary("before_storage")
    state.write_generation(io, value)
    state.boundary("after_generation")
    record.update(install_parent=current["generation"], install_generation=value["generation"],
                  install_files=sorted(writes), pending_result=frozen["result"])
    state.save_command(io, record)
    state.publish_head(io, value)
    projection.project(io, record, value)
    record.update(phase="complete", generation=value["generation"], result=frozen["result"])
    state.save_command(io, record)
    state.boundary("before_reply")
    return record
