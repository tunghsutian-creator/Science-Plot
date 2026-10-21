"""Expose filtered performance geometry contracts for auditing."""

from __future__ import annotations

from typing import Any
from sciplot_core.performance_veusz.style import _literal_text


def performance_literal_text(spec: dict[str, Any], value: object) -> str:
    """Keep selected original identifiers literal in rendering and native audit."""
    performance = spec.get("performance_comparison")
    selected = isinstance(performance, dict) and "performance_selection" in performance
    return _literal_text(value, format_units=not selected)


def performance_polygon_contracts(spec: dict[str, Any]) -> list[dict[str, Any]]:
    performance = spec.get("performance_comparison")
    if not isinstance(performance, dict):
        return []
    return [
        dict(item) for item in performance.get("polygons", []) if isinstance(item, dict)
    ]


def performance_line_contracts(spec: dict[str, Any]) -> list[dict[str, Any]]:
    performance = spec.get("performance_comparison")
    if not isinstance(performance, dict):
        return []
    return [
        dict(item) for item in performance.get("lines", []) if isinstance(item, dict)
    ]


def performance_label_contracts(spec: dict[str, Any]) -> list[dict[str, Any]]:
    performance = spec.get("performance_comparison")
    if not isinstance(performance, dict):
        return []
    return [
        dict(item) for item in performance.get("labels", []) if isinstance(item, dict)
    ]
