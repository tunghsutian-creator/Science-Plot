from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sciplot_core.canvas._validation import (
    reject_unknown_keys,
    require_json_int,
    require_json_number,
    require_json_object,
)

REVIEW_ANNOTATION_KIND = "sciplot_review_annotation"
REVIEW_ANNOTATION_VERSION = 2
REVIEW_ANNOTATION_COMPATIBLE_VERSIONS = {1, REVIEW_ANNOTATION_VERSION}
ANNOTATION_SHAPES = {"text", "arrow", "rectangle", "ellipse", "freehand"}
PROMOTABLE_ANNOTATION_SHAPES = {"text", "arrow", "rectangle", "ellipse"}
ANNOTATION_COORDINATE_SPACES = {"page", "normalized_page", "graph", "data", "object"}
ANNOTATION_STATES = {"review_only", "promoted", "removed"}
ANCHORED_COORDINATE_SPACES = {"graph", "data", "object"}

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    return text


def _color(value: object, label: str) -> str:
    text = str(value or "").strip()
    if _HEX_COLOR.fullmatch(text) is None:
        raise ValueError(f"{label} must be a #RRGGBB color.")
    return text.lower()


def _point(value: object, label: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must contain exactly two coordinates.")
    coordinates: list[float] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
        ):
            raise ValueError(f"{label}[{index}] must be a finite number.")
        coordinates.append(float(item))
    return coordinates[0], coordinates[1]


def annotation_geometry_points(
    shape: str,
    geometry: dict[str, Any],
) -> list[tuple[float, float]]:
    """Return canonical control points for a review-annotation geometry."""

    if shape == "text":
        reject_unknown_keys(geometry, {"position"}, label="text annotation geometry")
        return [_point(geometry.get("position"), "geometry.position")]
    if shape == "arrow":
        reject_unknown_keys(
            geometry,
            {"start", "end"},
            label="arrow annotation geometry",
        )
        start = _point(geometry.get("start"), "geometry.start")
        end = _point(geometry.get("end"), "geometry.end")
        if start == end:
            raise ValueError("Arrow annotation start and end must differ.")
        return [start, end]
    if shape in {"rectangle", "ellipse"}:
        reject_unknown_keys(geometry, {"rect"}, label=f"{shape} annotation geometry")
        rect = geometry.get("rect")
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ValueError("geometry.rect must contain x, y, width, and height.")
        x, y = _point(rect[:2], "geometry.rect position")
        width = require_json_number(rect[2], label="geometry.rect width")
        height = require_json_number(rect[3], label="geometry.rect height")
        if width <= 0 or height <= 0:
            raise ValueError("Annotation rectangle width and height must be positive.")
        return [(x, y), (x + width, y + height)]
    if shape == "freehand":
        reject_unknown_keys(
            geometry,
            {"points"},
            label="freehand annotation geometry",
        )
        raw_points = geometry.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 2:
            raise ValueError("Freehand annotation requires at least two points.")
        return [
            _point(value, f"geometry.points[{index}]")
            for index, value in enumerate(raw_points)
        ]
    raise ValueError(f"Unsupported annotation shape: {shape!r}")


def annotation_geometry_from_points(
    shape: str,
    points: list[tuple[float, float]],
) -> dict[str, Any]:
    """Build canonical geometry after a coordinate-space transformation."""

    normalized = [
        [float(point[0]), float(point[1])]
        for point in points
    ]
    if shape == "text":
        if len(normalized) != 1:
            raise ValueError("Text annotation requires one transformed point.")
        return {"position": normalized[0]}
    if shape == "arrow":
        if len(normalized) != 2:
            raise ValueError("Arrow annotation requires two transformed points.")
        return {"start": normalized[0], "end": normalized[1]}
    if shape in {"rectangle", "ellipse"}:
        if len(normalized) != 2:
            raise ValueError(f"{shape} annotation requires two transformed corners.")
        x1, y1 = normalized[0]
        x2, y2 = normalized[1]
        return {
            "rect": [
                min(x1, x2),
                min(y1, y2),
                abs(x2 - x1),
                abs(y2 - y1),
            ]
        }
    if shape == "freehand":
        if len(normalized) < 2:
            raise ValueError("Freehand annotation requires two transformed points.")
        return {"points": normalized}
    raise ValueError(f"Unsupported annotation shape: {shape!r}")


