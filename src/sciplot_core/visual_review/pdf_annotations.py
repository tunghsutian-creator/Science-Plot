"""Read PDF annotation facts from bytes, without granting editing authority.

This leaf neither captures files nor binds projects, revisions, scientific data,
permissions or outbound AI context. PyMuPDF's annotation iterator can omit unknown
PDF subtypes, links and form widgets. Empty results therefore establish neither
the absence of other PDF annotations nor the absence of flattened visual marks.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Protocol, cast

import pymupdf


class _OpenPDF(Protocol):
    def __call__(self, *, stream: bytes, filetype: str) -> pymupdf.Document: ...


def _geometry_lists(value: Any) -> Any:
    """Detach native point/Ink sequences without rounding their numeric values."""
    return [_geometry_lists(item) for item in value] if isinstance(value, (list, tuple)) else value


def _annotation_facts(annotation: pymupdf.Annot) -> dict[str, Any]:
    code, name, *_extra = annotation.type
    result = {"xref": annotation.xref, "type_code": code, "type_name": name,
              "rect_pt": list(annotation.rect), "info": annotation.info,
              "flags": annotation.flags}
    vertices, line_ends = annotation.vertices, annotation.line_ends
    if vertices is not None:
        result["vertices_pt"] = _geometry_lists(vertices)
    if line_ends is not None:
        result["line_ends"] = list(line_ends)
    return result


def inspect_pdf_annotations(pdf_bytes: bytes, *, max_pages: int | None = None,
                            max_page_area: int | None = None) -> dict[str, Any]:
    """Return local reference facts, never a figure command or completeness claim.

    Page indices are zero-based. Annotation rectangles and vertices use PyMuPDF's
    unrotated page coordinates in points, not scientific data coordinates.
    ``page.rect_pt`` alone describes the rotated visible page; media/crop boxes
    retain the library's unrotated coordinates. No geometry is rounded or mapped
    to a plot object. The caller owns file capture, resource limits and disclosure.

    No PDF is written, rasterized or OCRed. Links, actions, JavaScript and embedded
    payloads are not followed or read. Encrypted references are rejected even when
    their empty user password would allow the library to open them automatically.
    """
    if not isinstance(pdf_bytes, bytes):
        raise TypeError("PDF reference input must be immutable bytes.")
    try:
        # PyMuPDF's Document constructor is untyped; declare only the byte-open
        # signature used at this library boundary, without weakening our gate.
        with cast(_OpenPDF, pymupdf.open)(stream=pdf_bytes, filetype="pdf") as document:
            if not document.is_pdf:
                raise ValueError("PDF reference input must contain a PDF document.")
            if document.needs_pass or document.is_encrypted or document.metadata.get("encryption"):
                raise ValueError("Encrypted PDF references are not supported.")
            if document.page_count < 1:
                raise ValueError("PDF references require at least one page.")
            if max_pages is not None and document.page_count > max_pages:
                raise ValueError(f"PDF review is limited to {max_pages} pages.")
            if max_page_area is not None:
                total_area = 0
                for page in document:
                    width, height = page.rect.width, page.rect.height
                    total_area += (int(width) + 1) * (int(height) + 1)
                    if width <= 0 or height <= 0 or total_area > max_page_area:
                        raise ValueError("PDF review exceeds the 16-million-pixel page-reference budget.")
            pages = []
            for page in document:
                pages.append({
                    "page_index": page.number,
                    "rect_pt": list(page.rect),
                    "media_box_pt": list(page.mediabox),
                    "crop_box_pt": list(page.cropbox),
                    "rotation": page.rotation,
                    "pdf_annots_entry_type": document.xref_get_key(page.xref, "Annots")[0],
                    "annotations": [_annotation_facts(annotation) for annotation in page.annots()],
                })
            return {
                "kind": "sciplot_pdf_review_annotations", "version": 1,
                "scope": "pymupdf_enumerated_review_annotations",
                "sha256": sha256(pdf_bytes).hexdigest(), "size_bytes": len(pdf_bytes),
                "page_count": len(pages),
                "annotation_count": sum(len(page["annotations"]) for page in pages),
                "annotation_coordinate_space": "pymupdf_unrotated_page_points",
                "page_rect_coordinate_space": "pymupdf_rotated_visible_page_points",
                "visual_marks_evaluated": False,
                "all_pdf_annotation_types_enumerated": False,
                "parser_repaired": document.is_repaired,
                "pages": pages,
            }
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise ValueError("PDF reference bytes are malformed or unreadable.") from exc
