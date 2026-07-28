"""Inspect PDF font resources and visible text objects."""

from __future__ import annotations

import re
from typing import Any
import fitz


def _font_resource_info(document: fitz.Document) -> list[dict[str, Any]]:
    resources: dict[int, dict[str, Any]] = {}
    for page in document:
        for font in page.get_fonts(full=True):
            xref = int(font[0])
            if xref in resources:
                continue
            content = b""
            try:
                _basename, _extension, _font_type, content = document.extract_font(xref)
            except Exception:
                content = b""
            resources[xref] = {
                "xref": xref,
                "extension": str(font[1]),
                "type": str(font[2]),
                "base_font": str(font[3]),
                "resource_name": str(font[4]),
                "encoding": str(font[5]),
                "embedded": bool(content),
                "embedded_size_bytes": len(content),
            }
    return list(resources.values())


def _span_is_visible(span: dict[str, Any], page_rect: fitz.Rect) -> bool:
    alpha = span.get("alpha")
    if alpha is not None and int(alpha) <= 0:
        return False
    bbox = span.get("bbox")
    if isinstance(bbox, tuple | list) and len(bbox) == 4:
        span_rect = fitz.Rect(*(float(value) for value in bbox))
        if span_rect.is_empty or not span_rect.intersects(page_rect):
            return False
    return True


def _span_text_role(
    span: dict[str, Any],
    line_spans: list[dict[str, Any]],
    *,
    line_direction: object = None,
) -> str:
    """Distinguish reduced mathematical scripts from ordinary final-size text."""

    text = str(span.get("text") or "").strip()
    size = float(span.get("size") or 0.0)
    bbox = span.get("bbox")
    origin = span.get("origin")
    if not text or size <= 0.0 or not re.fullmatch(r"[0-9A-Za-z*∗+\-−–]+", text):
        return "ordinary"
    if not isinstance(bbox, tuple | list) or len(bbox) != 4:
        return "ordinary"
    if not isinstance(origin, tuple | list) or len(origin) != 2:
        return "ordinary"
    if not isinstance(line_direction, tuple | list) or len(line_direction) != 2:
        return "ordinary"
    direction_x, direction_y = (float(value) for value in line_direction)
    direction_norm = (direction_x**2 + direction_y**2) ** 0.5
    if direction_norm <= 0.0:
        return "ordinary"
    direction_x /= direction_norm
    direction_y /= direction_norm
    perpendicular_x, perpendicular_y = -direction_y, direction_x
    origin_x, origin_y = (float(value) for value in origin)
    cross_axis_origin = origin_x * perpendicular_x + origin_y * perpendicular_y
    x0, y0, x1, y1 = (float(value) for value in bbox)
    for neighbour in line_spans:
        neighbour_size = float(neighbour.get("size") or 0.0)
        neighbour_bbox = neighbour.get("bbox")
        neighbour_origin = neighbour.get("origin")
        if neighbour is span or size > neighbour_size * 0.8:
            continue
        if not isinstance(neighbour_bbox, tuple | list) or len(neighbour_bbox) != 4:
            continue
        if not isinstance(neighbour_origin, tuple | list) or len(neighbour_origin) != 2:
            continue
        other_x0, other_y0, other_x1, other_y1 = (
            float(value) for value in neighbour_bbox
        )
        horizontal_gap = min(abs(x0 - other_x1), abs(other_x0 - x1))
        horizontal_overlap = min(x1, other_x1) - max(x0, other_x0)
        vertical_gap = min(abs(y0 - other_y1), abs(other_y0 - y1))
        adjacent = bool(
            horizontal_gap <= max(1.0, neighbour_size * 0.25)
            or (
                horizontal_overlap >= -0.5
                and vertical_gap <= max(1.0, neighbour_size * 0.25)
            )
        )
        if not adjacent:
            continue
        other_origin_x, other_origin_y = (float(value) for value in neighbour_origin)
        other_cross_axis_origin = (
            other_origin_x * perpendicular_x + other_origin_y * perpendicular_y
        )
        cross_axis_offset = abs(cross_axis_origin - other_cross_axis_origin)
        if cross_axis_offset >= max(0.75, neighbour_size * 0.12):
            return "math_script"
    return "ordinary"


def _text_object_info(document: fitz.Document) -> dict[str, Any]:
    extracted_spans: list[dict[str, Any]] = []
    visible_spans: list[dict[str, Any]] = []
    plain_text_by_page: list[dict[str, Any]] = []
    for page_index, page in enumerate(document):
        page_text = page.get_text("text")
        plain_text_by_page.append(
            {
                "page": page_index + 1,
                "text": page_text,
                "lines": [
                    line.strip() for line in page_text.splitlines() if line.strip()
                ],
            }
        )
        text = page.get_text("dict")
        for block in text.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_spans = [
                    span for span in line.get("spans", []) if isinstance(span, dict)
                ]
                for span in line_spans:
                    if str(span.get("text") or "").strip():
                        span_record = {
                            "page": page_index + 1,
                            "text": str(span.get("text") or ""),
                            "font": str(span.get("font") or ""),
                            "size": round(float(span.get("size") or 0.0), 3),
                            "bbox": [
                                round(float(value), 3) for value in span.get("bbox", ())
                            ],
                            "role": _span_text_role(
                                span,
                                line_spans,
                                line_direction=line.get("dir"),
                            ),
                        }
                        extracted_spans.append(span_record)
                        if _span_is_visible(span, page.rect):
                            visible_spans.append(span_record)
    sizes = [
        float(span.get("size") or 0.0)
        for span in visible_spans
        if float(span.get("size") or 0.0) > 0
    ]
    ordinary_sizes = [
        float(span.get("size") or 0.0)
        for span in visible_spans
        if span.get("role") != "math_script" and float(span.get("size") or 0.0) > 0
    ]
    math_script_sizes = [
        float(span.get("size") or 0.0)
        for span in visible_spans
        if span.get("role") == "math_script" and float(span.get("size") or 0.0) > 0
    ]
    fonts = sorted(
        {
            str(span.get("font") or "")
            for span in visible_spans
            if str(span.get("font") or "")
        }
    )
    return {
        "text_objects_preserved": bool(visible_spans),
        "span_count": len(visible_spans),
        "extracted_span_count": len(extracted_spans),
        "excluded_invisible_span_count": len(extracted_spans) - len(visible_spans),
        "character_count": sum(
            len(str(span.get("text") or "")) for span in visible_spans
        ),
        "minimum_size_pt": round(min(sizes), 3) if sizes else None,
        "maximum_size_pt": round(max(sizes), 3) if sizes else None,
        "ordinary_minimum_size_pt": round(min(ordinary_sizes), 3)
        if ordinary_sizes
        else None,
        "math_script_minimum_size_pt": round(min(math_script_sizes), 3)
        if math_script_sizes
        else None,
        "sizes_pt": sorted({round(size, 3) for size in sizes}),
        "fonts": fonts,
        "visible_spans": visible_spans,
        "plain_text_by_page": plain_text_by_page,
    }
