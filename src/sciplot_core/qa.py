from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz


def _pdf_info(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        raise ValueError(f"{path} is missing or empty.")
    with fitz.open(path) as document:
        page_count = document.page_count
        if page_count <= 0:
            raise ValueError(f"{path} has no pages.")
        page = document.load_page(0)
        pixmap = page.get_pixmap(alpha=False, matrix=fitz.Matrix(0.25, 0.25))
        if not pixmap.samples:
            raise ValueError(f"{path} could not be rasterized.")
        rect = page.rect
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "page_count": page_count,
        "media_box_pt": [round(float(rect.width), 3), round(float(rect.height), 3)],
    }


def run_qa(output_dir: Path, *, goldens_dir: Path | None = None) -> dict[str, Any]:
    pdfs = sorted(output_dir.rglob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDF outputs found in {output_dir}.")
    pdf_reports = [_pdf_info(path) for path in pdfs]
    reports_by_name = {Path(report["path"]).name: report for report in pdf_reports}
    golden_reports: list[dict[str, Any]] = []
    if goldens_dir is not None and goldens_dir.exists():
        for path in sorted(goldens_dir.glob("*.json")):
            golden = json.loads(path.read_text(encoding="utf-8"))
            if golden.get("kind") == "pdf_media_box":
                filename = str(golden["filename"])
                actual = reports_by_name.get(filename)
                if actual is None:
                    raise ValueError(f"Golden media box target {filename} was not rendered.")
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
    }


__all__ = ["run_qa"]
