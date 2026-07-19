from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_list,
    require_json_object,
)


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    return text


@dataclass
class VeuszDataPointSelection:
    """Optional point context supplied to a selected-object assistant request."""

    target_object_id: str
    x: float
    y: float
    graph_x: float
    graph_y: float
    x_label: str = "x"
    y_label: str = "y"
    index: str | None = None
    display_type: tuple[str, str] = ("numeric", "numeric")

    def __post_init__(self) -> None:
        self.target_object_id = _required_text(
            self.target_object_id,
            "data_point.target_object_id",
        )
        values = (self.x, self.y, self.graph_x, self.graph_y)
        if not all(
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("Assistant data-point coordinates must be finite numbers.")
        self.x = float(self.x)
        self.y = float(self.y)
        self.graph_x = float(self.graph_x)
        self.graph_y = float(self.graph_y)
        self.x_label = _required_text(self.x_label, "data_point.x_label")
        self.y_label = _required_text(self.y_label, "data_point.y_label")
        if self.index is not None:
            self.index = _required_text(self.index, "data_point.index")
        if (
            not isinstance(self.display_type, tuple)
            or len(self.display_type) != 2
            or not all(isinstance(item, str) and item for item in self.display_type)
        ):
            raise ValueError("data_point.display_type must contain two strings.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_object_id": self.target_object_id,
            "x": self.x,
            "y": self.y,
            "graph_x": self.graph_x,
            "graph_y": self.graph_y,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "index": self.index,
            "display_type": list(self.display_type),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any] | None,
    ) -> VeuszDataPointSelection | None:
        if payload is None:
            return None
        value = require_json_object(payload, label="selection.data_point")
        reject_unknown_keys(
            value,
            {
                "target_object_id",
                "x",
                "y",
                "graph_x",
                "graph_y",
                "x_label",
                "y_label",
                "index",
                "display_type",
            },
            label="selection.data_point",
        )
        raw_display = require_json_list(
            value.get("display_type", ["numeric", "numeric"]),
            label="selection.data_point.display_type",
        )
        if len(raw_display) != 2 or not all(
            isinstance(item, str) and item for item in raw_display
        ):
            raise ValueError(
                "selection.data_point.display_type must contain two strings."
            )

        def number(key: str) -> float:
            raw = value.get(key)
            if (
                not isinstance(raw, int | float)
                or isinstance(raw, bool)
                or not math.isfinite(float(raw))
            ):
                raise ValueError(f"selection.data_point.{key} must be finite.")
            return float(raw)

        raw_index = value.get("index")
        if raw_index is not None and not isinstance(raw_index, str):
            raise ValueError("selection.data_point.index must be a string or null.")
        return cls(
            target_object_id=_required_text(
                value.get("target_object_id"),
                "selection.data_point.target_object_id",
            ),
            x=number("x"),
            y=number("y"),
            graph_x=number("graph_x"),
            graph_y=number("graph_y"),
            x_label=_required_text(
                value.get("x_label", "x"),
                "selection.data_point.x_label",
            ),
            y_label=_required_text(
                value.get("y_label", "y"),
                "selection.data_point.y_label",
            ),
            index=raw_index or None,
            display_type=(str(raw_display[0]), str(raw_display[1])),
        )


@dataclass
class VeuszSelection:
    """Stable selected-object context shared by Studio and provider contracts."""

    object_ids: list[str] = field(default_factory=list)
    primary_object_id: str | None = None
    data_point: VeuszDataPointSelection | None = None

    def __post_init__(self) -> None:
        self.object_ids = [
            _required_text(object_id, "selection object_id")
            for object_id in self.object_ids
        ]
        if len(set(self.object_ids)) != len(self.object_ids):
            raise ValueError("VeuszSelection object_ids must be unique.")
        if self.primary_object_id and self.primary_object_id not in self.object_ids:
            raise ValueError("primary_object_id must be included in object_ids.")
        if (
            self.data_point is not None
            and self.data_point.target_object_id not in self.object_ids
        ):
            raise ValueError(
                "data_point target_object_id must be included in object_ids."
            )
        if (
            self.data_point is not None
            and self.primary_object_id != self.data_point.target_object_id
        ):
            raise ValueError(
                "data_point target_object_id must be the primary_object_id."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_ids": list(self.object_ids),
            "primary_object_id": self.primary_object_id,
            "data_point": self.data_point.to_dict() if self.data_point else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> VeuszSelection:
        if payload is None:
            return cls()
        value = require_json_object(payload, label="selection")
        reject_unknown_keys(
            value,
            {"object_ids", "primary_object_id", "data_point"},
            label="selection",
        )
        raw_ids = require_json_list(
            value.get("object_ids", []),
            label="selection.object_ids",
        )
        ids = [_required_text(item, "selection object_id") for item in raw_ids]
        primary = value.get("primary_object_id")
        if primary is not None and not isinstance(primary, str):
            raise ValueError("selection.primary_object_id must be a string or null.")
        return cls(
            object_ids=ids,
            primary_object_id=primary or None,
            data_point=VeuszDataPointSelection.from_dict(value.get("data_point")),
        )


__all__ = ["VeuszDataPointSelection", "VeuszSelection"]
