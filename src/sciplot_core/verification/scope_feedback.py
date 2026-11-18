"""Admit only proven generated-public inventory deltas to affected feedback."""
import json
from pathlib import Path
import re
import subprocess
from typing import Any

_SCOPE_ROOT = "src/sciplot_core/verification/"
_SCOPE = _SCOPE_ROOT + "input_scope_manifest.json"
_INVENTORY = _SCOPE_ROOT + "private_corpus_inventory.json"
SCOPE_PATHS = frozenset({_SCOPE, _INVENTORY})
_AUDIT_DIGEST_FIELDS = {"nodeid_count", "nodeids_sha256", "test_sources_sha256", "test_source_count"}


def _without(value: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in fields}


def _read(root: Path, revision: str, path: str) -> dict[str, Any]:
    return json.loads(subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=root, timeout=10))


def _selected(node: str, targets: list[str]) -> bool:
    return any(node == name or node.startswith((name + "::", name + "[")) for name in targets)


def scope_delta_is_reviewed(root: Path, base: str, paths: set[str],
                            focused: list[str], comprehensive: list[str]) -> bool:
    """Existing responsibility, private sources, membership and tiers are immutable here."""
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        return False
    selectors = focused + comprehensive
    changed_tests = {path for path in paths if path.startswith("tests/") and path.endswith(".py")
                     and _selected(path, [name.split("::", 1)[0] for name in selectors])}
    if not changed_tests:
        return False
    try:
        old, new = (_read(root, revision, _SCOPE) for revision in (base, "HEAD"))
        old_audit, new_audit = (_read(root, revision, _INVENTORY) for revision in (base, "HEAD"))
        if (_without(old, {"scopes", "tiers"}) != _without(new, {"scopes", "tiers"})
                or set(old["scopes"]) != set(new["scopes"])
                or old["scopes"]["private"] != new["scopes"]["private"]
                or _without(old_audit, {"collection_audit"}) != _without(new_audit, {"collection_audit"})):
            return False
        prior, public = (set(value["scopes"]["public"]) for value in (old, new))
        added = public - prior
        if not prior <= public or set(old["tiers"]) != set(new["tiers"]):
            return False
        for tier, targets in (("focused", focused), ("comprehensive", comprehensive)):
            before, after = set(old["tiers"][tier]), set(new["tiers"][tier])
            if not before <= after or not after - before <= added:
                return False
            if any(node.split("::", 1)[0] not in changed_tests or not _selected(node, targets)
                   for node in after - before):
                return False
        old_review, new_review = (value["collection_audit"] for value in (old_audit, new_audit))
        allowed = _AUDIT_DIGEST_FIELDS | {"candidate_nodeids", "synthetic_candidates"}
        if _without(old_review, allowed) != _without(new_review, allowed):
            return False
        for field in ("candidate_nodeids", "synthetic_candidates"):
            previous, latest = old_review[field], new_review[field]
            if latest[:len(previous)] != previous:
                return False
            additions = latest[len(previous):]
            if any((entry if field == "candidate_nodeids" else entry["nodeid"]) not in added
                   for entry in additions):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return False
