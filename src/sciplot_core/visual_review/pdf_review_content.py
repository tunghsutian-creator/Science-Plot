"""Bounded page-reference evidence; pixels confer no scientific or edit authority."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, cast

import pymupdf

from .pdf_annotations import _OpenPDF, inspect_pdf_annotations
from .pdf_review_files import MAX_PDF_BYTES

MAX_PAGES = 16
MAX_PIXELS = 16_000_000
MAX_ANNOTATIONS = 100
MAX_GEOMETRY_POINTS = 4096


def _geometry_points(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    if len(value) == 2 and all(isinstance(coordinate, int | float) for coordinate in value):
        return 1
    return sum(_geometry_points(member) for member in value)


def review_content(data: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("PDF review exceeds 32 MiB.")
    # The existing reader owns standard-annotation/encryption semantics. No
    # embedded metadata, attachment, link or JavaScript is treated as authority.
    pages, total_pixels = [], 0
    with cast(_OpenPDF, pymupdf.open)(stream=data, filetype="pdf") as document:
        if document.page_count > MAX_PAGES:
            raise ValueError("PDF review is limited to 16 pages.")
        # Reject encrypted PDFs before rendering, including empty passwords.
        if document.needs_pass or document.is_encrypted or document.metadata.get("encryption"):
            raise ValueError("Encrypted PDF references are not supported.")
        for page in document:
            width, height = page.rect.width, page.rect.height
            total_pixels += (int(width) + 1) * (int(height) + 1)
            if width <= 0 or height <= 0 or total_pixels > MAX_PIXELS:
                raise ValueError("PDF review exceeds the 16-million-pixel page-reference budget.")
            pixmap = page.get_pixmap(dpi=72, colorspace=pymupdf.csRGB, alpha=True, annots=False)
            pages.append({"rect_pt": list(page.rect), "media_box_pt": list(page.mediabox),
                          "crop_box_pt": list(page.cropbox), "rotation": page.rotation,
                          "pixels": [pixmap.width, pixmap.height], "sha256": sha256(pixmap.samples).hexdigest()})
    reference = {"kind": "pdf_base_page_reference", "version": 2, "dpi": 72, "pixels": "premultiplied_rgba",
                 "mupdf_version": pymupdf.VersionBind, "pages": pages}
    annotations = inspect_pdf_annotations(data)
    facts, remaining, omitted, geometry_points = [], MAX_ANNOTATIONS, 0, 0
    for page in annotations["pages"]:
        for item in page["annotations"]:
            if remaining == 0:
                omitted += 1
                continue
            info = item["info"]
            text = str(info.get("content") or "")
            facts.append({"page_index": page["page_index"], "type": item["type_name"],
                          "rect_pt": item["rect_pt"], "text": text[:1024],
                          "text_omitted_characters": max(0, len(text) - 1024),
                          "title": str(info.get("title") or "")[:128],
                          "subject": str(info.get("subject") or "")[:128]})
            if "vertices_pt" in item:
                geometry_points += _geometry_points(item["vertices_pt"])
                if geometry_points > MAX_GEOMETRY_POINTS:
                    raise ValueError("PDF review exceeds the 4096-point geometry budget; no partial reference was returned.")
                facts[-1]["vertices_pt"] = item["vertices_pt"]
            if "line_ends" in item:
                facts[-1]["line_ends"] = item["line_ends"]
            remaining -= 1
    return reference, {"annotation_count": annotations["annotation_count"], "annotations": facts,
        "page_count": annotations["page_count"], "pages": [
            {key: page[key] for key in ("page_index", "rect_pt", "media_box_pt", "crop_box_pt", "rotation")}
            for page in annotations["pages"]],
        "page_rect_coordinate_space": annotations["page_rect_coordinate_space"],
        "omitted_annotation_count": omitted, "coordinate_space": annotations["annotation_coordinate_space"],
        "geometry_point_count": geometry_points, "geometry_point_limit": MAX_GEOMETRY_POINTS,
        "all_pdf_annotation_types_enumerated": False, "flattened_marks_supported": False,
        "parser_repaired": annotations["parser_repaired"], "trust": "untrusted_reference_only"}
