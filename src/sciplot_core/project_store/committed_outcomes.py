"""Bind derived receipts and projection plans to the one committed history."""

from dataclasses import dataclass
from typing import Any

from .errors import ProjectConflict
from .io import StoreIO
from .namespace_transfers import installed_members
import sciplot_core.project_store.state as state


@dataclass(frozen=True)
class CommittedOutcome:
    outcome: dict[str, Any]
    generation: dict[str, Any]
    parent: dict[str, Any]
    files: tuple[str, ...]
    rewritten: frozenset[str]


def _descendant_writes(io: StoreIO, current: dict[str, Any], published: dict[str, Any]) -> frozenset[str]:
    """A later immutable author removes the older plan's right to install."""
    cursor, rewritten = current, set()
    while cursor["generation"] != published["generation"]:
        parent = state.generation(io, cursor["parent"])
        for outcome in cursor["commands"].values():
            if outcome["generation"] == cursor["generation"]:
                rewritten.update(outcome["write_set"])
        # Input observations also advance the immutable file witness without an
        # output install. They must not restore an older writer's preimage rights.
        rewritten.update(name for name in set(parent["files"]) | set(cursor["files"])
                         if parent["files"].get(name) != cursor["files"].get(name))
        rewritten.update(set(cursor.get("input_resources", [])) - set(parent.get("input_resources", [])))
        cursor = parent
    return frozenset(rewritten)


def require(io: StoreIO, current: dict[str, Any], record: dict[str, Any]) -> CommittedOutcome | None:
    """A mutable receipt may describe committed facts but cannot select them."""
    if (record.get("kind") != "sciplot_project_command" or record.get("version") != 1
            or record.get("project_id") != current["project_id"]
            or not isinstance(record.get("command_id"), str)
            or not isinstance(record.get("command_digest"), str)):
        raise ProjectConflict("A derived receipt must bind this project's exact command identity.")
    outcome = current["commands"].get(record["command_id"])
    if outcome is None:
        if record.get("phase") == "complete":
            raise ProjectConflict("A command cannot claim completion without a committed generation outcome.")
        return None
    bound = ("command_id", "command_digest", "project_id", "result", "review", "metadata", "read_set", "write_set")
    if (any(record.get(key) != outcome.get(key) for key in bound)
            or record.get("projected_reads", []) != outcome.get("projected_reads", [])
            or record.get("namespace_origins", {}) != outcome.get("namespace_origins", {})
            or record.get("source_tree_origins", {}) != outcome.get("source_tree_origins", {})
            or record.get("decision_id") != outcome.get("candidate_digest")
            or record.get("accepted") is not True
            or "pending_result" in record and record["pending_result"] != outcome.get("result")):
        raise ProjectConflict("A derived command receipt differs from its immutable generation outcome.")
    published = state.reachable(io, current, outcome["generation"])
    if (published["project_id"] != current["project_id"]
            or published["commands"].get(record["command_id"]) != outcome
            or published.get("parent") is None or outcome.get("phase") != "complete"):
        raise ProjectConflict("The command outcome is not bound to its committed publication generation.")
    parent = state.reachable(io, current, published["parent"])
    if record["command_id"] in parent["commands"]:
        raise ProjectConflict("The command outcome must identify its first immutable publication.")
    draft = state.sealed_draft(io, record)
    if (draft.get("result") != outcome["result"] or draft.get("review") != outcome.get("review", {})
            or draft.get("artifacts", {}) != outcome.get("artifacts", {})
            or not isinstance(outcome["write_set"], list)
            or outcome["write_set"] != sorted(set(outcome["write_set"]))
            or set(draft.get("writes", {})) != set(outcome["write_set"])):
        raise ProjectConflict("The committed outcome does not bind the exact sealed candidate.")
    for group in (draft["writes"], draft.get("artifacts", {})):
        for entry in group.values():
            if entry is not None:
                io.get(entry)
    for versions in draft.get("sources", {}).values():
        for entry in versions.values():
            io.get(entry)
    files = tuple(sorted(set(outcome["write_set"]) - installed_members(record)))
    if (record.get("install_generation") != published["generation"]
            or record.get("install_parent") != parent["generation"]
            or record.get("install_files") != list(files)):
        raise ProjectConflict("The derived installation hints differ from the committed projection plan.")
    if record.get("phase") == "complete":
        if record.get("generation") != published["generation"]:
            raise ProjectConflict("A completed receipt names another committed generation.")
    elif record.get("phase") != "accepted":
        raise ProjectConflict("Only the exact accepted candidate may await committed projection recovery.")
    # This is an admission/read marker, never an installation parent. Concurrent
    # unrelated publications may have advanced the actual parent since reserve.
    admitted = state.reachable(io, current, record["generation"])
    if admitted["sequence"] > published["sequence"]:
        raise ProjectConflict("A receipt's generation marker cannot come from a later command.")
    return CommittedOutcome(outcome, published, parent, files, _descendant_writes(io, current, published))
