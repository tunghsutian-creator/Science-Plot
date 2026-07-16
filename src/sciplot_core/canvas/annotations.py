from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sciplot_core.canvas._validation import (
    reject_unknown_keys,
    require_json_int,
    require_json_object,
)
from sciplot_core.canvas.operations import _validate_json_value

REVIEW_ANNOTATION_KIND = "sciplot_review_annotation"
REVIEW_ANNOTATION_VERSION = 1
ANNOTATION_SHAPES = {"text", "arrow", "rectangle", "ellipse", "freehand"}
ANNOTATION_COORDINATE_SPACES = {"page", "normalized_page", "graph", "data", "object"}
ANNOTATION_STATES = {"review_only", "promoted", "removed"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    return text


@dataclass(frozen=True)
class ReviewAnnotation:
    page_index: int
    shape: str
    coordinate_space: str
    geometry: dict[str, Any]
    text: str = ""
    target_object_id: str | None = None
    state: str = "review_only"
    annotation_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        _required_text(self.annotation_id, "annotation_id")
        if self.page_index < 0:
            raise ValueError("page_index must be non-negative.")
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
        if not self.geometry:
            raise ValueError("annotation geometry cannot be empty.")
        _validate_json_value(self.geometry, path="geometry")
        if self.coordinate_space == "object" and not self.target_object_id:
            raise ValueError("object-space annotations require target_object_id.")
        if self.target_object_id:
            _required_text(self.target_object_id, "target_object_id")

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
            "state": self.state,
            "created_at": self.created_at,
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
                "state",
                "created_at",
            },
            label="ReviewAnnotation",
        )
        if payload.get("kind") != REVIEW_ANNOTATION_KIND:
            raise ValueError("Not a SciPlot ReviewAnnotation payload.")
        version = require_json_int(payload.get("version", 0), label="version")
        if version != REVIEW_ANNOTATION_VERSION:
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
            state=str(payload.get("state") or "review_only"),
            created_at=str(payload.get("created_at") or _now()),
        )


__all__ = [
    "ANNOTATION_COORDINATE_SPACES",
    "ANNOTATION_SHAPES",
    "ANNOTATION_STATES",
    "REVIEW_ANNOTATION_KIND",
    "REVIEW_ANNOTATION_VERSION",
    "ReviewAnnotation",
]