@dataclass(frozen=True)
class ReviewAnnotationStyle:
    color: str = "#ff9f0a"
    fill_color: str = "#fff2cc"
    line_width: float = 1.0
    font_size: float = 7.0
    opacity: float = 0.96

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", _color(self.color, "style.color"))
        object.__setattr__(
            self,
            "fill_color",
            _color(self.fill_color, "style.fill_color"),
        )
        for value, label, minimum, maximum in (
            (self.line_width, "style.line_width", 0.5, 12.0),
            (self.font_size, "style.font_size", 6.0, 72.0),
            (self.opacity, "style.opacity", 0.05, 1.0),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or not minimum <= float(value) <= maximum
            ):
                raise ValueError(
                    f"{label} must be a finite number between {minimum} and {maximum}."
                )
        object.__setattr__(self, "line_width", float(self.line_width))
        object.__setattr__(self, "font_size", float(self.font_size))
        object.__setattr__(self, "opacity", float(self.opacity))

    def to_dict(self) -> dict[str, Any]:
        return {
            "color": self.color,
            "fill_color": self.fill_color,
            "line_width": self.line_width,
            "font_size": self.font_size,
            "opacity": self.opacity,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any] | None,
    ) -> ReviewAnnotationStyle:
        if payload is None:
            return cls()
        value = require_json_object(payload, label="annotation style")
        reject_unknown_keys(
            value,
            {"color", "fill_color", "line_width", "font_size", "opacity"},
            label="annotation style",
        )
        return cls(
            color=str(value.get("color") or "#ff9f0a"),
            fill_color=str(value.get("fill_color") or "#fff2cc"),
            line_width=require_json_number(
                value.get("line_width", 1.0),
                label="style.line_width",
            ),
            font_size=require_json_number(
                value.get("font_size", 7.0),
                label="style.font_size",
            ),
            opacity=require_json_number(
                value.get("opacity", 0.96),
                label="style.opacity",
            ),
        )


