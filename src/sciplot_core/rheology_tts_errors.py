"""Supplied symmetric Y uncertainties: validation, native binding and fidelity."""

from dataclasses import replace
import math

import numpy as np

from sciplot_core.policy import (
    CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LINE_WIDTH_PT,
)
from sciplot_core.studio_core.veusz_units import _pt


def supplied_error_values(raw: dict, y: list[float], yscale: str) -> tuple[float, ...]:
    """Accept supplied uncertainties without estimating or repairing any values."""
    if "error_values" not in raw:
        return ()
    values = raw["error_values"]
    if not isinstance(values, (list, tuple)) or len(values) != len(y):
        raise ValueError("error_values must have the same paired length as y.")
    if any(isinstance(value, bool) for value in values):
        raise ValueError(
            "error_values must be finite nonnegative numbers, not booleans."
        )
    errors = tuple(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0 for value in errors):
        raise ValueError(
            "error_values must be finite and nonnegative; no errors were removed."
        )
    endpoints = [
        value
        for yv, error in zip(y, errors, strict=True)
        for value in (yv - error, yv + error)
    ]
    if not all(math.isfinite(value) for value in endpoints):
        raise ValueError("Y error bar endpoints must be finite.")
    if yscale == "log" and min(endpoints) <= 0:
        raise ValueError(
            "Y error bars reach nonpositive coordinates on a logarithmic axis."
        )
    return errors


def axis_extent_series(series: list) -> list:
    """Pass error endpoints only to the shared axis-range solver, never to plots."""
    return [
        replace(
            item,
            x_values=item.x_values * 2,
            y_values=tuple(
                y - e for y, e in zip(item.y_values, item.error_values, strict=True)
            )
            + tuple(
                y + e for y, e in zip(item.y_values, item.error_values, strict=True)
            ),
        )
        if item.error_values
        else item
        for item in series
    ]


def bind_native_errors(interface, series: list[dict]) -> None:
    for item in series:
        if item.get("error_values"):
            interface.SetData(
                item["y_name"], item["y_values"], symerr=item["error_values"]
            )


def native_error_fields(item: dict) -> dict[str, tuple]:
    if not item.get("error_values"):
        return {}
    bar = item["kind"] == "bar"
    return {
        "errorstyle" if bar else "errorStyle": ("barends", "token"),
        "ErrorBarLine/hide": (False, "exact"),
        "ErrorBarLine/hideVert": (False, "exact"),
        "ErrorBarLine/hideHorz": (True, "exact"),
        "ErrorBarLine/color": (UNIFIED_FOREGROUND_COLOR, "color"),
        "ErrorBarLine/width": (UNIFIED_LINE_WIDTH_PT, "points"),
        "ErrorBarLine/style": ("solid", "token"),
        "ErrorBarLine/transparency": (0, "exact"),
        "ErrorBarLine/endsize": (
            2 * CATEGORICAL_ERROR_CAP_TO_BAR_RATIO if bar else 1.0,
            "number",
        ),
    }


def apply_native_errors(interface, item: dict) -> None:
    fields = native_error_fields(item)
    if not fields:
        return
    interface.To(item["name"])
    for name, (value, kind) in fields.items():
        interface.Set(name, _pt(value) if kind == "points" else value)
    interface.To("..")


def audit_native_errors(doc, item: dict) -> None:
    """Audit both expected and unexpected uncertainty channels on both axes."""
    for axis in ("x", "y"):
        name = item[f"{axis}_name"]
        dataset = doc.data[name]
        errors = item.get("error_values", []) if axis == "y" else []
        for channel in ("serr", "nerr", "perr"):
            actual = getattr(dataset, channel, None)
            expected = errors if errors and channel == "serr" else None
            if (actual is None) != (expected is None) or (
                expected is not None and not np.array_equal(actual, expected)
            ):
                raise ValueError(
                    f"Saved native uncertainty differs from supplied errors: {name}/{channel}"
                )
