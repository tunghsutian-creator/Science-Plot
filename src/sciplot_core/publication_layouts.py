from __future__ import annotations

import math
from typing import Any

COMPOSITE_LAYOUT_KIND = "sciplot_composite_layout"
COMPOSITE_LAYOUT_VERSION = 1
COMPOSITE_CANVAS_WIDTH_MM = 183.0
COMPOSITE_NOMINAL_CONTENT_WIDTH_MM = 180.0
DEFAULT_COMPOSITION_HEIGHT_MM = 55.0
MIN_COMPOSITION_HEIGHT_MM = 20.0
MAX_COMPOSITION_HEIGHT_MM = 170.0

_LAYOUTS: dict[str, dict[str, Any]] = {
    "single_180": {
        "label": "Single 180 mm panel",
        "panel_widths_mm": (180.0,),
        "gaps_mm": (),
        "outer_left_mm": 1.5,
        "outer_right_mm": 1.5,
    },
    "double_equal_90": {
        "label": "Two equal 90 mm panels",
        "panel_widths_mm": (90.0, 90.0),
        "gaps_mm": (3.0,),
        "outer_left_mm": 0.0,
        "outer_right_mm": 0.0,
    },
    "double_120_60": {
        "label": "120 mm primary plus 60 mm supporting panel",
        "panel_widths_mm": (120.0, 60.0),
        "gaps_mm": (3.0,),
        "outer_left_mm": 0.0,
        "outer_right_mm": 0.0,
    },
    "double_60_120": {
        "label": "60 mm supporting plus 120 mm primary panel",
        "panel_widths_mm": (60.0, 120.0),
        "gaps_mm": (3.0,),
        "outer_left_mm": 0.0,
        "outer_right_mm": 0.0,
    },
    "triple_equal_60": {
        "label": "Three equal 60 mm panels",
        "panel_widths_mm": (60.0, 60.0, 60.0),
        "gaps_mm": (1.5, 1.5),
        "outer_left_mm": 0.0,
        "outer_right_mm": 0.0,
    },
}


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _validated_height(value: float) -> float:
    height = float(value)
    if not math.isfinite(height) or not (
        MIN_COMPOSITION_HEIGHT_MM <= height <= MAX_COMPOSITION_HEIGHT_MM
    ):
        raise ValueError(
            "Composite canvas height must be a finite value between "
            f"{MIN_COMPOSITION_HEIGHT_MM:g} and "
            f"{MAX_COMPOSITION_HEIGHT_MM:g} mm."
        )
    return height


def composite_layout_ids() -> tuple[str, ...]:
    return tuple(_LAYOUTS)


def build_composite_layout(
    layout_id: str,
    *,
    canvas_height_mm: float = DEFAULT_COMPOSITION_HEIGHT_MM,
) -> dict[str, Any]:
    """Return the pure publication geometry contract for one 183 mm layout.

    This module intentionally contains no multi-panel editor, mutable project,
    renderer, or GUI implementation. Publication metadata may describe a
    confirmed layout without making figure assembly part of daily readiness.
    """

    try:
        spec = _LAYOUTS[layout_id]
    except KeyError as exc:
        known = ", ".join(sorted(_LAYOUTS))
        raise ValueError(
            f"Unknown composite layout `{layout_id}`. Available: {known}."
        ) from exc
    height = _validated_height(canvas_height_mm)
    geometry_total = (
        float(spec["outer_left_mm"])
        + sum(float(value) for value in spec["panel_widths_mm"])
        + sum(float(value) for value in spec["gaps_mm"])
        + float(spec["outer_right_mm"])
    )
    if not math.isclose(
        geometry_total,
        COMPOSITE_CANVAS_WIDTH_MM,
        abs_tol=1e-9,
    ):
        raise RuntimeError(
            f"Composite layout `{layout_id}` closes to "
            f"{geometry_total:g} mm, not 183 mm."
        )

    cursor = float(spec["outer_left_mm"])
    slots: list[dict[str, Any]] = []
    widths = tuple(float(value) for value in spec["panel_widths_mm"])
    gaps = tuple(float(value) for value in spec["gaps_mm"])
    for index, width in enumerate(widths):
        label = chr(ord("a") + index)
        slots.append(
            {
                "id": f"panel_{label}",
                "order": index + 1,
                "panel_label": label,
                "x_mm": _rounded(cursor),
                "y_mm": 0.0,
                "width_mm": _rounded(width),
                "height_mm": _rounded(height),
                "x_fraction": _rounded(cursor / COMPOSITE_CANVAS_WIDTH_MM),
                "width_fraction": _rounded(
                    width / COMPOSITE_CANVAS_WIDTH_MM
                ),
            }
        )
        cursor += width
        if index < len(gaps):
            cursor += gaps[index]

    return {
        "kind": COMPOSITE_LAYOUT_KIND,
        "version": COMPOSITE_LAYOUT_VERSION,
        "id": layout_id,
        "label": str(spec["label"]),
        "authority": "sciplot_composite_layout_definition",
        "canvas_width_mm": COMPOSITE_CANVAS_WIDTH_MM,
        "canvas_height_mm": _rounded(height),
        "nominal_content_width_mm": COMPOSITE_NOMINAL_CONTENT_WIDTH_MM,
        "spare_width_mm": _rounded(
            COMPOSITE_CANVAS_WIDTH_MM
            - COMPOSITE_NOMINAL_CONTENT_WIDTH_MM
        ),
        "panel_widths_mm": list(widths),
        "gaps_mm": list(gaps),
        "outer_left_mm": float(spec["outer_left_mm"]),
        "outer_right_mm": float(spec["outer_right_mm"]),
        "geometry_total_mm": COMPOSITE_CANVAS_WIDTH_MM,
        "slots": slots,
        "renderer_contract": {
            "engine": "veusz",
            "metadata_only": True,
            "raster_panel_composition_allowed": False,
            "grid_outer_margins_must_be_explicit": True,
        },
    }


def list_composite_layouts() -> list[dict[str, Any]]:
    return [build_composite_layout(layout_id) for layout_id in _LAYOUTS]
__all__ = [
    "COMPOSITE_CANVAS_WIDTH_MM",
    "COMPOSITE_LAYOUT_KIND",
    "COMPOSITE_LAYOUT_VERSION",
    "COMPOSITE_NOMINAL_CONTENT_WIDTH_MM",
    "DEFAULT_COMPOSITION_HEIGHT_MM",
    "MAX_COMPOSITION_HEIGHT_MM",
    "MIN_COMPOSITION_HEIGHT_MM",
    "build_composite_layout",
    "composite_layout_ids",
    "list_composite_layouts",
]
