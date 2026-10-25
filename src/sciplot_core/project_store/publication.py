"""Freeze complete generations, publish one head, recover derived installation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

import sciplot_core.project_store.commands as commands
import sciplot_core.project_store.projection as projection
import sciplot_core.project_store.state as state
import sciplot_core.project_store.preconditions as preconditions
from .errors import ProjectCommandConflict, ProjectConflict
from .io import StoreIO, digest
from .source_observations import adopt, local_versions
from .root_bindings import identities
from .namespace_transfers import require as require_namespaces, values as namespace_values


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
    preconditions.require_reads(io, current, record)
    namespaces = require_namespaces(io, current, record)
    writes = dict(frozen["writes"])
    if set(writes) != set(record["write_set"]):
        raise ProjectConflict("Publication does not cover the exact reserved write set.")
    for name, adoption in preconditions.native_adoptions(record).items():
        if (writes[name] is None or writes[name]["sha256"] != adoption["observed_sha256"]
                or writes[name]["mode"] != record["adoption_modes"][name]):
            raise ProjectConflict("The imported native candidate differs from the explicitly audited outside bytes.")
    projected = preconditions.projected_writes(record)
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
    value.update(parent=current["generation"], parent_sha256=digest(current), generation=uuid4().hex,
                 sequence=current["sequence"] + 1, origin="command")
    value["resource_roots"] = identities(io)
    value["history_resources"] = sorted(set(current.get("history_resources", [])) | namespaces.history)
    value["retired_namespace_prefixes"] = sorted(set(current.get("retired_namespace_prefixes", []))
        | {item.prefix for item in namespace_values(record)})
    for key, path in io.locations.items():
        value["locators"].setdefault(key, str(path))
    for name, entry in writes.items():
        if entry is None:
            value["files"].pop(name, None)
        else:
            prior = current["files"].get(name)
            value["files"][name] = {**entry, "file_id": prior["file_id"] if prior else uuid4().hex}
    adopt(io, current, value, record, frozen)
    for source_id, versions in frozen.get("sources", {}).items():
        destination = value["sources"].setdefault(source_id, {})
        for version, entry in versions.items():
            if version in destination and destination[version] != entry:
                before = destination[version]
                before_core = {key: item for key, item in before.items() if key != "aliases"}
                after_core = {key: item for key, item in entry.items() if key != "aliases"}
                if (before_core != after_core or not set(before.get("aliases", [])).issubset(entry.get("aliases", []))):
                    raise ProjectConflict("A stable source version already has different provenance or lost an explicit alias.")
            destination[version] = entry
    alias_owners: dict[tuple[str, str, str], str] = {}
    for source_id, versions in value["sources"].items():
        for version, entry in versions.items():
            for alias in entry.get("aliases", []):
                identity = (entry["locator"], version, alias)
                if identity in alias_owners and alias_owners[identity] != source_id:
                    raise ProjectConflict("A logical source alias is ambiguous for the exact original locator/version.")
                alias_owners[identity] = source_id
    outcome = {"command_id": record["command_id"], "command_digest": record["command_digest"],
        "project_id": current["project_id"], "generation": value["generation"],
        "phase": "complete", "result": frozen["result"], "review": record.get("review", {}),
        "metadata": record["metadata"], "read_set": record["read_set"],
        "write_set": record["write_set"], "projected_reads": record.get("projected_reads", []),
        "candidate_digest": record.get("decision_id"), "artifacts": frozen.get("artifacts", {}),
        "namespace_origins": record.get("namespace_origins", {})}
    value["commands"][record["command_id"]] = outcome
    state.boundary("before_storage")
    state.write_generation(io, value)
    state.boundary("after_generation")
    record.update(install_parent=current["generation"], install_generation=value["generation"],
                  install_files=sorted(set(writes) - namespaces.installed), pending_result=frozen["result"])
    state.save_command(io, record)
    state.boundary("before_head")
    io.verify_roots()
    preconditions.require_reads(io, current, record)
    commands.verify_sources(io, frozen.get("sources", {}), record)
    local_versions(io, record)
    if io.read("local_locations.json") is not None:
        expected_root = io.root / ".sciplot_resources"
        if any(path != expected_root / key for key, path in io.locations.items()):
            raise ProjectConflict("A cold project resource must retain its confined host-selected local root.")
        io.write("local_locations.json", {"ids": sorted(io.locations), "members": io.location_members})
    state.publish_head(io, value)
    state.boundary("after_head")
    projection.project(io, record, value)
    record.update(phase="complete", generation=value["generation"], result=frozen["result"])
    state.save_command(io, record)
    state.boundary("before_reply")
    return record
