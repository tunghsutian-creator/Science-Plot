"""Observe requested PNG/SVG artifacts without replacing canonical PDF/TIFF QA."""

from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast
from xml.etree import ElementTree

import pymupdf as fitz

from sciplot_core.policy.frame_export import canonical_figure_stem, export_format_from_path, export_suffix
from sciplot_core.qa.artifacts import _canonical_artifacts, _raster_visual_qa
from sciplot_core.qa.raster_inspection import _png_info


class _OpenDocument(Protocol):
    def __call__(self, *, stream: bytes, filetype: str) -> fitz.Document: ...


def _visual_info(path: Path, content: bytes) -> dict[str, Any]:
    if path.suffix.casefold() == ".svg":
        root = ElementTree.fromstring(content)
        if root.tag != "{http://www.w3.org/2000/svg}svg":
            raise ValueError(f"Not a native SVG artifact: {path}")
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] in {"script", "foreignObject"}:
                raise ValueError(f"Active SVG content is not a native figure artifact: {path}")
            if any(key.rsplit("}", 1)[-1] == "href" and not value.startswith(("#", "data:"))
                   for key, value in node.attrib.items()):
                raise ValueError(f"An SVG artifact cannot import external content: {path}")
    with cast(_OpenDocument, fitz.open)(stream=content, filetype=path.suffix.lstrip(".")) as document:
        if document.page_count != 1:
            raise ValueError(f"An exported figure must have one canvas: {path}")
        page = document.load_page(0)
        rectangle = page.rect
        visual = _raster_visual_qa(page.get_pixmap(alpha=False))
    return {"path": str(path), "size_bytes": len(content), "sha256": sha256(content).hexdigest(),
            "media_box_pt": [float(rectangle.width), float(rectangle.height)], "visual_qa": visual}


def additional_export_reports(output_dir: Path, pdfs: list[dict[str, Any]], *, required: set[str]) -> dict[str, list[dict[str, Any]]]:
    """One byte observation supplies canvas, PNG metadata, visibility and hash."""
    pdf_by_stem = {canonical_figure_stem(item["path"]): item for item in pdfs}
    reports: dict[str, list[dict[str, Any]]] = {"pngs": [], "svgs": []}
    by_format: dict[str, list[dict[str, Any]]] = {}
    for path in _canonical_artifacts(output_dir, (".png", ".svg")):
        fmt = export_format_from_path(path)
        if fmt is None:
            continue  # Noncanonical preview.png is not a requested native export.
        content = path.read_bytes()
        report = _visual_info(path, content)
        stem = canonical_figure_stem(path)
        if stem not in pdf_by_stem:
            raise ValueError(f"Additional export has no canonical PDF: {path}")
        pdf = pdf_by_stem[stem]
        if fmt.startswith("png_"):
            raster = _png_info(path, content)
            dpi = export_suffix(fmt)[1]
            assert dpi is not None
            if any(abs(actual - dpi) > 0.5 for actual in raster["dpi"]):
                raise ValueError(f"PNG resolution does not match its explicit export format: {path}")
            # PDF MediaBox uses integer points and native raster size uses
            # integer pixels. Bound those two quantizations, never change the
            # existing PDF/TIFF publication size or scientific tolerances.
            bound = dpi / 72.0 + 1.0
            expected_pixels = [float(point) * dpi / 72.0 for point in pdf["media_box_pt"]]
            if any(abs(actual - expected) > bound for actual, expected in zip(raster["pixel_size"], expected_pixels, strict=True)):
                raise ValueError(f"PNG pixels do not match the same native figure canvas: {path}")
            report.update(raster, pixel_quantization_bound={"pdf_points": 1, "raster_pixels": 1})
            reports["pngs"].append(report)
        else:
            if any(abs(actual - float(expected)) > 1.0 for actual, expected in zip(report["media_box_pt"], pdf["media_box_pt"], strict=True)):
                raise ValueError(f"SVG does not match the same native figure canvas: {path}")
            report["coverage"] = "native byte binding, one canvas and raster visibility; no PDF font or journal claim"
            reports["svgs"].append(report)
        report["export_format"] = fmt
        by_format.setdefault(fmt, []).append(report)
    for fmt in (required | set(by_format)) - {"pdf", "tiff_300"}:
        counts = Counter(canonical_figure_stem(item["path"]) for item in by_format.get(fmt, []))
        if counts != Counter(dict.fromkeys(pdf_by_stem, 1)):
            raise ValueError(f"Requested {fmt} exports do not cover each canonical figure exactly once.")
    return reports
