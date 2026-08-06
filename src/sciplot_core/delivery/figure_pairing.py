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
    pdf_figure_ids: dict[str, list[str]] = {}
    tiff_figure_ids: dict[str, list[str]] = {}
    invalid_tiff_names: list[str] = []
    figure_formats: dict[str, list[str]] = {}
    figure_stems: dict[str, list[str]] = {}
    unidentified_paths: list[str] = []
    for record in figure_records:
        path = Path(str(record["path"]))
        figure_id = str(record.get("figure_id") or "").strip()
        stem = canonical_figure_stem(path)
        export_format = str(record.get("export_format") or "").strip()
        if not export_format:
            export_format = (
                "pdf"
                if path.suffix.casefold() == ".pdf"
                else "tiff_300"
                if path.name.casefold().endswith("_300dpi.tiff")
                else "tiff"
            )
        if figure_id:
            figure_formats.setdefault(figure_id, []).append(export_format)
            figure_stems.setdefault(figure_id, []).append(stem)
        else:
            unidentified_paths.append(str(path))
        if path.suffix.casefold() == ".pdf":
            pdf_index.setdefault(stem, []).append(str(path))
            pdf_figure_ids.setdefault(stem, []).append(figure_id)
        elif path.suffix.casefold() in {".tif", ".tiff"}:
            tiff_index.setdefault(stem, []).append(str(path))
            tiff_figure_ids.setdefault(stem, []).append(figure_id)
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
    figure_id_pairing_mismatches = {
        stem: {
            "pdf_figure_ids": sorted(pdf_figure_ids.get(stem, [])),
            "tiff_figure_ids": sorted(tiff_figure_ids.get(stem, [])),
        }
        for stem in sorted(pdf_stems | tiff_stems)
        if {
            figure_id
            for figure_id in [
                *pdf_figure_ids.get(stem, []),
                *tiff_figure_ids.get(stem, []),
            ]
            if figure_id
        }
        and (
            len(set(pdf_figure_ids.get(stem, []))) != 1
            or len(set(tiff_figure_ids.get(stem, []))) != 1
            or set(pdf_figure_ids.get(stem, [])) != set(tiff_figure_ids.get(stem, []))
        )
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
                figure_id_pairing_mismatches,
            )
        )
    )
    complete_figure_ids = sorted(
        figure_id
        for figure_id, formats in figure_formats.items()
        if formats.count("pdf") == 1
        and formats.count("tiff_300") == 1
        and len(set(figure_stems.get(figure_id, []))) == 1
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
        "figure_id_pairing_mismatches": figure_id_pairing_mismatches,
        "complete_figure_ids": complete_figure_ids,
        "figure_formats": {
            figure_id: sorted(formats)
            for figure_id, formats in sorted(figure_formats.items())
        },
        "figure_stems": {
            figure_id: sorted(stems)
            for figure_id, stems in sorted(figure_stems.items())
        },
        "unidentified_paths": sorted(unidentified_paths),
    }
