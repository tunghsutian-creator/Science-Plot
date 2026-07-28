"""Inspect embedded rasters, strokes, and vector colors."""

from __future__ import annotations

from typing import Any
import fitz


def _embedded_raster_info(document: fitz.Document) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for page_index, page in enumerate(document):
        for info in page.get_image_info(xrefs=True):
            bbox = info.get("bbox")
            if not isinstance(bbox, tuple | list) or len(bbox) != 4:
                continue
            width_pt = max(float(bbox[2]) - float(bbox[0]), 0.0)
            height_pt = max(float(bbox[3]) - float(bbox[1]), 0.0)
            width_px = int(info.get("width") or 0)
            height_px = int(info.get("height") or 0)
            effective_x = width_px * 72.0 / width_pt if width_pt > 0 else None
            effective_y = height_px * 72.0 / height_pt if height_pt > 0 else None
            images.append(
                {
                    "page": page_index + 1,
                    "xref": int(info.get("xref") or 0),
                    "width_px": width_px,
                    "height_px": height_px,
                    "placed_width_pt": round(width_pt, 3),
                    "placed_height_pt": round(height_pt, 3),
                    "effective_dpi": (
                        round(min(effective_x, effective_y), 3)
                        if effective_x is not None and effective_y is not None
                        else None
                    ),
                }
            )
    return images


def _stroke_info(document: fitz.Document) -> dict[str, Any]:
    widths = [
        float(drawing.get("width"))
        for page in document
        for drawing in page.get_drawings()
        if drawing.get("width") is not None and float(drawing.get("width")) > 0
    ]
    return {
        "coverage": "partial",
        "reason": "PDF strokes are measurable, but Veusz data curves may be exported as filled paths.",
        "measured_count": len(widths),
        "minimum_width_pt": round(min(widths), 3) if widths else None,
        "maximum_width_pt": round(max(widths), 3) if widths else None,
        "widths_pt": sorted({round(width, 3) for width in widths}),
    }


def _vector_color_info(document: fitz.Document) -> dict[str, Any]:
    colors: list[dict[str, Any]] = []
    for page_index, page in enumerate(document):
        for drawing in page.get_drawings():
            for role in ("color", "fill"):
                value = drawing.get(role)
                if not isinstance(value, tuple | list) or len(value) < 3:
                    continue
                rgb = [round(float(channel), 6) for channel in value[:3]]
                colors.append({"page": page_index + 1, "role": role, "rgb": rgb})
    unique = sorted({tuple(item["rgb"]) for item in colors})
    return {
        "occurrence_count": len(colors),
        "unique_rgb": [list(value) for value in unique],
    }
