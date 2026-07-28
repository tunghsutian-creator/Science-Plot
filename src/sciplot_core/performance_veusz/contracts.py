"""Expose filtered performance geometry contracts for auditing."""

from __future__ import annotations

from typing import Any


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
