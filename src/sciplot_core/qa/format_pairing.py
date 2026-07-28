"""Validate required export formats and canonical PDF/TIFF pairing."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_io import read_json_object
from sciplot_core.policy import canonical_export_format, canonical_figure_stem


def _normalized_export_format(value: object) -> str | None:
    try:
        normalized = canonical_export_format(value, allow_legacy=True)
    except ValueError:
        return None
    return normalized if normalized in {"pdf", "tiff_300"} else None


def _required_export_formats(
    output_dir: Path, profile: dict[str, Any]
) -> dict[str, Any]:
    required = {"pdf"}
    sources = ["qa_pdf_contract"]

    profile_formats = profile.get("required_formats")
    if not isinstance(profile_formats, list):
        formats_block = (
            profile.get("formats") if isinstance(profile.get("formats"), dict) else {}
        )
        profile_formats = formats_block.get("required")
    if isinstance(profile_formats, list):
        sources.append("publication_profile")
        required.update(
            normalized
            for value in profile_formats
            if (normalized := _normalized_export_format(value)) is not None
        )

    request_payload = read_json_object(output_dir / "request_snapshot.json")
    if request_payload is None:
        manifest = read_json_object(output_dir / "manifest.json")
        request_payload = (
            manifest.get("request") if isinstance(manifest, dict) else None
        )
    if isinstance(request_payload, dict) and isinstance(
        request_payload.get("exports"), list
    ):
        sources.append("request_exports")
        required.update(
            normalized
            for value in request_payload["exports"]
            if (normalized := _normalized_export_format(value)) is not None
        )
    return {"formats": sorted(required), "sources": sources}


def _canonical_pairing_report(
    pdfs: list[dict[str, Any]],
    tiffs: list[dict[str, Any]],
    *,
    required_formats: set[str],
) -> dict[str, Any]:
    pdf_index: dict[str, list[str]] = {}
    tiff_index: dict[str, list[str]] = {}
    for report in pdfs:
        pdf_index.setdefault(canonical_figure_stem(report["path"]), []).append(
            str(report["path"])
        )
    for report in tiffs:
        tiff_index.setdefault(canonical_figure_stem(report["path"]), []).append(
            str(report["path"])
        )

    pdf_stems = set(pdf_index)
    tiff_stems = set(tiff_index)
    tiff_required = "tiff_300" in required_formats
    pairing_expected = tiff_required or bool(tiffs)
    missing_tiffs = sorted(pdf_stems - tiff_stems) if pairing_expected else []
    orphan_tiffs = sorted(tiff_stems - pdf_stems)
    duplicate_pdfs = {
        stem: paths for stem, paths in pdf_index.items() if len(paths) != 1
    }
    duplicate_tiffs = {
        stem: paths for stem, paths in tiff_index.items() if len(paths) != 1
    }
    required_missing = []
    if "pdf" in required_formats and not pdfs:
        required_missing.append("pdf")
    if tiff_required and not tiffs:
        required_missing.append("tiff_300")
    passed = not any(
        (missing_tiffs, orphan_tiffs, duplicate_pdfs, duplicate_tiffs, required_missing)
    )
    return {
        "passed": passed,
        "pairing_expected": pairing_expected,
        "required_formats": sorted(required_formats),
        "pdf_stems": sorted(pdf_stems),
        "tiff_stems": sorted(tiff_stems),
        "missing_tiffs": missing_tiffs,
        "orphan_tiffs": orphan_tiffs,
        "duplicate_pdfs": duplicate_pdfs,
        "duplicate_tiffs": duplicate_tiffs,
        "required_missing": required_missing,
    }
