"""Durable command admission and sealed candidate decisions in the one store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
from typing import Any

from sciplot_core.project_commands.resources import PreparedFile
from sciplot_core.foundation.json_values import json_safe

from .errors import ProjectCommandConflict, ProjectConflict, ProjectStoreError
from .io import StoreIO, digest, directory, install, parts, read_file, sha
from .root_bindings import identities, scope_local_import
from .committed_outcomes import require as committed_outcome
import sciplot_core.project_store.state as state
import sciplot_core.project_store.preconditions as preconditions


def reserve(io: StoreIO, current: dict[str, Any], command_id: str, command_digest: str, *,
            expected_generation: str | None, read_set: Mapping[str, str | None], write_set: Sequence[str],
            metadata: dict[str, Any] | None, projected_reads: Sequence[dict[str, Any]]) -> dict[str, Any]:
    existing = state.command(io, command_id, command_digest)
    if existing is not None:
        return existing
    scope_local_import(io, current)
    if not isinstance(command_digest, str) or not command_digest:
        raise ProjectStoreError("A frozen business command digest is required.")
    record = {"kind": "sciplot_project_command", "version": 1, "project_id": current["project_id"],
        "command_id": command_id, "command_digest": command_digest, "phase": "reserved",
        "expected_generation": expected_generation or current["generation"], "generation": current["generation"],
        "read_set": dict(read_set), "write_set": sorted(set(write_set)),
        "projected_reads": list(projected_reads), "metadata": json.loads(json.dumps(json_safe(metadata or {}), allow_nan=False)),
        "result": {}, "review": {}}
    record["resource_roots"] = identities(io)
    projected = {item["resource"] for item in preconditions.projected_writes(record)}
    adoptions = preconditions.native_adoptions(record)
    record["adoption_modes"] = {}
    for name in adoptions:
        physical = io.physical(name)
        if physical is None:
            raise ProjectConflict("The audited native import resource disappeared.")
        record["adoption_modes"][name] = physical[1]
    from .source_observations import observations

    record["source_adoption_modes"] = {}
    for name in observations(record):
        physical = io.physical(name, owned=False)
        if physical is None:
            raise ProjectConflict("The exact observed original input disappeared.")
        record["source_adoption_modes"][name] = physical[1]
    for name in [*record["read_set"], *record["write_set"]]:
        parts(name)
        io.split(name)
    if any(name not in read_set and name not in projected for name in record["write_set"]):
        raise ProjectStoreError("Every full-resource write needs an exact before hash or absence read.")
    from .namespace_transfers import require as require_namespaces
    from .source_trees import require as require_source_trees

    require_namespaces(io, current, record, admit=True)
    require_source_trees(io, current, record, admit=True)
    preconditions.require_reads(io, current, record)
    state.save_command(io, record)
    return record


def mark_applying(io: StoreIO, record: dict[str, Any]) -> dict[str, Any]:
    if record["phase"] != "reserved":
        raise ProjectCommandConflict("This command already entered native preparation; never execute it twice.")
    record["phase"] = "applying"
    state.save_command(io, record)
    state.boundary("before_native")
    return record


def capture_sources(io: StoreIO, sources: Sequence[dict[str, Any]] | None) -> dict[str, Any]:
    from uuid import uuid4
    from .produced_sources import bind

    result: dict[str, Any] = {}
    for supplied in sources or ():
        item = dict(supplied)
        source_id = item.get("source_id") or uuid4().hex
        if not isinstance(source_id, str) or len(source_id) != 32 or any(c not in "0123456789abcdef" for c in source_id):
            raise ProjectStoreError("A source identity must be a stable UUID hex value.")
        local = io.read("local_sources.json") or {"versions": {}}
        current = state.head(io)
        version = item.get("version")
        prior = current["sources"].get(source_id, {}).get(version) if current else None
        if "data" in item:
            from sciplot_core.project_commands.resources import PreparedSource

            source = PreparedSource(source_id, item["locator"], item["version"], item["data"],
                                    tuple(item.get("aliases", ())), item.get("mode", 0o600), item.get("produced_resource"))
            if item.get("size", len(source.data)) != len(source.data):
                raise ProjectConflict("The prepared source size differs from its exact bytes.")
            entry = {**io.put(source.data), "source_id": source_id, "locator": source.locator,
                     "version": source.version, "mode": source.mode}
            if prior is not None:
                if any(prior.get(key) != entry[key] for key in entry):
                    raise ProjectConflict("A prepared source conflicts with the existing immutable source version.")
                entry = dict(prior)
            entry = bind(entry, source.produced_resource)
            aliases = sorted(set(entry.get("aliases", [])) | set(source.aliases))
            if aliases:
                entry["aliases"] = aliases
            result.setdefault(source_id, {})[source.version] = entry
            continue
        path = Path(item["path"])
        if prior is not None and local["versions"].get(source_id, {}).get(version) == prior["sha256"]:
            if str(item.get("locator") or path) != prior.get("locator"):
                raise ProjectConflict("The relocated source descriptor changed its preserved original locator.")
            io.get(prior)
            result.setdefault(source_id, {})[version] = bind(dict(prior), item.get("produced_resource"))
            continue
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            data, mode = read_file(parent, path.name)
        finally:
            os.close(parent)
        version = sha(data)
        if item.get("version") != version:
            raise ProjectConflict("The captured source differs from its explicit version.")
        entry = {**io.put(data), "mode": mode, "source_id": source_id,
                 "locator": str(item.get("locator") or path), "version": version}
        if entry["locator"] != str(path):
            if prior is None or prior.get("locator") != entry["locator"] or prior["sha256"] != version:
                raise ProjectConflict("Only an existing source ID/version can preserve a different host read locator.")
            entry = dict(prior)
        entry = bind(entry, item.get("produced_resource"))
        aliases = sorted(set(entry.get("aliases", [])) | set(item.get("aliases", [])))
        if aliases:
            entry["aliases"] = aliases
        result.setdefault(source_id, {})[entry["version"]] = entry
    return result


def stage(io: StoreIO, record: dict[str, Any], *, writes: Mapping[str, bytes | Path | PreparedFile | None],
          result: dict[str, Any], review: dict[str, Any], artifacts: Mapping[str, bytes | Path | PreparedFile] | None,
          sources: Sequence[dict[str, Any]] | None, input_reads: Sequence[dict[str, str]] = ()) -> dict[str, Any]:
    if record["phase"] in {"needs_review", "accepted", "rejected", "complete"}:
        return record
    if record["phase"] not in {"reserved", "applying"}:
        raise ProjectCommandConflict("This command cannot produce another candidate.")
    if set(writes) != set(record["write_set"]):
        raise ProjectStoreError("The candidate must exactly cover the declared write set.")
    from .source_trees import require as require_source_trees

    current = state.head(io)
    assert current is not None
    require_source_trees(io, current, record)
    frozen: dict[str, Any] = {"writes": state.import_writes(io, writes), "artifacts": state.import_writes(io, artifacts or {}),
              "sources": capture_sources(io, sources or review.get("source_versions")), "result": result, "review": review}
    from .input_reads import values as input_values
    declared = input_values(record, {"input_reads": list(input_reads)})
    if declared:
        frozen["input_reads"] = [item.to_payload() for item in declared]
    if record.get("source_tree_origins"):
        frozen["source_tree_origins"] = record["source_tree_origins"]
    for name in preconditions.native_adoptions(record):
        if isinstance(writes[name], bytes):
            frozen["writes"][name]["mode"] = record["adoption_modes"][name]
    frozen = json.loads(json.dumps(json_safe(frozen), allow_nan=False))
    from .produced_sources import frozen_output

    source_baseline = state.head(io)
    assert source_baseline is not None
    for versions in frozen["sources"].values():
        for entry in versions.values():
            matched = frozen_output(io, entry, {**record, "draft": frozen})
            prior = source_baseline["sources"].get(entry["source_id"], {}).get(entry["version"], {})
            if entry.get("produced_resource") is not None and not matched and prior.get("produced_resource") != entry["produced_resource"]:
                raise ProjectConflict("A new produced source binding requires its exact same-command sealed output.")
    from .input_reads import require as require_inputs
    from .source_observations import observations

    require_inputs(io, source_baseline, record, observed=observations(record), frozen=frozen)
    seal(io, record, frozen)
    from .namespace_transfers import require as require_namespaces

    current = state.head(io)
    assert current is not None
    require_namespaces(io, current, record)
    record.update(phase="needs_review", result=frozen["result"], review=frozen["review"])
    state.save_command(io, record)
    return record


def seal(io: StoreIO, record: dict[str, Any], frozen: dict[str, Any]) -> None:
    decision_id = digest({"command_digest": record["command_digest"], "candidate": frozen})
    path = f"drafts/{digest(record['command_id'])}/{decision_id}.json"
    try:
        io.write(path, frozen, exclusive=True)
    except FileExistsError:
        if io.read(path) != frozen:
            raise ProjectConflict("The immutable candidate descriptor has conflicting content.") from None
    record.update(decision_id=decision_id, draft=frozen)


def decide(io: StoreIO, record: dict[str, Any], decision_id: str, accept: bool) -> dict[str, Any]:
    if type(accept) is not bool or record.get("decision_id") != decision_id:
        raise ProjectCommandConflict("The decision does not bind this exact frozen candidate.")
    if "accepted" in record:
        if record["accepted"] != accept:
            raise ProjectCommandConflict("A saved command decision cannot be reversed.")
        return record
    if record["phase"] != "needs_review":
        raise ProjectCommandConflict("This command has no undecided frozen candidate.")
    record.update(accepted=accept, phase="accepted" if accept else "rejected")
    state.save_command(io, record)
    return record


def public(io: StoreIO, record: dict[str, Any], *, create_views: bool = False,
           projection_pending: bool = False, checked: state.CheckedHead | None = None) -> dict[str, Any]:
    result = dict(record)
    checked = checked if checked is not None else state.checked_head(io)
    current = checked.current if checked is not None else None
    if checked is not None:
        checked.require(io, checked.current)
    committed = committed_outcome(io, current, record, checked=checked) if current else None
    if committed is not None and record.get("phase") != "complete":
        result["committed_generation"] = committed.generation["generation"]
        projection_pending = True
    if result["phase"] == "applying":
        result["phase"] = "unknown"
    result["generation_sequence"] = state.reachable(io, current, result["generation"], checked=checked)["sequence"] if current else None
    result["projection_pending"] = projection_pending
    if record.get("native_workspace") is not None:
        import sciplot_core.project_store.native_work as native_work

        result["native_workspace_path"] = str(native_work.verify(io, record)[0])
    draft = record.get("draft")
    if draft is not None:
        draft = state.sealed_draft(io, record)
        expected = record["decision_id"]
        for key, field in (("writes", "staged_paths"), ("artifacts", "artifact_paths")):
            paths = {}
            all_views = bool(draft[key])
            for logical, entry in draft[key].items():
                if entry is None:
                    continue
                components = ("drafts", digest(record["command_id"]), expected, key, *parts(logical))
                data = io.get(entry)
                view_exists = False
                try:
                    with directory(io.fd, components[:-1], create=create_views) as parent:
                        if create_views:
                            try:
                                install(parent, components[-1], data, mode=0o400, exclusive=True)
                            except FileExistsError:
                                pass
                        if read_file(parent, components[-1])[0] != data:
                            raise ProjectConflict("A sealed candidate view has conflicting bytes.")
                        view_exists = True
                except FileNotFoundError:
                    if create_views:
                        raise
                sealed = Path(*components) if view_exists else Path("objects", entry["sha256"][:2], entry["sha256"])
                all_views = all_views and view_exists
                paths[logical] = str(io.root / ".sciplot_store" / sealed)
            result[field] = paths
            result["artifact_root" if key == "artifacts" else "staged_root"] = (
                str(io.root / ".sciplot_store" / "drafts" / digest(record["command_id"]) / expected / key)
                if all_views else None)
    if checked is not None:
        checked.require(io, checked.current)
    return result


def verify_sources(io: StoreIO, sources: Mapping[str, Any], record: dict[str, Any] | None = None) -> None:
    from .source_observations import observations
    from .produced_sources import frozen_output

    selected = observations(record) if record is not None else {}
    local = io.read("local_sources.json") or {"versions": {}}
    for source_id, versions in sources.items():
        for version, entry in versions.items():
            if frozen_output(io, entry, record):
                continue
            if any(value.source_id == source_id and value.observed_sha256 == version for value in selected.values()):
                io.get(entry)  # The exact confined original resource was rechecked immediately before this call.
                continue
            imported = local["versions"].get(source_id, {}).get(version)
            if imported == entry["sha256"]:
                io.get(entry)
                continue
            path = Path(entry["locator"])
            try:
                parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    data, _mode = read_file(parent, path.name)
                finally:
                    os.close(parent)
            except OSError as exc:
                raise ProjectConflict("A selected original source is missing; use an explicit source/version binding.") from exc
            if sha(data) != version:
                raise ProjectConflict("A selected original source changed before head publication.")
