"""Data-space geometry for extent and window intersection, preserving gaps/order.

Physical marker, glyph and error-cap sizes belong to layout. A rule's domain
spanning direction has no independent extent and cannot bootstrap an auto axis.
"""
from collections.abc import Iterator
from dataclasses import dataclass
import math
from typing import Any

from sciplot_core.plot_transforms.display import interpolate_display

Point = tuple[float, float]


@dataclass(frozen=True)
class Geometry:
    kind: str
    points: tuple[Point, ...]


def _runs(rows: Any) -> Iterator[list[Any]]:
    run: list[Any] = []
    for row in rows:
        if any(value is None for value in row):
            if run:
                yield run
                run = []
        else:
            run.append(row)
    if run:
        yield run


def data_coordinates(datasets: dict[str, dict[str, Any]], layer: dict[str, Any]) -> dict[str, list[Any]]:
    columns = datasets[layer["dataset_id"]]["columns"]
    return {name: list(columns[column]["values"]) for name, column in layer["mappings"].items()}


def mark_data_geometry(data: dict[str, list[Any]], mark: dict[str, Any]) -> list[Geometry]:
    """The one data-primitive writer for viewport projection and native adapters.

    Error bars and rules intentionally retain the historical paired-presence
    prerequisite. Band polygons independently consume contiguous x/low/high.
    """
    result: list[Geometry] = []
    kind = mark["type"]
    if kind == "band":
        for run in _runs(zip(data["x"], data["y_low"], data["y_high"], strict=True)):
            if len(run) >= 2:
                result.append(Geometry("polygon", tuple((x, low) for x, low, _ in run)
                                       + tuple((x, high) for x, _, high in reversed(run))))
    elif kind == "line":
        x, y = data["x"], data["y"]
        if "interpolation" in mark:
            curve = interpolate_display(x, y, **mark["interpolation"])
            x, y = curve["x"], curve["y"]
        result.extend(Geometry("path", tuple(run)) for run in _runs(zip(x, y, strict=True)) if len(run) >= 2)
    else:
        for index, (x, y) in enumerate(zip(data["x"], data["y"], strict=True)):
            if x is None or y is None:
                continue
            if kind == "bar":
                half, baseline = mark["width_data"] / 2, mark["baseline"]
                result.append(Geometry("polygon", ((x-half, baseline), (x+half, baseline), (x+half, y), (x-half, y))))
            elif kind == "errorbar":
                low, high = data["y_low"][index], data["y_high"][index]
                if low is not None and high is not None:
                    result.append(Geometry("path", ((x, low), (x, high))))
            elif kind == "rule":
                result.append(Geometry(mark["orientation"], ((x, y),)))
            else:  # point and text anchors
                result.append(Geometry("point", ((x, y),)))
    return result


def layer_geometry(layer: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> list[Geometry]:
    data = data_coordinates(datasets, layer)
    return [item for mark in layer["marks"] for item in mark_data_geometry(data, mark)]


def extent_values(geometry: list[Geometry], dimension: str) -> list[float]:
    index = 0 if dimension == "x" else 1
    spanning = "horizontal" if dimension == "x" else "vertical"
    return [point[index] for item in geometry if item.kind != spanning for point in item.points]


def _inside(point: Point, window: tuple[float, float, float, float]) -> bool:
    left, right, bottom, top = window
    return left <= point[0] <= right and bottom <= point[1] <= top


def _segment_intersects(a: Point, b: Point, window: tuple[float, float, float, float]) -> bool:
    left, right, bottom, top = window
    dx, dy = b[0] - a[0], b[1] - a[1]
    enter, leave = 0., 1.
    for p, q in ((-dx, a[0]-left), (dx, right-a[0]), (-dy, a[1]-bottom), (dy, top-a[1])):
        if p == 0:
            if q < 0:
                return False
        elif p < 0:
            enter = max(enter, q / p)
        else:
            leave = min(leave, q / p)
        if enter > leave:
            return False
    return True


def _in_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if (current[1] > y) != (previous[1] > y):
            crossing = current[0] + (y-current[1]) * (previous[0]-current[0]) / (previous[1]-current[1])
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def window_intersects(item: Geometry, x_scale: dict[str, Any], y_scale: dict[str, Any]) -> bool:
    """Intersect the geometry after the same axis transform as native drawing."""
    def coordinate(value: float, scale: dict[str, Any]) -> float:
        return math.log10(value) if scale["transform"] == "log" else value

    left, right = (coordinate(value, x_scale) for value in x_scale["domain"])
    bottom, top = (coordinate(value, y_scale) for value in y_scale["domain"])
    window = (left, right, bottom, top)
    if item.kind == "vertical":
        return left <= coordinate(item.points[0][0], x_scale) <= right
    if item.kind == "horizontal":
        return bottom <= coordinate(item.points[0][1], y_scale) <= top
    points = tuple((coordinate(x, x_scale), coordinate(y, y_scale)) for x, y in item.points)
    if any(_inside(point, window) for point in points):
        return True
    edges = list(zip(points, points[1:], strict=False))
    if item.kind == "polygon":
        edges.append((points[-1], points[0]))
    if any(_segment_intersects(a, b, window) for a, b in edges):
        return True
    return item.kind == "polygon" and any(_in_polygon(point, points) for point in
        ((left, bottom), (left, top), (right, bottom), (right, top)))
