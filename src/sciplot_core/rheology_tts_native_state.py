"""Compare native state outside an explicit, closed display-field delta."""

from __future__ import annotations

from io import StringIO
from typing import Any


def native_state(document: Any, excluded: set[str]) -> dict[str, Any]:
    """Retain references, widget order, custom definitions and dataset tags."""
    settings, widgets = {}, []

    def collect(path: str, node: Any) -> None:
        if node.nodetype == "widget":
            widgets.append((path, node.typename, tuple(node.childnames)))
        elif path not in excluded:
            settings[path] = node.saveText(True)

    document.walkNodes(collect, nodetypes=("widget", "setting"))
    custom, tags = StringIO(), StringIO()
    document.evaluate.saveCustomDefinitions(custom)
    document.saveDatasetTags(tags)
    return {"settings": settings, "widgets": widgets, "custom": custom.getvalue(),
            "dataset_tags": tags.getvalue(), "compatlevel": document.compatlevel}
