"""Durable command admission and sealed candidate decisions in the one store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
from typing import Any

from .errors import ProjectCommandConflict, ProjectConflict, ProjectStoreError
from .io import StoreIO, digest, directory, install, parts, read_file, sha
from . import state


def projected_writes(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected = record.get("metadata", {}).get("projected_writes", [])
    if not isinstance(selected, list):
        raise ProjectStoreError("Projected writes must use the fixed domain descriptors.")
    reads = record.get("projected_reads", [])
    for item in selected:
        if not isinstance(item, dict) or set(item) != {"resource", "kind", "key", "sha256"} or item not in reads:
            raise ProjectStoreError("Each projected write must bind the identical admitted projected read.")
    return selected


def native_adoptions(record: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    import re

    values = record.get("metadata", {}).get("native_adoptions", [])
    if not values:
        return {}
    if record["metadata"].get("kind") != "native_import":
        raise ProjectStoreError("Only an explicit audited native import can adopt outside native bytes.")
    result = {}
    for item in values:
        if (not isinstance(item, dict) or set(item) != {"resource", "before_sha256", "observed_sha256", "audit_sha256"}
                or any(not isinstance(item[key], str) or not re.fullmatch(r"[0-9a-f]{64}", item[key])
                       for key in ("before_sha256", "observed_sha256", "audit_sha256"))
                or item["resource"] not in record["write_set"] or item["resource"] in result
                or Path(item["resource"]).suffix.casefold() != ".vsz"
                or record["read_set"].get(item["resource"]) != item["before_sha256"]):
            raise ProjectStoreError("A native adoption must exactly bind one guarded native resource and audit identity.")
        result[item["resource"]] = item
    return result


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
        "projected_reads": list(projected_reads), "metadata": metadata or {}, "result": {}, "review": {}}
    projected = {item["resource"] for item in projected_writes(record)}
    native_adoptions(record)
    for name in [*record["read_set"], *record["write_set"]]:
        parts(name)
        io.split(name)
    if any(name not in read_set and name not in projected for name in record["write_set"]):
        raise ProjectStoreError("Every full-resource write needs an exact before hash or absence read.")
    state.require_reads(io, current, record)
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
        path = Path(item["path"])
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            data, mode = read_file(parent, path.name)
        finally:
            os.close(parent)
        version = sha(data)
        if item.get("version") != version:
            raise ProjectConflict("The captured source differs from its explicit version.")
        entry = {**io.put(data), "mode": mode, "source_id": source_id,
                 "locator": str(path), "version": version}
        result.setdefault(source_id, {})[entry["version"]] = entry
    return result


def stage(io: StoreIO, record: dict[str, Any], *, writes: Mapping[str, bytes | Path | None],
          result: dict[str, Any], review: dict[str, Any], artifacts: Mapping[str, bytes | Path] | None,
          sources: Sequence[dict[str, Any]] | None) -> dict[str, Any]:
    if record["phase"] in {"needs_review", "accepted", "rejected", "complete"}:
        return record
    if record["phase"] not in {"reserved", "applying"}:
        raise ProjectCommandConflict("This command cannot produce another candidate.")
    if set(writes) != set(record["write_set"]):
        raise ProjectStoreError("The candidate must exactly cover the declared write set.")
    frozen = {"writes": state.import_writes(io, writes), "artifacts": state.import_writes(io, artifacts or {}),
              "sources": capture_sources(io, sources or review.get("source_versions")), "result": result, "review": review}
    seal(io, record, frozen)
    record.update(phase="needs_review", result=result, review=review)
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


def public(io: StoreIO, record: dict[str, Any], *, create_views: bool = False) -> dict[str, Any]:
    result = dict(record)
    current = state.head(io)
    outcome = current["commands"].get(record["command_id"]) if current else None
    if outcome is not None:
        bound = ("command_digest", "project_id", "generation", "result", "metadata", "read_set", "write_set")
        if (any(record.get(key) != outcome.get(key) for key in bound)
                or record.get("decision_id") != outcome.get("candidate_digest")):
            raise ProjectConflict("A derived command receipt differs from its immutable generation outcome.")
    elif record["phase"] == "complete":
        raise ProjectConflict("A command cannot claim completion without a committed generation outcome.")
    if result["phase"] == "applying":
        result["phase"] = "unknown"
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


def verify_sources(io: StoreIO, sources: Mapping[str, Any]) -> None:
    local = io.read("local_sources.json") or {"versions": {}}
    for source_id, versions in sources.items():
        for version, entry in versions.items():
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
