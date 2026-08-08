"""Record and verify whether final axis bounds hide plotted coordinates."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


AXIS_DATA_VISIBILITY_KIND = "sciplot_axis_data_visibility"
AXIS_DATA_VISIBILITY_VERSION = 1


def axis_data_visibility_payload(
    *,
    series_specs: object,
    axes: object,
    render_options: object,
) -> dict[str, Any]:
    """Build deterministic configured-versus-effective axis visibility evidence."""

    series = _mapping_sequence(series_specs)
    axis_records = axes if isinstance(axes, Mapping) else {}
    options = render_options if isinstance(render_options, Mapping) else {}
    records = {
        axis: _axis_visibility_record(
            values=[
                value
                for series_record in series
                for value in _finite_values(series_record.get(f"{axis}_values"))
            ],
            axis_record=(
                axis_records.get(axis)
                if isinstance(axis_records.get(axis), Mapping)
                else {}
            ),
            configured_min=_finite_float(options.get(f"{axis}_min")),
            configured_max=_finite_float(options.get(f"{axis}_max")),
        )
        for axis in ("x", "y")
    }
    clipped_count = sum(
        int(record["clipped_coordinate_count"]) for record in records.values()
    )
    finite_count = sum(
        int(record["finite_coordinate_count"]) for record in records.values()
    )
    return {
        "kind": AXIS_DATA_VISIBILITY_KIND,
        "version": AXIS_DATA_VISIBILITY_VERSION,
        "status": (
            "clipped"
            if clipped_count
            else "all_finite_coordinates_visible"
            if finite_count
            else "no_finite_coordinates"
        ),
        "finite_coordinate_count": finite_count,
        "clipped_coordinate_count": clipped_count,
        "axes": records,
    }


def validate_axis_data_visibility(spec: Mapping[str, Any]) -> None:
    """Recompute the closed evidence from the same spec axes and series."""

    actual = spec.get("axis_data_visibility")
    ordinary_contract_present = "series_encoding_contract" in spec
    if actual is None and not ordinary_contract_present:
        return
    if not isinstance(actual, Mapping):
        raise ValueError("Veusz axis data visibility contract is missing or invalid.")
    expected = axis_data_visibility_payload(
        series_specs=spec.get("series"),
        axes=spec.get("axes"),
        render_options=spec.get("render_options"),
    )
    if dict(actual) != expected:
        raise ValueError(
            "Veusz axis data visibility evidence does not match its axes and data."
        )


def _axis_visibility_record(
    *,
    values: list[float],
    axis_record: Mapping[str, Any],
    configured_min: float | None,
    configured_max: float | None,
) -> dict[str, Any]:
    effective_min = _finite_float(axis_record.get("min"))
    effective_max = _finite_float(axis_record.get("max"))
    effective_low, effective_high = _ordered_bounds(effective_min, effective_max)
    below_effective = (
        sum(value < effective_low for value in values)
        if effective_low is not None
        else 0
    )
    above_effective = (
        sum(value > effective_high for value in values)
        if effective_high is not None
        else 0
    )
    below_configured = (
        sum(value < configured_min for value in values)
        if configured_min is not None
        else 0
    )
    above_configured = (
        sum(value > configured_max for value in values)
        if configured_max is not None
        else 0
    )
    return {
        "finite_coordinate_count": len(values),
        "data_min": min(values) if values else None,
        "data_max": max(values) if values else None,
        "configured_min": configured_min,
        "configured_max": configured_max,
        "effective_min": effective_min,
        "effective_max": effective_max,
        "below_configured_min_count": below_configured,
        "above_configured_max_count": above_configured,
        "below_effective_min_count": below_effective,
        "above_effective_max_count": above_effective,
        "clipped_coordinate_count": below_effective + above_effective,
        "configured_min_relaxed": bool(
            configured_min is not None
            and effective_low is not None
            and effective_low < configured_min
            and below_configured
        ),
        "configured_max_relaxed": bool(
            configured_max is not None
            and effective_high is not None
            and effective_high > configured_max
            and above_configured
        ),
    }


def _mapping_sequence(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _finite_values(value: object) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [number for item in value if (number := _finite_float(item)) is not None]


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _ordered_bounds(
    minimum: float | None,
    maximum: float | None,
) -> tuple[float | None, float | None]:
    if minimum is None or maximum is None:
        return minimum, maximum
    return (minimum, maximum) if minimum <= maximum else (maximum, minimum)


__all__ = [
    "AXIS_DATA_VISIBILITY_KIND",
    "AXIS_DATA_VISIBILITY_VERSION",
    "axis_data_visibility_payload",
    "validate_axis_data_visibility",
]
