"""Validate one-to-one PDF and TIFF figure pairings."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.policy import (
    canonical_figure_stem,
)


def _delivery_figure_pairing(figure_records: list[dict[str, Any]]) -> dict[str, Any]:
    pdf_index: dict[str, list[str]] = {}
    tiff_index: dict[str, list[str]] = {}
    invalid_tiff_names: list[str] = []
    for record in figure_records:
        path = Path(str(record["path"]))
        if path.suffix.casefold() == ".pdf":
            pdf_index.setdefault(canonical_figure_stem(path), []).append(str(path))
        elif path.suffix.casefold() in {".tif", ".tiff"}:
            tiff_index.setdefault(canonical_figure_stem(path), []).append(str(path))
            if not path.name.casefold().endswith("_300dpi.tiff"):
                invalid_tiff_names.append(str(path))

    pdf_stems = set(pdf_index)
    tiff_stems = set(tiff_index)
    missing_tiffs = sorted(pdf_stems - tiff_stems)
    orphan_tiffs = sorted(tiff_stems - pdf_stems)
    duplicate_pdfs = {
        stem: paths for stem, paths in pdf_index.items() if len(paths) != 1
    }
    duplicate_tiffs = {
        stem: paths for stem, paths in tiff_index.items() if len(paths) != 1
    }
    passed = (
        bool(pdf_index)
        and bool(tiff_index)
        and not any(
            (
                missing_tiffs,
                orphan_tiffs,
                duplicate_pdfs,
                duplicate_tiffs,
                invalid_tiff_names,
            )
        )
    )
    return {
        "passed": passed,
        "pdf_stems": sorted(pdf_stems),
        "tiff_stems": sorted(tiff_stems),
        "missing_tiffs": missing_tiffs,
        "orphan_tiffs": orphan_tiffs,
        "duplicate_pdfs": duplicate_pdfs,
        "duplicate_tiffs": duplicate_tiffs,
        "invalid_tiff_names": invalid_tiff_names,
    }
