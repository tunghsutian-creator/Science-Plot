from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sciplot_core.policy import (
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_RIGHT_MARGIN_MM,
)

RELATIVE_GRADIENT_STRIP_LAYOUT_ID = "relative_gradient_strip_120x42_v1"


@dataclass(frozen=True)
class FigureLayoutContract:
    layout_id: str
    size_mm: tuple[float, float]
    panel_count: int
    outer_frame_x_mm: tuple[float, float]
    panel_frame_y_mm: tuple[float, float]
    panel_gap_mm: float
    colorbar_frame_mm: tuple[float, float, float, float]

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": "sciplot_figure_layout_contract",
            "version": 1,
            "layout_id": self.layout_id,
            "size_mm": list(self.size_mm),
            "panel_count": self.panel_count,
            "outer_frame_x_mm": list(self.outer_frame_x_mm),
            "panel_frame_y_mm": list(self.panel_frame_y_mm),
            "panel_gap_mm": self.panel_gap_mm,
            "colorbar_frame_mm": list(self.colorbar_frame_mm),
        }


_LAYOUTS = {
    RELATIVE_GRADIENT_STRIP_LAYOUT_ID: FigureLayoutContract(
        layout_id=RELATIVE_GRADIENT_STRIP_LAYOUT_ID,
        size_mm=(120.0, 42.0),
        panel_count=4,
        outer_frame_x_mm=(
            UNIFIED_LEFT_MARGIN_MM,
            120.0 - UNIFIED_RIGHT_MARGIN_MM,
        ),
        panel_frame_y_mm=(6.0, 34.0),
        panel_gap_mm=1.1,
        colorbar_frame_mm=(8.2, 6.0, 10.4, 34.0),
    ),
}


def get_figure_layout(layout_id: str) -> FigureLayoutContract:
    normalized = str(layout_id or "").strip()
    try:
        return deepcopy(_LAYOUTS[normalized])
    except KeyError as exc:
        known = ", ".join(sorted(_LAYOUTS))
        raise ValueError(
            f"Unknown figure layout `{layout_id}`. Available: {known}."
        ) from exc


def list_figure_layouts() -> list[dict[str, Any]]:
    return [layout.to_payload() for layout in _LAYOUTS.values()]


__all__ = [
    "FigureLayoutContract",
    "RELATIVE_GRADIENT_STRIP_LAYOUT_ID",
    "get_figure_layout",
    "list_figure_layouts",
]
