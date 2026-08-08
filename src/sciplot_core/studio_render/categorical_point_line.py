"""Bind source-provided sample labels to equally spaced point-line positions."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

import pandas as pd

from sciplot_core.studio_render.categorical_values import _clean_studio_cell
from sciplot_core.studio_render.models import (
    CATEGORICAL_POINT_LINE_KIND,
    StudioPreparationBlocked,
    StudioSeries,
)


_CATEGORY_COLUMN_ALIASES = {"sample", "samples", "specimen", "category"}


def categorical_point_line_axis_from_frame(
    frame: pd.DataFrame,
    *,
    row_indices: Iterable[Any],
    x_column: Any,
) -> tuple[tuple[str, ...], tuple[float, ...]] | None:
    """Return ordered source labels and numeric positions for one xy pair."""

    category_columns = [
        column
        for column in frame.columns
        if re.sub(r"[^a-z0-9]+", "", str(column).strip().casefold())
        in _CATEGORY_COLUMN_ALIASES
    ]
    if not category_columns:
        return None
    if len(category_columns) != 1:
        raise StudioPreparationBlocked(
            "ambiguous_point_line_category_column",
            "Categorical point-line input must contain exactly one Sample or "
            "Category label column.",
        )

    indices = list(row_indices)
    labels = tuple(
        _clean_studio_cell(frame.at[index, category_columns[0]]) for index in indices
    )
    positions = tuple(float(frame.at[index, x_column]) for index in indices)
    if len(labels) < 2 or any(not label for label in labels):
        raise StudioPreparationBlocked(
            "invalid_point_line_category_labels",
            "Categorical point-line labels must be non-empty for every plotted row.",
        )
    if len(set(labels)) != len(labels):
        raise StudioPreparationBlocked(
            "duplicate_point_line_category_labels",
            "Categorical point-line labels must be unique and ordered.",
        )
    if any(not math.isfinite(position) for position in positions) or len(
        set(positions)
    ) != len(positions):
        raise StudioPreparationBlocked(
            "invalid_point_line_category_positions",
            "Categorical point-line positions must be finite and unique.",
        )
    return labels, positions


def categorical_point_line_contract(
    series: list[StudioSeries],
    *,
    template_id: str,
) -> dict[str, Any] | None:
    """Describe the label-only categorical axis for ordinary point-line data."""

    categorical = [
        item for item in series if item.presentation_kind == CATEGORICAL_POINT_LINE_KIND
    ]
    if not categorical:
        return None
    if template_id != "point_line" or len(categorical) != len(series):
        raise StudioPreparationBlocked(
            "categorical_point_line_template_mismatch",
            "Source-labeled categorical point-line series require the point_line "
            "template and cannot mix with numeric-axis series.",
        )

    labels = categorical[0].component_labels
    positions = categorical[0].x_values
    if not labels or len(labels) != len(positions):
        raise StudioPreparationBlocked(
            "invalid_categorical_point_line_axis",
            "Categorical point-line labels and positions must have equal lengths.",
        )
    if any(
        item.component_labels != labels
        or item.x_values != positions
        or len(item.y_values) != len(labels)
        for item in categorical
    ):
        raise StudioPreparationBlocked(
            "inconsistent_categorical_point_line_axis",
            "Every categorical point-line series must share one ordered sample axis.",
        )

    groups: list[dict[str, Any]] = []
    for index, (label, position) in enumerate(
        zip(labels, positions, strict=True), start=1
    ):
        values = [float(item.y_values[index - 1]) for item in categorical]
        ordered = sorted(values)
        middle = len(ordered) // 2
        median = (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2.0
        )
        groups.append(
            {
                "label": label,
                "y_name": f"category_axis_slot_{index}",
                "position": float(position),
                "raw_points_visible": False,
                "boxplot_eligible": False,
                "descriptive_statistics": {
                    "minimum": min(values),
                    "q1": median,
                    "median": median,
                    "q3": median,
                    "maximum": max(values),
                },
            }
        )

    return {
        "kind": "sciplot_categorical_point_line_axis_contract",
        "version": 1,
        "presentation_kind": CATEGORICAL_POINT_LINE_KIND,
        "category_labels": list(labels),
        "category_positions": [float(position) for position in positions],
        "condition_labels": [item.label for item in categorical],
        "native_veusz_boxplot": False,
        "raw_values_preserved": True,
        "raw_replicate_count": sum(len(item.y_values) for item in categorical),
        "visual_style": {"palette_policy": "ordered_series"},
        "groups": groups,
    }
