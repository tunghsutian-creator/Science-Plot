"""Exact affected selection after the existing complete input-scope admission."""
from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--sciplot-public-target", action="append", default=[],
                     help="Exact selectors in an admitted public tier, applied after exhaustive scope validation.")


@pytest.hookimpl(wrapper=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> Generator[None, Any, Any]:
    # The existing conftest must first validate the complete actual manifest union.
    result = yield
    targets = config.getoption("sciplot_public_target")
    if targets:
        if config.getoption("input_scope") not in {"public-focused", "public-comprehensive"}:
            raise pytest.UsageError("Affected selectors require an admitted focused or comprehensive public scope.")
        retained: set[str] = set()
        for target in targets:
            matches = {item.nodeid for item in items if item.nodeid == target or item.nodeid.startswith((target + "::", target + "["))}
            if not matches:
                raise pytest.UsageError("An affected selector has no admitted node in its public tier.")
            retained.update(matches)
        config.hook.pytest_deselected(items=[item for item in items if item.nodeid not in retained])
        items[:] = [item for item in items if item.nodeid in retained]
    return result
