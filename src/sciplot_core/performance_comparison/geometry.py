"""Build deterministic envelope and scatter geometry."""

from __future__ import annotations

import hashlib
import math
from sciplot_core.policy import (
    PERFORMANCE_ENVELOPE_IRREGULARITY_FRACTION,
    PERFORMANCE_ENVELOPE_PADDING_FRACTION,
)

from sciplot_core.performance_comparison.models import (
    PerformanceComparisonError,
    PerformanceMetric,
)


def _axis_bounds(
    values: list[float],
    *,
    metric: PerformanceMetric,
) -> tuple[float, float]:
    minimum = min(values)
    maximum = max(values)
    span = maximum - minimum
    if math.isclose(span, 0.0):
        span = max(abs(minimum), 1.0) * 0.16
    padding = span * 0.08
    lower = metric.scatter_min if metric.scatter_min is not None else minimum - padding
    upper = metric.scatter_max if metric.scatter_max is not None else maximum + padding
    if lower > minimum and not math.isclose(lower, minimum):
        raise PerformanceComparisonError(
            "performance_scatter_bound_excludes_data",
            f"Metric {metric.metric_id!r}: ScatterMin {lower:g} excludes "
            f"the plotted minimum {minimum:g}.",
        )
    if upper < maximum and not math.isclose(upper, maximum):
        raise PerformanceComparisonError(
            "performance_scatter_bound_excludes_data",
            f"Metric {metric.metric_id!r}: ScatterMax {upper:g} excludes "
            f"the plotted maximum {maximum:g}.",
        )
    if not lower < upper:
        raise PerformanceComparisonError(
            "performance_scatter_scale_invalid",
            f"Metric {metric.metric_id!r}: scatter bounds must increase.",
        )
    return lower, upper


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique

    def cross(
        origin: tuple[float, float],
        left: tuple[float, float],
        right: tuple[float, float],
    ) -> float:
        return (left[0] - origin[0]) * (right[1] - origin[1]) - (
            left[1] - origin[1]
        ) * (right[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _circle_polygon(
    center: tuple[float, float],
    radius: float,
    *,
    point_count: int = 24,
) -> list[tuple[float, float]]:
    return [
        (
            center[0] + radius * math.cos(2.0 * math.pi * index / point_count),
            center[1] + radius * math.sin(2.0 * math.pi * index / point_count),
        )
        for index in range(point_count)
    ]


def _capsule_polygon(
    start: tuple[float, float],
    end: tuple[float, float],
    radius: float,
) -> list[tuple[float, float]]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if math.isclose(length, 0.0):
        return _circle_polygon(start, radius)
    angle = math.atan2(dy, dx)
    points: list[tuple[float, float]] = []
    for index in range(9):
        theta = angle + math.pi / 2.0 + math.pi * index / 8.0
        points.append(
            (start[0] + radius * math.cos(theta), start[1] + radius * math.sin(theta))
        )
    for index in range(9):
        theta = angle - math.pi / 2.0 + math.pi * index / 8.0
        points.append(
            (end[0] + radius * math.cos(theta), end[1] + radius * math.sin(theta))
        )
    return points


def _chaikin_closed_polygon(
    points: list[tuple[float, float]],
    *,
    iterations: int,
) -> list[tuple[float, float]]:
    smoothed = list(points)
    for _ in range(max(int(iterations), 0)):
        refined: list[tuple[float, float]] = []
        for start, end in zip(
            smoothed,
            [*smoothed[1:], smoothed[0]],
            strict=True,
        ):
            refined.extend(
                (
                    (
                        0.75 * start[0] + 0.25 * end[0],
                        0.75 * start[1] + 0.25 * end[1],
                    ),
                    (
                        0.25 * start[0] + 0.75 * end[0],
                        0.25 * start[1] + 0.75 * end[1],
                    ),
                )
            )
        smoothed = refined
    return smoothed


def _irregularize_polygon(
    points: list[tuple[float, float]],
    *,
    seed_key: str,
) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    smoothed = _chaikin_closed_polygon(
        points,
        iterations=2 if len(points) <= 8 else 1,
    )
    centroid = (
        sum(point[0] for point in smoothed) / len(smoothed),
        sum(point[1] for point in smoothed) / len(smoothed),
    )
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    phase_3 = 2.0 * math.pi * int.from_bytes(digest[:4], "big") / (2**32)
    phase_5 = 2.0 * math.pi * int.from_bytes(digest[4:8], "big") / (2**32)
    result: list[tuple[float, float]] = []
    for point in smoothed:
        dx = point[0] - centroid[0]
        dy = point[1] - centroid[1]
        angle = math.atan2(dy, dx)
        modulation = (
            1.08
            + PERFORMANCE_ENVELOPE_IRREGULARITY_FRACTION
            * math.sin(3.0 * angle + phase_3)
            + 0.6
            * PERFORMANCE_ENVELOPE_IRREGULARITY_FRACTION
            * math.sin(5.0 * angle + phase_5)
        )
        result.append(
            (
                centroid[0] + modulation * dx,
                centroid[1] + modulation * dy,
            )
        )
    return result


def _expanded_envelope(
    points: list[tuple[float, float]],
    *,
    x_bounds: tuple[float, float],
    y_bounds: tuple[float, float],
    seed_key: str,
) -> list[tuple[float, float]]:
    x_span = x_bounds[1] - x_bounds[0]
    y_span = y_bounds[1] - y_bounds[0]
    normalized = [
        (
            (x_value - x_bounds[0]) / x_span,
            (y_value - y_bounds[0]) / y_span,
        )
        for x_value, y_value in points
    ]
    hull = _convex_hull(normalized)
    radius = PERFORMANCE_ENVELOPE_PADDING_FRACTION
    if len(hull) == 1:
        expanded = _circle_polygon(hull[0], radius)
    elif len(hull) == 2:
        expanded = _capsule_polygon(hull[0], hull[1], radius)
    else:
        x_min = min(point[0] for point in normalized)
        x_max = max(point[0] for point in normalized)
        y_min = min(point[1] for point in normalized)
        y_max = max(point[1] for point in normalized)
        center = (
            0.5 * (x_min + x_max),
            0.5 * (y_min + y_max),
        )
        x_radius = max(0.5 * (x_max - x_min) + radius, radius) * 1.12
        y_radius = max(0.5 * (y_max - y_min) + radius, radius) * 1.05
        superellipse_power = 3.6
        expanded = []
        for index in range(32):
            angle = 2.0 * math.pi * index / 32.0
            cosine = math.cos(angle)
            sine = math.sin(angle)
            expanded.append(
                (
                    center[0]
                    + x_radius
                    * math.copysign(
                        abs(cosine) ** (2.0 / superellipse_power),
                        cosine,
                    ),
                    center[1]
                    + y_radius
                    * math.copysign(
                        abs(sine) ** (2.0 / superellipse_power),
                        sine,
                    ),
                )
            )
    expanded = _irregularize_polygon(expanded, seed_key=seed_key)
    return [
        (
            x_bounds[0] + point[0] * x_span,
            y_bounds[0] + point[1] * y_span,
        )
        for point in expanded
    ]
