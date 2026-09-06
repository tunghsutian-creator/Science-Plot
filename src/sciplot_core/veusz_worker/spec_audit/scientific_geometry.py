"""Check current scientific identity and geometry independently of typography."""

from __future__ import annotations

import math
from typing import Any

from sciplot_core.veusz_worker.widget_bindings import (
    _distance_is_positive,
    _numeric_sequence_equal,
)


def axis_matches_science(
    record: dict[str, Any], axis: dict[str, Any], *, name: str, spec: dict[str, Any]
) -> bool:
    bindings = record["bindings"]
    if not (
        record["name"] == name
        and str(bindings["label"]) == str(axis.get("label") or "")
        and str(bindings["direction"]) == ("vertical" if name == "y" else "horizontal")
        and str(bindings["mode"]) == str(axis.get("mode") or "numeric")
        and bool(bindings["log"]) is (axis.get("scale") == "log")
        and bool(bindings["Label/hide"])
        is (axis.get("hidden") is True or not axis.get("label"))
    ):
        return False
    values = [
        value
        for series in spec.get("series", [])
        for value in series.get(f"{name}_values", [])
    ]
    scalar = spec.get("scalar_field")
    if isinstance(scalar, dict):
        values.extend(scalar.get(f"{name}_values", []))
    try:
        current = _bounds(bindings)
        prepared = _bounds(axis)
    except (TypeError, ValueError):
        return False
    for value in values:
        if value is None or not math.isfinite(float(value)):
            continue
        numeric = float(value)
        # A viewport may expand or move within unused margins, but must not
        # newly omit a source observation that the prepared figure exposed.
        if prepared[0] <= numeric <= prepared[1] and not (
            current[0] <= numeric <= current[1]
        ):
            return False
    return True


def _bounds(values: dict[str, Any]) -> tuple[float, float]:
    bounds = []
    for name, default in (("min", -math.inf), ("max", math.inf)):
        value = values.get(name)
        if value is None or str(value).casefold() == "auto":
            bounds.append(default)
        else:
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("A current axis bound must be finite or Auto.")
            bounds.append(numeric)
    if bounds[0] == bounds[1]:
        raise ValueError("A current axis cannot have a zero range.")
    return min(bounds), max(bounds)


def label_matches_science(record: dict[str, Any], expected: dict[str, Any]) -> bool:
    bindings = record["bindings"]
    return (
        record["path"] == expected["path"]
        and record["name"] == expected["name"]
        and str(bindings["label"]) == str(expected["literal_label"])
        and not bool(bindings["Text/hide"])
        and str(bindings["xAxis"]) == expected["x_axis"]
        and str(bindings["yAxis"]) == expected["y_axis"]
    )


def shape_matches_science(
    record: dict[str, Any], expected: dict[str, Any], *, kind: str
) -> bool:
    """Retain data coordinates and statistical geometry, not colour or strokes."""

    bindings = record["bindings"]
    if record["path"] != expected["path"] or record["name"] != expected["name"]:
        return False
    if str(bindings["positioning"]) != expected["positioning"]:
        return False
    if kind != "rect" and (
        str(bindings["xAxis"]) != expected["x_axis"]
        or str(bindings["yAxis"]) != expected["y_axis"]
    ):
        return False
    fields = {
        "rect": ("xPos", "yPos", "width", "height"),
        "line": ("xPos", "yPos", "xPos2", "yPos2"),
        "polygon": ("xPos", "yPos"),
    }[kind]
    if any(not _numeric_sequence_equal(bindings[key], expected[key]) for key in fields):
        return False
    if kind == "line" and str(bindings["mode"]) != expected["mode"]:
        return False
    # A hidden statistical or reference mark cannot become a passing style edit.
    if kind == "rect":
        return bool(bindings["Fill/hide"]) is bool(expected["fill_hide"]) and (
            bool(expected["fill_hide"]) or float(bindings["Fill/transparency"]) < 100
        )
    return (
        not bool(bindings.get("hide"))
        and (bool(bindings["Line/hide"]) is bool(expected["line_hide"]))
        and (
            bool(expected["line_hide"])
            or (
                float(bindings["Line/transparency"]) < 100
                and _distance_is_positive(bindings["Line/width"])
            )
        )
    )


def colorbar_matches_science(
    record: dict[str, Any], *, scalar: dict[str, Any], visual: dict[str, Any]
) -> bool:
    bindings = record["bindings"]
    return (
        record["name"] == "field_colorbar"
        and str(bindings["label"]) == str(scalar.get("z_label") or "Z")
        and str(bindings["widgetName"]) == "field_image"
        and bindings["min"] == visual["z_min"]
        and bindings["max"] == visual["z_max"]
        and not bool(bindings["Label/hide"])
        and not bool(bindings["TickLabels/hide"])
    )
