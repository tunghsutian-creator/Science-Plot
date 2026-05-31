from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any, TypedDict, cast

from src.rendering.series_styles import _optional_y_axis_target
from src.text_normalization import _clean_text


class SeriesOffsetPayloadDict(TypedDict):
    series_id: str
    enabled: bool
    x_offset: float
    y_offset: float
    y_axis_target: str | None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = _clean_text(str(value))
    return cleaned or None


def _finite_float(value: object, *, field_name: str) -> float:
    try:
        resolved = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"`series_offsets.{field_name}` must be a finite number.") from exc
    if not math.isfinite(resolved):
        raise ValueError(f"`series_offsets.{field_name}` must be a finite number.")
    return resolved


def normalize_series_offsets_payload(value: object) -> tuple[SeriesOffsetPayloadDict, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(value, Iterable):
        raise ValueError("`series_offsets` must be a list of mappings.")

    offsets_by_id: dict[str, SeriesOffsetPayloadDict] = {}
    order: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("`series_offsets` entries must be mappings.")
        series_id = _optional_text(item.get("series_id"))
        if series_id is None:
            raise ValueError("`series_offsets.series_id` is required.")
        if series_id not in offsets_by_id:
            order.append(series_id)
        offsets_by_id[series_id] = SeriesOffsetPayloadDict(
            series_id=series_id,
            enabled=bool(item.get("enabled", True)),
            x_offset=_finite_float(item.get("x_offset", 0.0), field_name="x_offset"),
            y_offset=_finite_float(item.get("y_offset", 0.0), field_name="y_offset"),
            y_axis_target=_optional_y_axis_target(item.get("y_axis_target")),
        )
    if not order:
        return None
    return tuple(offsets_by_id[series_id] for series_id in order)


def series_offset_by_id(
    value: tuple[Mapping[str, Any], ...] | None,
) -> dict[str, Mapping[str, Any]]:
    if value is None:
        return {}
    return {str(item.get("series_id")): item for item in value if item.get("series_id")}


__all__ = [
    "SeriesOffsetPayloadDict",
    "normalize_series_offsets_payload",
    "series_offset_by_id",
]
