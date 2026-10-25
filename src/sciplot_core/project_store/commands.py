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
from .root_bindings import identities
import sciplot_core.project_store.state as state
import sciplot_core.project_store.preconditions as preconditions


def reserve(io: StoreIO, current: dict[str, Any], command_id: str, command_digest: str, *,
            expected_generation: str | None, read_set: Mapping[str, str | None], write_set: Sequence[str],
            metadata: dict[str, Any] | None, projected_reads: Sequence[dict[str, Any]]) -> dict[str, Any]:
    existing = state.command(io, command_id, command_digest)
    if existing is not None:
        return existing
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
                                    tuple(item.get("aliases", ())), item.get("mode", 0o600))
            if item.get("size", len(source.data)) != len(source.data):
                raise ProjectConflict("The prepared source size differs from its exact bytes.")
            entry = {**io.put(source.data), "source_id": source_id, "locator": source.locator,
                     "version": source.version, "mode": source.mode}
            if prior is not None:
                if any(prior.get(key) != entry[key] for key in entry):
                    raise ProjectConflict("A prepared source conflicts with the existing immutable source version.")
                entry = dict(prior)
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
            result.setdefault(source_id, {})[version] = dict(prior)
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
        aliases = sorted(set(entry.get("aliases", [])) | set(item.get("aliases", [])))
        if aliases:
            entry["aliases"] = aliases
        result.setdefault(source_id, {})[entry["version"]] = entry
    return result


def stage(io: StoreIO, record: dict[str, Any], *, writes: Mapping[str, bytes | Path | PreparedFile | None],
          result: dict[str, Any], review: dict[str, Any], artifacts: Mapping[str, bytes | Path | PreparedFile] | None,
          sources: Sequence[dict[str, Any]] | None) -> dict[str, Any]:
    if record["phase"] in {"needs_review", "accepted", "rejected", "complete"}:
        return record
    if record["phase"] not in {"reserved", "applying"}:
        raise ProjectCommandConflict("This command cannot produce another candidate.")
    if set(writes) != set(record["write_set"]):
        raise ProjectStoreError("The candidate must exactly cover the declared write set.")
    frozen = {"writes": state.import_writes(io, writes), "artifacts": state.import_writes(io, artifacts or {}),
              "sources": capture_sources(io, sources or review.get("source_versions")), "result": result, "review": review}
    for name in preconditions.native_adoptions(record):
        if isinstance(writes[name], bytes):
            frozen["writes"][name]["mode"] = record["adoption_modes"][name]
    frozen = json.loads(json.dumps(json_safe(frozen), allow_nan=False))
    seal(io, record, frozen)
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
           projection_pending: bool = False) -> dict[str, Any]:
    result = dict(record)
    current = state.head(io)
    outcome = current["commands"].get(record["command_id"]) if current else None
    if outcome is not None:
        own_pending = record.get("phase") != "complete" and record.get("install_generation") == outcome["generation"]
        bound = ("command_digest", "project_id", "result", "metadata", "read_set", "write_set")
        if (any(record.get(key) != outcome.get(key) for key in bound)
                or not own_pending and record.get("generation") != outcome["generation"]
                or record.get("decision_id") != outcome.get("candidate_digest")):
            raise ProjectConflict("A derived command receipt differs from its immutable generation outcome.")
        if own_pending:
            result["committed_generation"] = outcome["generation"]
            projection_pending = True
    elif record["phase"] == "complete":
        raise ProjectConflict("A command cannot claim completion without a committed generation outcome.")
    if result["phase"] == "applying":
        result["phase"] = "unknown"
    result["generation_sequence"] = state.reachable(io, current, result["generation"])["sequence"] if current else None
    result["projection_pending"] = projection_pending
    if record.get("native_workspace") is not None:
        import sciplot_core.project_store.native_work as native_work

        result["native_workspace_path"] = str(native_work.verify(io, record)[0])
    draft = record.get("draft")
    if draft is not None:
        expected = digest({"command_digest": record["command_digest"], "candidate": draft})
        frozen = io.read(f"drafts/{digest(record['command_id'])}/{expected}.json")
        if expected != record.get("decision_id") or frozen != draft:
            raise ProjectConflict("The sealed command candidate changed.")
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
    return result


def verify_sources(io: StoreIO, sources: Mapping[str, Any], record: dict[str, Any] | None = None) -> None:
    from .source_observations import observations

    selected = observations(record) if record is not None else {}
    local = io.read("local_sources.json") or {"versions": {}}
    for source_id, versions in sources.items():
        for version, entry in versions.items():
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
