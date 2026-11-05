"""Exact affected selection after the existing complete input-scope admission."""
from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest


def selected_public_nodes(manifest: dict[str, Any], source: dict[str, str], profile: str, targets: list[str] | None) -> set[str]:
    scope = "public-focused" if profile == "public-affected" else profile
    expected = set(manifest["scopes"]["public"])
    if scope != "public-all":
        expected.intersection_update(manifest["tiers"][scope.removeprefix("public-")])
    if targets is None:
        return expected
    selected: set[str] = set()
    for target in targets:
        filename = target.split("::", 1)[0]
        matches = {node for node in expected if node == target or node.startswith((target + "::", target + "["))}
        if not filename.startswith("tests/") or filename not in source or not matches:
            raise ValueError("Affected selector must bind a current tracked public focused test.")
        selected.update(matches)
    return selected


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--sciplot-public-target", action="append", default=[],
                     help="Exact public-focused selectors, applied after exhaustive scope validation.")


@pytest.hookimpl(wrapper=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> Generator[None, Any, Any]:
    # The existing conftest must first validate the complete actual manifest union.
    result = yield
    targets = config.getoption("sciplot_public_target")
    if targets:
        if config.getoption("input_scope") != "public-focused":
            raise pytest.UsageError("Affected selectors require the admitted public-focused scope.")
        retained: set[str] = set()
        for target in targets:
            matches = {item.nodeid for item in items if item.nodeid == target or item.nodeid.startswith((target + "::", target + "["))}
            if not matches:
                raise pytest.UsageError("An affected selector has no admitted public-focused node.")
            retained.update(matches)
        config.hook.pytest_deselected(items=[item for item in items if item.nodeid not in retained])
        items[:] = [item for item in items if item.nodeid in retained]
    return result
