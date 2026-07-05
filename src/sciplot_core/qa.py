from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz
import numpy as np


def _raster_visual_qa(pixmap: fitz.Pixmap) -> dict[str, Any]:
    channels = int(pixmap.n)
    if channels <= 0 or pixmap.width <= 0 or pixmap.height <= 0:
        raise ValueError("PDF rasterization produced an invalid pixmap.")
    pixels = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, channels)
    rgb = pixels[:, :, :3] if channels >= 3 else np.repeat(pixels[:, :, :1], 3, axis=2)
    luminance = rgb.astype(float).mean(axis=2)
    ink_mask = luminance < 248.0
    ink_count = int(np.count_nonzero(ink_mask))
    total = int(ink_mask.size)
    if ink_count == 0:
        raise ValueError("PDF raster appears blank.")
    ys, xs = np.where(ink_mask)
    bbox_area = int((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1))
    ink_fraction = ink_count / max(total, 1)
    bbox_fraction = bbox_area / max(total, 1)
    if ink_fraction < 0.0005:
        raise ValueError(f"PDF raster has too little visible ink: {ink_fraction:.6f}.")
    return {
        "raster_width_px": int(pixmap.width),
        "raster_height_px": int(pixmap.height),
        "ink_fraction": round(float(ink_fraction), 6),
        "content_bbox_fraction": round(float(bbox_fraction), 6),
        "content_bbox_px": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
    }


def _pdf_info(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        raise ValueError(f"{path} is missing or empty.")
    with fitz.open(path) as document:
        page_count = document.page_count
        if page_count <= 0:
            raise ValueError(f"{path} has no pages.")
        page = document.load_page(0)
        pixmap = page.get_pixmap(alpha=False, matrix=fitz.Matrix(1.0, 1.0))
        if not pixmap.samples:
            raise ValueError(f"{path} could not be rasterized.")
        visual_qa = _raster_visual_qa(pixmap)
        rect = page.rect
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "page_count": page_count,
        "media_box_pt": [round(float(rect.width), 3), round(float(rect.height), 3)],
        "visual_qa": visual_qa,
    }


def run_qa(output_dir: Path, *, goldens_dir: Path | None = None, require_all_goldens: bool = False) -> dict[str, Any]:
    pdfs = sorted(output_dir.rglob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDF outputs found in {output_dir}.")
    pdf_reports = [_pdf_info(path) for path in pdfs]
    reports_by_name = {Path(report["path"]).name: report for report in pdf_reports}
    golden_reports: list[dict[str, Any]] = []
    skipped_goldens: list[str] = []
    if goldens_dir is not None and goldens_dir.exists():
        for path in sorted(goldens_dir.glob("*.json")):
            golden = json.loads(path.read_text(encoding="utf-8"))
            if golden.get("kind") == "pdf_media_box":
                filename = str(golden["filename"])
                actual = reports_by_name.get(filename)
                if actual is None:
                    if require_all_goldens:
                        raise ValueError(f"Golden media box target {filename} was not rendered.")
                    skipped_goldens.append(filename)
                    continue
                expected = [float(item) for item in golden["media_box_pt"]]
                observed = [float(item) for item in actual["media_box_pt"]]
                tolerance = float(golden.get("tolerance_pt", 0.5))
                deltas = [abs(left - right) for left, right in zip(observed, expected, strict=True)]
                if any(delta > tolerance for delta in deltas):
                    raise ValueError(
                        f"{filename} media box drifted: observed={observed}, expected={expected}, "
                        f"tolerance_pt={tolerance}."
                    )
            golden_reports.append(golden)
    return {
        "status": "passed",
        "pdf_count": len(pdf_reports),
        "pdfs": pdf_reports,
        "goldens_checked": len(golden_reports),
        "goldens_skipped": skipped_goldens,
    }


__all__ = ["run_qa"]
