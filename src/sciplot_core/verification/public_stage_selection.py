"""Select exact public nodes and bind the public test scope."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest


TARGETED_SCOPES = {"public-affected": "public-focused", "public-affected-native": "public-comprehensive"}


COMPREHENSIVE_SHARDS = ("public-comprehensive-first", "public-comprehensive-second")


def comprehensive_shard(profile: str, nodes: set[str]) -> set[str]:
    """Split the canonical tier by exact ID, independently of collection order."""
    if profile not in COMPREHENSIVE_SHARDS:
        return nodes
    ordered = sorted(nodes)
    midpoint = len(ordered) // 2
    if not midpoint:
        raise ValueError("Comprehensive shards require two nonempty halves.")
    return set(ordered[:midpoint] if profile == COMPREHENSIVE_SHARDS[0] else ordered[midpoint:])


def profile_tier(profile: str) -> str:
    return "public-comprehensive" if profile in COMPREHENSIVE_SHARDS else TARGETED_SCOPES.get(profile, profile)


def target_modules(targets: Sequence[str]) -> frozenset[str]:
    return frozenset(target.split("::", 1)[0] for target in targets)


def match_targets(nodes: Iterable[str], targets: Sequence[str]) -> set[str]:
    """A function selector includes its parameters, not similarly named functions."""
    selected: set[str] = set()
    candidates: dict[str, list[str]] = {}
    for node in nodes:
        candidates.setdefault(node.split("::", 1)[0], []).append(node)
    for target in targets:
        module = target.split("::", 1)[0]
        matches = {node for node in candidates.get(module, ())
                   if node == target or node.startswith((target + "::", target + "["))}
        if not matches:
            raise ValueError("Affected selector must bind a current tracked test in its public tier.")
        selected.update(matches)
    return selected


def selected_public_nodes(manifest: dict[str, Any], source: dict[str, str], profile: str, targets: list[str] | None) -> set[str]:
    scope = profile_tier(profile)
    expected = set(manifest["scopes"]["public"])
    if scope != "public-all":
        expected.intersection_update(manifest["tiers"][scope.removeprefix("public-")])
    if targets is None:
        return comprehensive_shard(profile, expected)
    if any(not filename.startswith("tests/") or filename not in source for filename in target_modules(targets)):
        raise ValueError("Affected selector must bind a current tracked test in its public tier.")
    return match_targets(expected, targets)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--sciplot-public-target", action="append", default=[],
                     help="Exact public feedback selectors admitted against complete collection of their test modules.")


def validate_profile_selectors(profile: str, targets: list[str] | None) -> None:
    affected = profile in TARGETED_SCOPES
    if profile not in {"public-focused", "public-comprehensive", "public-all", *TARGETED_SCOPES, *COMPREHENSIVE_SHARDS}:
        raise ValueError("Only exact public profiles may execute in a source stage.")
    if affected != bool(targets) or (targets is not None and not affected):
        raise ValueError("Only an affected public profile requires explicit nonempty test selectors.")
