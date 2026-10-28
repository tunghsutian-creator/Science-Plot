"""Closed read/write admission and exact native import guards."""
from __future__ import annotations
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO, sha
import sciplot_core.project_store.state as state
from .membership import require_memberships
from .source_observations import observations, require_bindings
from .root_bindings import require as require_roots
from .namespace_transfers import require as require_namespaces


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


def require_reads(io: StoreIO, current: Mapping[str, Any], record: Mapping[str, Any]) -> None:
    from .errors import ProjectRecoveryRequired
    from .source_trees import require as require_source_trees

    require_source_trees(io, dict(current), dict(record))
    namespaces = require_namespaces(io, dict(current), dict(record))
    require_roots(io, dict(current), dict(record), exemptions=namespaces.root_exemptions)
    adoptions = native_adoptions(record)
    sources = observations(record)
    baseline = state.reachable(io, dict(current), record["expected_generation"])
    if baseline["project_id"] != current["project_id"]:
        raise ProjectConflict("The expected generation belongs to another project.")
    from .generated_outputs import require as require_missing
    missing = require_missing(io, dict(current), dict(record))
    require_memberships(io, baseline, dict(current), dict(record), observed=namespaces.memberships,
                        missing=frozenset(missing))
    require_bindings(baseline, record)
    from .input_reads import require as require_inputs
    require_inputs(io, current, record, observed=sources)
    if set(record["write_set"]) & set(current.get("input_resources", [])):
        raise ProjectConflict("An observed original input cannot become a materialized output write.")
    if set(record["write_set"]) & set(current.get("history_resources", [])):
        raise ProjectConflict("Read-only semantic history cannot become an active output write.")
    if any(name.startswith(prefix + "/") for prefix in current.get("retired_namespace_prefixes", []) for name in record["write_set"]):
        raise ProjectConflict("A retired semantic namespace cannot acquire another active writer.")
    for name, expected in record["read_set"].items():
        old = baseline["files"].get(name)
        latest = current["files"].get(name)
        if expected != (old["sha256"] if old else None) or expected != (latest["sha256"] if latest else None):
            raise ProjectConflict(f"A declared project read changed: {name}")
        if old is not None and latest is not None and old["mode"] != latest["mode"]:
            raise ProjectConflict(f"A declared project resource changed permission mode: {name}")
        physical = io.physical(name, owned=name not in sources and name not in namespaces.physical
            and name not in current.get("input_resources", []) and name not in current.get("history_resources", []))
        actual = sha(physical[0]) if physical else None
        namespace_observation = namespaces.physical.get(name)
        observed = None if name in missing else (namespace_observation["sha256"] if namespace_observation else None) if name in namespaces.physical else (
            adoptions[name]["observed_sha256"] if name in adoptions
                    else sources[name].observed_sha256 if name in sources else expected)
        if actual != observed:
            raise ProjectConflict(f"Outside bytes changed a declared project read: {name}")
        expected_mode = (namespace_observation["mode"] if namespace_observation else None) if name in namespaces.physical else (
                         record.get("adoption_modes", {}).get(name) if name in adoptions
                         else record.get("source_adoption_modes", {}).get(name) if name in sources
                         else old["mode"] if old else None)
        if physical is not None and expected_mode is not None and physical[1] != expected_mode:
            raise ProjectConflict(f"Outside permissions changed a declared project read: {name}")
    projected = record.get("projected_reads", [])
    if projected:
        from sciplot_core.project_commands.read_projections import projection_digest

        for item in projected:
            name = item["resource"]
            before = baseline["files"].get(name)
            after = current["files"].get(name)
            if before is None or after is None:
                raise ProjectConflict("A projected read resource is missing.")
            physical = io.physical(name)
            if (physical is None or sha(physical[0]) != after["sha256"] or physical[1] != after["mode"]
                    or before["mode"] != after["mode"]):
                raise ProjectRecoveryRequired("A projected resource has unregistered outside bytes.")
            for entry in (before, after):
                if projection_digest(io.get(entry), kind=item["kind"], key=item["key"]) != item["sha256"]:
                    raise ProjectConflict("The selected project membership or source projection changed.")
