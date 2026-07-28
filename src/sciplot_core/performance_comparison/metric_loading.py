"""Build validated metric definitions from normalized performance rows."""

from __future__ import annotations

import math

import pandas as pd

from sciplot_core.performance_comparison.models import (
    PerformanceComparisonError,
    PerformanceMetric,
)
from sciplot_core.performance_comparison.field_validation import (
    _normalized_direction,
    _normalized_scatter_axis,
    _unique_float,
    _unique_text,
)


def load_performance_metrics(
    normalized: pd.DataFrame,
    *,
    metric_first_order: dict[str, int],
) -> list[PerformanceMetric]:
    """Validate per-metric units, scatter bounds, and radar scales."""

    metrics: list[PerformanceMetric] = []
    for metric_id, rows in normalized.groupby("metric", sort=False):
        owner = f"Metric {metric_id!r}"
        unit = _unique_text(rows, "unit", field="Unit", owner=owner)
        display_label = _unique_text(
            rows,
            "display_label" if "display_label" in rows else None,
            field="DisplayLabel",
            owner=owner,
            default=str(metric_id),
        )
        scatter_axis = _normalized_scatter_axis(
            _unique_text(
                rows,
                "scatter_axis" if "scatter_axis" in rows else None,
                field="ScatterAxis",
                owner=owner,
            ),
            metric_id=str(metric_id),
        )
        scatter_min = _unique_float(
            rows,
            "scatter_min" if "scatter_min" in rows else None,
            field="ScatterMin",
            owner=owner,
        )
        scatter_max = _unique_float(
            rows,
            "scatter_max" if "scatter_max" in rows else None,
            field="ScatterMax",
            owner=owner,
        )
        if (
            scatter_min is not None
            and scatter_max is not None
            and not scatter_min < scatter_max
        ):
            raise PerformanceComparisonError(
                "performance_scatter_scale_invalid",
                f"{owner}: ScatterMin must be smaller than ScatterMax.",
            )
        radar_order = _positive_integer_or_none(
            _unique_float(
                rows,
                "radar_order" if "radar_order" in rows else None,
                field="RadarOrder",
                owner=owner,
            ),
            owner=owner,
        )
        direction = _normalized_direction(
            _unique_text(
                rows,
                "direction" if "direction" in rows else None,
                field="Direction",
                owner=owner,
            ),
            metric_id=str(metric_id),
        )
        scale_min = _unique_float(
            rows,
            "scale_min" if "scale_min" in rows else None,
            field="ScaleMin",
            owner=owner,
        )
        scale_max = _unique_float(
            rows,
            "scale_max" if "scale_max" in rows else None,
            field="ScaleMax",
            owner=owner,
        )
        _validate_radar_scale(
            owner=owner,
            radar_order=radar_order,
            direction=direction,
            scale_min=scale_min,
            scale_max=scale_max,
        )
        metrics.append(
            PerformanceMetric(
                metric_id=str(metric_id),
                display_label=display_label,
                unit=unit,
                source_order=metric_first_order[str(metric_id)],
                scatter_axis=scatter_axis,
                scatter_min=scatter_min,
                scatter_max=scatter_max,
                radar_order=radar_order,
                direction=direction,
                scale_min=scale_min,
                scale_max=scale_max,
            )
        )
    return metrics


def _positive_integer_or_none(
    value: float | None,
    *,
    owner: str,
) -> int | None:
    if value is None:
        return None
    if value < 1 or not math.isclose(value, round(value)):
        raise PerformanceComparisonError(
            "performance_radar_order_invalid",
            f"{owner}: RadarOrder must be a positive integer.",
        )
    return int(round(value))


def _validate_radar_scale(
    *,
    owner: str,
    radar_order: int | None,
    direction: str | None,
    scale_min: float | None,
    scale_max: float | None,
) -> None:
    if radar_order is None:
        return
    if direction is None or scale_min is None or scale_max is None:
        raise PerformanceComparisonError(
            "performance_radar_scale_incomplete",
            f"{owner}: radar metrics require Direction, ScaleMin, and ScaleMax.",
        )
    if not scale_min < scale_max:
        raise PerformanceComparisonError(
            "performance_radar_scale_invalid",
            f"{owner}: ScaleMin must be smaller than ScaleMax.",
        )
