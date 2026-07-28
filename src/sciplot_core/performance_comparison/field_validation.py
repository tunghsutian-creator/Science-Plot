"""Validate consistent metric and material metadata fields."""

from __future__ import annotations

import math
import re
import pandas as pd
from sciplot_core.performance_comparison.models import (
    PerformanceComparisonError,
)

from sciplot_core.performance_comparison.source_values import (
    _ROLE_ALIASES,
    _DIRECTION_ALIASES,
    _token,
    _text,
    _optional_float,
)


def _unique_text(
    frame: pd.DataFrame,
    column: object | None,
    *,
    field: str,
    owner: str,
    default: str = "",
) -> str:
    if column is None:
        return default
    values = list(
        dict.fromkeys(_text(value) for value in frame[column] if _text(value))
    )
    if len(values) > 1:
        raise PerformanceComparisonError(
            "performance_metadata_conflict",
            f"{owner} has conflicting {field} values: {values}.",
        )
    return values[0] if values else default


def _unique_float(
    frame: pd.DataFrame,
    column: object | None,
    *,
    field: str,
    owner: str,
) -> float | None:
    if column is None:
        return None
    values: list[float] = []
    for index, value in frame[column].items():
        parsed = _optional_float(
            value,
            field=field,
            row_number=int(index) + 2,
        )
        if parsed is not None and not any(
            math.isclose(parsed, item) for item in values
        ):
            values.append(parsed)
    if len(values) > 1:
        raise PerformanceComparisonError(
            "performance_metadata_conflict",
            f"{owner} has conflicting {field} values: {values}.",
        )
    return values[0] if values else None


def _unique_bool(
    frame: pd.DataFrame,
    column: object | None,
    *,
    field: str,
    owner: str,
    default: bool,
) -> bool:
    if column is None:
        return default
    values: list[bool] = []
    true_tokens = {
        "true",
        "yes",
        "y",
        "include",
        "included",
        "是",
        "包含",
        "纳入",
    }
    false_tokens = {
        "false",
        "no",
        "n",
        "exclude",
        "excluded",
        "否",
        "不包含",
        "不纳入",
    }
    for index, value in frame[column].items():
        text = _text(value)
        if not text:
            continue
        parsed: bool | None = None
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = math.nan
        if math.isfinite(number) and math.isclose(number, 1.0):
            parsed = True
        elif math.isfinite(number) and math.isclose(number, 0.0):
            parsed = False
        else:
            token = _token(value)
            if token in true_tokens:
                parsed = True
            elif token in false_tokens:
                parsed = False
        if parsed is None:
            raise PerformanceComparisonError(
                "performance_envelope_include_invalid",
                f"Row {int(index) + 2}: {field} must be true/false, "
                "yes/no, include/exclude, or 1/0.",
            )
        if parsed not in values:
            values.append(parsed)
    if len(values) > 1:
        raise PerformanceComparisonError(
            "performance_metadata_conflict",
            f"{owner} has conflicting {field} values: {values}.",
        )
    return values[0] if values else default


def _normalized_role(value: object, *, row_number: int) -> str:
    role = _ROLE_ALIASES.get(_token(value))
    if role is None:
        raise PerformanceComparisonError(
            "performance_role_invalid",
            f"Row {row_number}: Role must identify sample/this work or "
            "reference/literature.",
        )
    return role


def _normalized_direction(value: str, *, metric_id: str) -> str | None:
    if not value:
        return None
    direction = _DIRECTION_ALIASES.get(_token(value))
    if direction is None:
        raise PerformanceComparisonError(
            "performance_direction_invalid",
            f"Metric {metric_id!r}: Direction must be higher or lower.",
        )
    return direction


def _normalized_scatter_axis(value: str, *, metric_id: str) -> str | None:
    if not value:
        return None
    axis = _token(value)
    if axis in {"x", "横轴"}:
        return "x"
    if axis in {"y", "纵轴"}:
        return "y"
    raise PerformanceComparisonError(
        "performance_scatter_axis_invalid",
        f"Metric {metric_id!r}: ScatterAxis must be x, y, or blank.",
    )


def _normalized_marker(value: str, *, material_id: str) -> str | None:
    if not value:
        return None
    marker = value.strip().casefold().replace("_", "")
    aliases = {
        "triangleup": "triangle",
        "triangle": "triangle",
        "triangledown": "triangledown",
        "circle": "circle",
        "square": "square",
        "diamond": "diamond",
        "pentagon": "pentagon",
        "hexagon": "hexagon",
        "star": "star",
        "cross": "cross",
        "plus": "plus",
        "triangleleft": "triangleleft",
        "triangleright": "triangleright",
        "octogon": "octogon",
        "octagon": "octogon",
        "ellipsehorz": "ellipsehorz",
        "ellipsehorizontal": "ellipsehorz",
        "ellipsevert": "ellipsevert",
        "ellipsevertical": "ellipsevert",
        "star4": "star4",
    }
    normalized = aliases.get(marker)
    if normalized is None:
        raise PerformanceComparisonError(
            "performance_marker_invalid",
            f"Material {material_id!r}: unsupported marker {value!r}.",
        )
    return normalized


def _normalized_marker_fill_color(
    value: str,
    *,
    material_id: str,
) -> str | None:
    if not value:
        return None
    color = value.strip().upper()
    if re.fullmatch(r"#[0-9A-F]{6}", color) is None:
        raise PerformanceComparisonError(
            "performance_marker_fill_color_invalid",
            f"Material {material_id!r}: MarkerFillColor must be a "
            "#RRGGBB hexadecimal color.",
        )
    return color


def _normalized_marker_line_color(
    value: str,
    *,
    material_id: str,
) -> str | None:
    if not value:
        return None
    color = value.strip().upper()
    if re.fullmatch(r"#[0-9A-F]{6}", color) is None:
        raise PerformanceComparisonError(
            "performance_marker_line_color_invalid",
            f"Material {material_id!r}: MarkerLineColor must be a "
            "#RRGGBB hexadecimal color.",
        )
    return color
