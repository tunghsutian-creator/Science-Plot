"""Verify stroke widths from exact-current Veusz audit evidence."""

from __future__ import annotations

from typing import Any


def _vsz_stroke_report(
    audit: dict[str, Any] | None, profile: dict[str, Any]
) -> dict[str, Any]:
    stroke_profile = (
        profile.get("strokes") if isinstance(profile.get("strokes"), dict) else {}
    )
    minimum = float(stroke_profile.get("minimum_width_pt") or 0.0)
    maximum = float(stroke_profile.get("maximum_width_pt") or float("inf"))
    documents = audit.get("documents", []) if isinstance(audit, dict) else []
    items = [
        {**item, "document": document.get("path")}
        for document in documents
        if isinstance(document, dict)
        for item in document.get("stroke_inventory", {}).get("items", [])
        if isinstance(item, dict) and item.get("active")
    ]
    unsupported = [
        {**item, "document": document.get("path")}
        for document in documents
        if isinstance(document, dict)
        for item in document.get("stroke_inventory", {}).get("unsupported", [])
        if isinstance(item, dict)
    ]
    out_of_range = [
        item
        for item in items
        if item.get("width_pt") is None
        or float(item["width_pt"]) < minimum - 0.01
        or float(item["width_pt"]) > maximum + 0.01
    ]
    coverage_complete = (
        bool(documents)
        and not unsupported
        and all(item.get("width_pt") is not None for item in items)
    )
    return {
        "available": bool(documents),
        "coverage_complete": coverage_complete,
        "passed": coverage_complete and not out_of_range,
        "expected": {"minimum_pt": minimum, "maximum_pt": maximum},
        "active_count": len(items),
        "items": items,
        "unsupported": unsupported,
        "out_of_range": out_of_range,
        "evidence_model": "PDF strokes plus resolved active line settings from the exact current VSZ",
    }
