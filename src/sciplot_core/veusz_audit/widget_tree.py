"""Index Veusz widgets and resolve the owner of nested settings."""

from __future__ import annotations

from typing import Any


def _owner_widget(path: str, widgets_by_path: dict[str, Any]) -> tuple[str, Any] | None:
    candidate = path.rstrip("/") or "/"
    while True:
        widget = widgets_by_path.get(candidate)
        if widget is not None:
            return candidate, widget
        if candidate == "/":
            return None
        parent = candidate.rsplit("/", maxsplit=1)[0]
        candidate = parent or "/"


def _iter_widgets(document: Any) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    widgets_by_path: dict[str, Any] = {}
    ordered: list[tuple[str, Any]] = []

    def collect(path: str, node: Any) -> None:
        widgets_by_path[path] = node
        ordered.append((path, node))

    document.walkNodes(collect, nodetypes=("widget",))
    return widgets_by_path, ordered
