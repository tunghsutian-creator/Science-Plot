"""Assemble complete PDF metadata and raster visibility evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import fitz
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.qa.artifacts import (
    _raster_visual_qa,
)

from sciplot_core.qa.pdf_text import (
    _font_resource_info,
    _text_object_info,
)

from sciplot_core.qa.pdf_graphics import (
    _embedded_raster_info,
    _stroke_info,
    _vector_color_info,
)


def _pdf_info(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        raise ValueError(f"{path} is missing or empty.")
    with fitz.open(path) as document:
        page_count = document.page_count
        if page_count <= 0:
            raise ValueError(f"{path} has no pages.")
        pages: list[dict[str, Any]] = []
        for page_index in range(page_count):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(alpha=False, matrix=fitz.Matrix(1.0, 1.0))
            if not pixmap.samples:
                raise ValueError(
                    f"{path} page {page_index + 1} could not be rasterized."
                )
            rect = page.rect
            pages.append(
                {
                    "page": page_index + 1,
                    "media_box_pt": [
                        round(float(rect.width), 3),
                        round(float(rect.height), 3),
                    ],
                    "physical_size_mm": [
                        round(float(rect.width) * 25.4 / 72.0, 3),
                        round(float(rect.height) * 25.4 / 72.0, 3),
                    ],
                    "visual_qa": _raster_visual_qa(pixmap),
                }
            )
        fonts = _font_resource_info(document)
        text_objects = _text_object_info(document)
        embedded_rasters = _embedded_raster_info(document)
        strokes = _stroke_info(document)
        vector_colors = _vector_color_info(document)
    first_page = pages[0]
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "page_count": page_count,
        "media_box_pt": first_page["media_box_pt"],
        "physical_size_mm": first_page["physical_size_mm"],
        "pages": pages,
        "text_objects": text_objects,
        "font_resources": fonts,
        "embedded_rasters": embedded_rasters,
        "strokes": strokes,
        "vector_colors": vector_colors,
        "visual_qa": first_page["visual_qa"],
    }
