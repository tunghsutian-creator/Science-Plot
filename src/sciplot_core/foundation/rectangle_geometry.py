"""Renderer-independent complete segment/rectangle geometry in physical units."""
from __future__ import annotations

import math

Point = tuple[float, float]


def clip_segment(a: Point, b: Point, box: list[float]) -> tuple[Point, Point] | None:
    low, high = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - box[0]), (dx, box[2] - a[0]),
                 (-dy, a[1] - box[1]), (dy, box[3] - a[1])):
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            low = max(low, q / p)
        else:
            high = min(high, q / p)
        if low > high:
            return None
    return (a[0] + low * dx, a[1] + low * dy), (a[0] + high * dx, a[1] + high * dy)


def point_box_distance(point: Point, box: list[float]) -> float:
    return math.hypot(max(box[0] - point[0], 0, point[0] - box[2]),
                      max(box[1] - point[1], 0, point[1] - box[3]))


def segment_box_distance(a: Point, b: Point, box: list[float]) -> float:
    if clip_segment(a, b, box) is not None:
        return 0.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    distances = [point_box_distance(a, box), point_box_distance(b, box)]
    for x, y in ((box[0], box[1]), (box[0], box[3]), (box[2], box[1]), (box[2], box[3])):
        t = min(1.0, max(0.0, ((x - a[0]) * dx + (y - a[1]) * dy) / length)) if length else 0.0
        distances.append(math.hypot(x - a[0] - t * dx, y - a[1] - t * dy))
    return min(distances)


def rectangle_distance(a: list[float], b: list[float]) -> float:
    corners = [(a[0], a[1]), (a[2], a[1]), (a[2], a[3]), (a[0], a[3])]
    return min([point_box_distance((b[0], b[1]), a),
        *[segment_box_distance(corners[index], corners[(index+1) % 4], b) for index in range(4)]])
