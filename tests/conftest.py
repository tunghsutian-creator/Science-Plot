from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Make the focused and comprehensive tiers exhaustive and disjoint."""
    focused = pytest.mark.focused
    for item in items:
        comprehensive_marker = item.get_closest_marker("comprehensive")
        focused_marker = item.get_closest_marker("focused")
        if comprehensive_marker is not None and focused_marker is not None:
            raise pytest.UsageError(
                f"{item.nodeid} cannot be both focused and comprehensive"
            )
        if comprehensive_marker is None and focused_marker is None:
            item.add_marker(focused)
