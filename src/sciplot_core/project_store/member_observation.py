"""One checked generation selection, projection observation, and member read."""

from collections.abc import Sequence
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from .errors import ProjectConflict, ProjectStoreError
from .io import StoreIO, parts, sha
from .root_bindings import require as require_roots
from .state import CheckedHead, checked_head, reachable


@dataclass(frozen=True)
class ObservedMember:
    kind: Literal["file", "directory", "missing"]
    data: bytes | None = None


@dataclass(frozen=True)
class MemberObservation:
    # Canonical generations are distinct from optional physical observations.
    head: dict[str, Any]
    selected: dict[str, Any]
    members: dict[str, ObservedMember]
    projection: dict[str, Any] | None
    # Only admitted current members are observed: absent key = unobserved;
    # present key with None = observed physical absence.
    physical: dict[str, tuple[bytes, int] | None]


def _projection(io: StoreIO, current: dict[str, Any]) -> dict[str, Any]:
    require_roots(io, current)
    drift: dict[str, str | None] = {}
    metadata_drift: dict[str, str] = {}
    for name, entry in current["files"].items():
        try:
            physical = io.physical(name, owned=name not in current.get("input_resources", [])
                and name not in current.get("history_resources", []))
        except ProjectConflict as exc:
            drift[name] = None
            metadata_drift[name] = str(exc)
            continue
        actual = sha(physical[0]) if physical else None
        if actual != entry["sha256"] or physical is not None and physical[1] != entry["mode"]:
            drift[name] = actual
    return {**current, "projection_status": "conflict" if drift else "current",
            "outside_changes": drift, "outside_metadata": metadata_drift}


def observe(io: StoreIO, current: dict[str, Any], checked: CheckedHead, names: Sequence[str], *,
            generation: str | None, projection: bool, physical: Sequence[str]) -> MemberObservation:
    """Read finite members; an omitted projection is unobserved, never current.

    Admitted current physical members use their original owned file checks,
    independently of the selected immutable historical generation. Unregistered
    names have no physical result and confer no outside-file read authority.
    They support host-capability bootstrap without scanning unbound host roots.
    """
    checked.require(io, current)
    selected = reachable(io, current, generation, checked=checked) if generation else current
    if selected["project_id"] != current["project_id"]:
        raise ProjectStoreError("The logical resource is not a member of this generation.")
    requested = tuple(dict.fromkeys(names))
    if not set(physical).issubset(requested):
        raise ProjectStoreError("Physical observations must name explicitly requested members.")
    for name in requested:
        parts(name)
    with ExitStack() as proofs:
        epoch = io.validation_epoch
        observed_projection = _projection(io, current) if projection else None
        if io.validation_epoch != epoch:
            # A snapshot reports physical conflicts as data. The failed physical
            # validation has expired every old proof; retain that negative
            # observation only after freshly checking the same canonical head.
            fresh = checked_head(io)
            if fresh is not None:
                proofs.callback(fresh.close)
            if fresh is None or fresh.current != current:
                raise ProjectConflict("The canonical head changed across its projection observation boundary.")
            checked, current = fresh, fresh.current
            selected = reachable(io, current, generation, checked=checked) if generation else current
        members = {}
        for name in requested:
            entry = selected["files"].get(name)
            if entry is not None:
                members[name] = ObservedMember("file", io.get(entry))
            else:
                kind: Literal["directory", "missing"] = (
                    "directory" if any(member.startswith(name + "/") for member in selected["files"]) else "missing")
                members[name] = ObservedMember(kind)
        host = {name: io.physical(name) for name in physical if name in current["files"]}
        checked.require(io, current)
        if io._checked_window is not None:
            current, selected, observed_projection = deepcopy((current, selected, observed_projection))
        return MemberObservation(current, selected, members, observed_projection, host)
