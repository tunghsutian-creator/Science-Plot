"""Select public feedback by complete modules and exact eligible nodes."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest


TARGETED_SCOPES = {"public-affected": "public-focused", "public-affected-native": "public-comprehensive"}


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
    scope = TARGETED_SCOPES.get(profile, profile)
    expected = set(manifest["scopes"]["public"])
    if scope != "public-all":
        expected.intersection_update(manifest["tiers"][scope.removeprefix("public-")])
    if targets is None:
        return expected
    if any(not filename.startswith("tests/") or filename not in source for filename in target_modules(targets)):
        raise ValueError("Affected selector must bind a current tracked test in its public tier.")
    return match_targets(expected, targets)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--sciplot-public-target", action="append", default=[],
                     help="Exact public feedback selectors admitted against complete collection of their test modules.")
