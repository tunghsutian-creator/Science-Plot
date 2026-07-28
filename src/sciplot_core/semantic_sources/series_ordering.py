"""Order curve series from explicit, material-pair, or shared-height evidence."""

from __future__ import annotations

import math
import re
from typing import Any, Callable
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.series_labels import (
    _intake_group_name,
)


def _series_order_map(series_order: object) -> dict[str, int]:
    if not isinstance(series_order, list | tuple):
        return {}
    ordered: dict[str, int] = {}
    for index, value in enumerate(series_order):
        label = _clean_text(value)
        if label and label not in ordered:
            ordered[label] = index
    return ordered


def _order_curve_series(
    series_list: list[CurveSeriesPayload],
    series_order: object,
) -> list[CurveSeriesPayload]:
    order = _series_order_map(series_order)
    if not order:
        return series_list

    def key(item: tuple[int, CurveSeriesPayload]) -> tuple[int, int]:
        index, series = item
        group_name = _intake_group_name(series.sample) or series.sample
        rank = order.get(series.sample, order.get(group_name, len(order) + index))
        return (rank, index)

    return [series for _index, series in sorted(enumerate(series_list), key=key)]


def _recycled_pa_pair_rank(sample: object) -> int | None:
    label = _clean_text(sample)
    group_name = _intake_group_name(label) or label
    compact = re.sub(r"[^a-z0-9]+", "", group_name.casefold())
    if compact == "rpa":
        return 0
    if compact == "mrpa":
        return 1
    return None


def _order_recycled_pa_pair_control_first(
    values: list[Any],
    *,
    sample_of: Callable[[Any], object],
) -> list[Any]:
    """Keep the rPA control black and the modified m-rPA sample blue.

    The shared ordinary palette is positional: the first sample is the
    near-black control and the second is blue. Apply this semantic ordering
    only to the exact two-condition recycled-PA comparison so unrelated
    mechanical sample orders remain source- or user-controlled.
    """

    ranks = [_recycled_pa_pair_rank(sample_of(value)) for value in values]
    if {rank for rank in ranks if rank is not None} != {0, 1}:
        return values
    if any(rank is None for rank in ranks):
        return values
    return [
        value
        for _index, value in sorted(
            enumerate(values),
            key=lambda item: (
                int(ranks[item[0]]),
                item[0],
            ),
        )
    ]


def _finite_series_points(series: CurveSeriesPayload) -> list[tuple[float, float]]:
    return sorted(
        (
            (x_value, y_value)
            for x_value, y_value in series.points
            if math.isfinite(x_value) and math.isfinite(y_value)
        ),
        key=lambda item: item[0],
    )


def _interpolated_y_at(
    points: list[tuple[float, float]], target_x: float
) -> float | None:
    if not points:
        return None
    if target_x <= points[0][0]:
        return points[0][1]
    for index in range(1, len(points)):
        x0, y0 = points[index - 1]
        x1, y1 = points[index]
        if target_x > x1:
            continue
        if math.isclose(x0, x1):
            return y1
        fraction = (target_x - x0) / (x1 - x0)
        return y0 + (y1 - y0) * fraction
    return points[-1][1]


def _order_curve_series_by_shared_right_height(
    series_list: list[CurveSeriesPayload],
) -> list[CurveSeriesPayload]:
    if len(series_list) < 2:
        return series_list
    point_sets = [_finite_series_points(series) for series in series_list]
    usable_ranges = [(points[0][0], points[-1][0]) for points in point_sets if points]
    if len(usable_ranges) != len(series_list):
        return series_list
    shared_min = max(start for start, _end in usable_ranges)
    shared_max = min(end for _start, end in usable_ranges)
    target_x = shared_max if shared_min <= shared_max else None

    scored: list[tuple[float, int, CurveSeriesPayload]] = []
    for index, (series, points) in enumerate(zip(series_list, point_sets, strict=True)):
        if target_x is None:
            score = points[-1][1]
        else:
            interpolated = _interpolated_y_at(points, target_x)
            score = interpolated if interpolated is not None else points[-1][1]
        scored.append((score, index, series))
    return [
        series
        for _score, _index, series in sorted(
            scored, key=lambda item: (-item[0], item[1])
        )
    ]