@dataclass(frozen=True)
class ReviewAnnotation:
    page_index: int
    shape: str
    coordinate_space: str
    geometry: dict[str, Any]
    text: str = ""
    target_object_id: str | None = None
    style: ReviewAnnotationStyle = field(default_factory=ReviewAnnotationStyle)
    state: str = "review_only"
    promoted_object_id: str | None = None
    annotation_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _required_text(self.annotation_id, "annotation_id")
        if (
            isinstance(self.page_index, bool)
            or not isinstance(self.page_index, int)
            or self.page_index < 0
        ):
            raise ValueError("page_index must be a non-negative integer.")
        if self.shape not in ANNOTATION_SHAPES:
            raise ValueError(f"Unsupported annotation shape: {self.shape!r}")
        if self.coordinate_space not in ANNOTATION_COORDINATE_SPACES:
            raise ValueError(
                f"Unsupported annotation coordinate space: {self.coordinate_space!r}"
            )
        if self.state not in ANNOTATION_STATES:
            raise ValueError(f"Unsupported annotation state: {self.state!r}")
        if not isinstance(self.geometry, dict):
            raise ValueError("annotation geometry must be an object.")
        points = annotation_geometry_points(self.shape, self.geometry)
        if self.coordinate_space in {"normalized_page", "graph", "object"}:
            if any(
                coordinate < 0.0 or coordinate > 1.0
                for point in points
                for coordinate in point
            ):
                raise ValueError(
                    f"{self.coordinate_space} annotation coordinates must be normalized."
                )
        elif self.coordinate_space == "page":
            if any(
                coordinate < 0.0
                for point in points
                for coordinate in point
            ):
                raise ValueError("Page annotation coordinates must be non-negative.")
        if (
            self.coordinate_space in ANCHORED_COORDINATE_SPACES
            and not self.target_object_id
        ):
            raise ValueError(
                f"{self.coordinate_space}-space annotations require target_object_id."
            )
        if self.target_object_id:
            _required_text(self.target_object_id, "target_object_id")
        if not isinstance(self.style, ReviewAnnotationStyle):
            raise ValueError("style must be a ReviewAnnotationStyle.")
        if self.shape == "text" and self.state == "review_only":
            _required_text(self.text, "text annotation text")
        if self.promoted_object_id:
            _required_text(self.promoted_object_id, "promoted_object_id")
        if self.state == "promoted":
            if self.shape not in PROMOTABLE_ANNOTATION_SHAPES:
                raise ValueError(
                    f"{self.shape!r} review marks have no native promotion mapping."
                )
            if not self.promoted_object_id:
                raise ValueError(
                    "Promoted annotations require promoted_object_id."
                )
        elif self.promoted_object_id is not None:
            raise ValueError(
                "Only promoted annotations may carry promoted_object_id."
            )

    @property
    def promotable(self) -> bool:
        return (
            self.state == "review_only"
            and self.shape in PROMOTABLE_ANNOTATION_SHAPES
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": REVIEW_ANNOTATION_KIND,
            "version": REVIEW_ANNOTATION_VERSION,
            "annotation_id": self.annotation_id,
            "page_index": self.page_index,
            "shape": self.shape,
            "coordinate_space": self.coordinate_space,
            "geometry": dict(self.geometry),
            "text": self.text,
            "target_object_id": self.target_object_id,
            "style": self.style.to_dict(),
            "state": self.state,
            "promoted_object_id": self.promoted_object_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReviewAnnotation:
        reject_unknown_keys(
            payload,
            {
                "kind",
                "version",
                "annotation_id",
                "page_index",
                "shape",
                "coordinate_space",
                "geometry",
                "text",
                "target_object_id",
                "style",
                "state",
                "promoted_object_id",
                "created_at",
                "updated_at",
            },
            label="ReviewAnnotation",
        )
        if payload.get("kind") != REVIEW_ANNOTATION_KIND:
            raise ValueError("Not a SciPlot ReviewAnnotation payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version not in REVIEW_ANNOTATION_COMPATIBLE_VERSIONS:
            raise ValueError(
                f"Unsupported ReviewAnnotation version: {payload.get('version')!r}"
            )
        return cls(
            annotation_id=_required_text(payload.get("annotation_id"), "annotation_id"),
            page_index=require_json_int(
                payload.get("page_index", 0), label="page_index"
            ),
            shape=str(payload.get("shape") or ""),
            coordinate_space=str(payload.get("coordinate_space") or ""),
            geometry=dict(
                require_json_object(
                    payload.get("geometry"), label="annotation geometry"
                )
            ),
            text=str(payload.get("text") or ""),
            target_object_id=(
                str(payload["target_object_id"])
                if payload.get("target_object_id")
                else None
            ),
            style=ReviewAnnotationStyle.from_dict(
                payload.get("style") if version >= 2 else None
            ),
            state=str(payload.get("state") or "review_only"),
            promoted_object_id=(
                str(payload["promoted_object_id"])
                if payload.get("promoted_object_id")
                else None
            ),
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(
                payload.get("updated_at")
                or payload.get("created_at")
                or _now()
            ),
        )


__all__ = [
    "ANCHORED_COORDINATE_SPACES",
    "ANNOTATION_COORDINATE_SPACES",
    "ANNOTATION_SHAPES",
    "ANNOTATION_STATES",
    "PROMOTABLE_ANNOTATION_SHAPES",
    "REVIEW_ANNOTATION_COMPATIBLE_VERSIONS",
    "REVIEW_ANNOTATION_KIND",
    "REVIEW_ANNOTATION_VERSION",
    "ReviewAnnotation",
    "ReviewAnnotationStyle",
    "annotation_geometry_from_points",
    "annotation_geometry_points",
]
