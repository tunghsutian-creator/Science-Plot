from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from matplotlib import transforms


@dataclass(frozen=True)
class BBoxPointScore:
    inside_count: int
    near_score: float
    total: float


def bbox_distance(points: np.ndarray, bbox: transforms.Bbox) -> np.ndarray:
    if points.size == 0:
        return np.array([], dtype=float)
    dx = np.where(
        points[:, 0] < bbox.x0,
        bbox.x0 - points[:, 0],
        np.where(points[:, 0] > bbox.x1, points[:, 0] - bbox.x1, 0.0),
    )
    dy = np.where(
        points[:, 1] < bbox.y0,
        bbox.y0 - points[:, 1],
        np.where(points[:, 1] > bbox.y1, points[:, 1] - bbox.y1, 0.0),
    )
    return np.hypot(dx, dy)


def score_points_against_bbox(
    points: np.ndarray,
    bbox: transforms.Bbox,
    *,
    inside_weight: float,
    near_radius: float,
    near_weight: float = 1.0,
    normalize_near: bool = True,
) -> BBoxPointScore:
    if points.size == 0:
        return BBoxPointScore(inside_count=0, near_score=0.0, total=0.0)
    inside = (
        (points[:, 0] >= bbox.x0)
        & (points[:, 0] <= bbox.x1)
        & (points[:, 1] >= bbox.y0)
        & (points[:, 1] <= bbox.y1)
    )
    inside_count = int(inside.sum())
    distances = bbox_distance(points, bbox)
    near = distances < near_radius
    near_score = 0.0
    if np.any(near):
        penalty = float((near_radius - distances[near]).sum())
        if normalize_near and near_radius > 0:
            penalty /= near_radius
        near_score = penalty * near_weight
    total = inside_count * inside_weight + near_score
    return BBoxPointScore(inside_count=inside_count, near_score=near_score, total=total)


def proximity_penalty(
    points: np.ndarray,
    bbox: transforms.Bbox,
    *,
    radius: float,
    weight: float = 1.0,
    normalize: bool = True,
) -> float:
    if points.size == 0:
        return 0.0
    distances = bbox_distance(points, bbox)
    near = distances < radius
    if not np.any(near):
        return 0.0
    penalty = float((radius - distances[near]).sum())
    if normalize and radius > 0:
        penalty /= radius
    return penalty * weight


def expanded_bbox(bbox: transforms.Bbox, *, x_scale: float, y_scale: float) -> transforms.Bbox:
    return bbox.expanded(x_scale, y_scale)


def bbox_overlaps_any(bbox: transforms.Bbox, others: Sequence[transforms.Bbox]) -> bool:
    return any(bbox.overlaps(other) for other in others)
