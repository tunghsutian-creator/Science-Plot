from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any, TypedDict, cast

from matplotlib.colors import is_color_like

from src.text_normalization import _clean_text

_VALID_MARKERS = frozenset({"none", "circle", "square", "triangle", "diamond", "x", "plus"})
_MARKER_SYMBOLS = {
    "none": "",
    "circle": "o",
    "square": "s",
    "triangle": "^",
    "diamond": "D",
    "x": "x",
    "plus": "+",
}
_Y_AXIS_TARGETS = {
    "primary": "y_primary",
    "y_primary": "y_primary",
    "secondary": "y_secondary",
    "y_secondary": "y_secondary",
}


class SeriesStylePayloadDict(TypedDict):
    series_id: str
    enabled: bool
    color: str | None
    line_width: float | None
    marker_size: float | None
    marker: str | None
    y_axis_target: str | None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = _clean_text(str(value))
    return cleaned or None


def _optional_color(value: object) -> str | None:
    color = _optional_text(value)
    if color is None:
        return None
    if not is_color_like(color):
        raise ValueError("`series_styles.color` must be a Matplotlib-compatible color.")
    return color


def _optional_line_width(value: object) -> float | None:
    if value is None:
        return None
    try:
        line_width = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError("`series_styles.line_width` must be a positive number.") from exc
    if not math.isfinite(line_width) or line_width <= 0:
        raise ValueError("`series_styles.line_width` must be a positive number.")
    return line_width


def _optional_marker_size(value: object) -> float | None:
    if value is None:
        return None
    try:
        marker_size = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError("`series_styles.marker_size` must be a non-negative number.") from exc
    if not math.isfinite(marker_size) or marker_size < 0:
        raise ValueError("`series_styles.marker_size` must be a non-negative number.")
    return marker_size


def _optional_marker(value: object) -> str | None:
    marker = _optional_text(value)
    if marker is None:
        return None
    normalized = marker.lower()
    if normalized not in _VALID_MARKERS:
        raise ValueError("`series_styles.marker` must be one of: " + ", ".join(sorted(_VALID_MARKERS)) + ".")
    return normalized


def _optional_y_axis_target(value: object) -> str | None:
    target = _optional_text(value)
    if target is None:
        return None
    normalized = target.lower()
    if normalized not in _Y_AXIS_TARGETS:
        raise ValueError("`series_styles.y_axis_target` must be one of: primary, secondary.")
    return _Y_AXIS_TARGETS[normalized]


def normalize_series_styles_payload(value: object) -> tuple[SeriesStylePayloadDict, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(value, Iterable):
        raise ValueError("`series_styles` must be a list of mappings.")

    styles_by_id: dict[str, SeriesStylePayloadDict] = {}
    order: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("`series_styles` entries must be mappings.")
        series_id = _optional_text(item.get("series_id"))
        if series_id is None:
            raise ValueError("`series_styles.series_id` is required.")
        if series_id not in styles_by_id:
            order.append(series_id)
        styles_by_id[series_id] = SeriesStylePayloadDict(
            series_id=series_id,
            enabled=bool(item.get("enabled", True)),
            color=_optional_color(item.get("color")),
            line_width=_optional_line_width(item.get("line_width")),
            marker_size=_optional_marker_size(item.get("marker_size")),
            marker=_optional_marker(item.get("marker")),
            y_axis_target=_optional_y_axis_target(item.get("y_axis_target")),
        )
    if not order:
        return None
    return tuple(styles_by_id[series_id] for series_id in order)


def series_style_by_id(
    value: tuple[Mapping[str, Any], ...] | None,
) -> dict[str, Mapping[str, Any]]:
    if value is None:
        return {}
    return {str(item.get("series_id")): item for item in value if item.get("series_id")}


def matplotlib_marker_symbol(marker: object) -> str | None:
    if marker is None:
        return None
    normalized = str(marker).strip().lower()
    return _MARKER_SYMBOLS.get(normalized, normalized)


__all__ = [
    "SeriesStylePayloadDict",
    "matplotlib_marker_symbol",
    "normalize_series_styles_payload",
    "series_style_by_id",
]
