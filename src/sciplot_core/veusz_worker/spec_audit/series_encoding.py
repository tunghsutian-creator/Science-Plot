"""Audit request-owned XY visual channels against an exact-current VSZ."""

from __future__ import annotations

from typing import Any

from sciplot_core.studio_core.series_encoding_contract import (
    series_encoding_from_spec,
)
from sciplot_core.veusz_worker.spec_audit.model import SpecAuditInventory


_ENCODING_FIELD_BINDINGS = {
    "line.color": ("line", "color", "PlotLine/color", "color"),
    "line.style": ("line", "style", "PlotLine/style", "token"),
    "marker.shape": ("marker", "shape", "marker", "token"),
    "marker.fill_color": ("marker", "fill_color", "MarkerFill/color", "color"),
    "marker.line_color": ("marker", "line_color", "MarkerLine/color", "color"),
}


def _normalized_color(value: object) -> str:
    """Resolve Veusz/Qt named and hexadecimal colours to one RGB token."""

    from PyQt6.QtGui import QColor

    color = QColor(str(value or "").strip())
    if not color.isValid():
        return str(value or "").strip().casefold()
    return color.name().casefold()


def _encoding_value_equal(actual: object, expected: object, *, kind: str) -> bool:
    if kind == "color":
        return _normalized_color(actual) == _normalized_color(expected)
    return (
        str(actual or "").strip().casefold() == str(expected or "").strip().casefold()
    )


def audit_series_encoding(
    inventory: SpecAuditInventory,
    *,
    raw_series: dict[str, Any],
    matching_xy: dict[str, Any],
    style: dict[str, Any],
) -> None:
    """Check every request-owned visual channel against the loaded VSZ."""

    encoding = series_encoding_from_spec(raw_series, style=style)
    request_bound_fields = [str(value) for value in encoding["request_bound_fields"]]
    actual_fields: dict[str, Any] = {}
    for field_name, (
        group,
        key,
        binding_name,
        comparison_kind,
    ) in _ENCODING_FIELD_BINDINGS.items():
        expected = encoding[group][key]
        actual = matching_xy["bindings"].get(binding_name)
        actual_fields[field_name] = actual
        if field_name not in request_bound_fields:
            continue
        if not _encoding_value_equal(actual, expected, kind=comparison_kind):
            name = str(raw_series.get("name") or "")
            raise ValueError(
                f"Exact-current Veusz series {name!r} request-bound encoding "
                f"{field_name!r} is {actual!r}, expected {expected!r}."
            )
    inventory.series_encoding_evidence.append(
        {
            "series_name": str(raw_series.get("name") or ""),
            "series_label": str(raw_series.get("label") or ""),
            "widget_path": str(matching_xy.get("path") or ""),
            "request_bound_fields": request_bound_fields,
            "expected": encoding,
            "actual": actual_fields,
        }
    )


__all__ = ["audit_series_encoding"]
