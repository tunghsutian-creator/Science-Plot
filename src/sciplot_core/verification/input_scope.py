"""Exact reviewed input scope, orthogonal to focused/comprehensive test tiers."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

MANIFEST = Path(__file__).with_name("input_scope_manifest.json")
PROFILES = ("public-focused", "public-comprehensive", "public-all", "private-science")


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("kind") != "sciplot_test_input_scopes" or value.get("version") != 1:
        raise ValueError("Unknown input-scope manifest.")
    if set(value.get("scopes", {})) != {"public", "private"}:
        raise ValueError("Exactly public and private input scopes must be declared.")
    seen: set[str] = set()
    for scope in ("public", "private"):
        nodes = value["scopes"][scope]
        if not isinstance(nodes, list) or not nodes:
            raise ValueError(f"Empty or malformed {scope} scope.")
        for node in nodes:
            if not isinstance(node, str) or not node.startswith("tests/") or ".py::test_" not in node:
                raise ValueError("Invalid exact test node ID.")
            if node in seen:
                raise ValueError(f"Duplicate or overlapping scope: {node}")
            seen.add(node)
    tiers = value.get("tiers")
    if not isinstance(tiers, dict) or set(tiers) != {"focused", "comprehensive"}:
        raise ValueError("Both original lifecycle tiers must be declared.")
    tier_seen: set[str] = set()
    for nodes in tiers.values():
        if not isinstance(nodes, list) or len(nodes) != len(set(nodes)) or tier_seen.intersection(nodes):
            raise ValueError("Duplicate or intersecting lifecycle tiers.")
        tier_seen.update(nodes)
    if seen != tier_seen:
        raise ValueError("Input scopes and lifecycle tiers do not have the same exhaustive union.")
    responsibilities = value.get("private_failure_responsibilities")
    if not isinstance(responsibilities, list) or len(responsibilities) != 111:
        raise ValueError("The original 111 private-input failures need exact responsibility records.")
    mapped: set[str] = set()
    for row in responsibilities:
        if not isinstance(row, dict) or row.get("private_nodeid") not in value["scopes"]["private"]:
            raise ValueError("A failure responsibility is not a declared private node.")
        node = row["private_nodeid"]
        if node in mapped or not row.get("real_science_responsibility"):
            raise ValueError("Duplicate or unexplained real-science responsibility.")
        mapped.add(node)
        counterparts = row.get("public_counterparts")
        if not isinstance(counterparts, list) or not counterparts or not set(counterparts).issubset(value["scopes"]["public"]):
            raise ValueError(f"Missing exact public behavior counterparts: {node}")
        if row.get("disposition") not in {"behavior_and_private_science", "real_specific_only"} or not row.get("behavior_responsibility"):
            raise ValueError("Each responsibility needs an explicit behavior/science split.")
    if value.get("baseline_failure_nodeids_sha256") != hashlib.sha256("\n".join(sorted(mapped)).encode()).hexdigest():
        raise ValueError("Original failure responsibility membership drift.")
    return value


def select_scope(profile: str, *, manifest: dict[str, Any], collected: list[str],
                 tiers: dict[str, str], private_nodes: set[str]) -> list[str]:
    """Refuse unknown/stale/intersecting scope before selecting any test bodies."""
    if profile not in PROFILES:
        raise ValueError("Unknown named input scope.")
    if len(collected) != len(set(collected)):
        raise ValueError("Duplicate node IDs in fresh collection.")
    declared = set(manifest["scopes"]["public"]) | set(manifest["scopes"]["private"])
    actual = set(collected)
    unknown, stale = actual - declared, declared - actual
    if unknown or stale:
        raise ValueError(f"Input scope drift: unknown={sorted(unknown)[:8]}, stale={sorted(stale)[:8]}")
    if set(manifest["scopes"]["private"]) != private_nodes:
        raise ValueError("Private input classification differs from the dependency inventory.")
    for tier, nodes in manifest["tiers"].items():
        if any(tiers.get(node) != tier for node in nodes):
            raise ValueError("Lifecycle tier drift; input scope cannot reclassify lifecycle tiers.")
    scope = "private" if profile == "private-science" else "public"
    selected = set(manifest["scopes"][scope])
    if profile in {"public-focused", "public-comprehensive"}:
        selected.intersection_update(manifest["tiers"][profile.removeprefix("public-")])
    return [node for node in collected if node in selected]
