"""Measure PDF/TIFF artifacts and build review rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import fitz
from PIL import Image
from sciplot_core.policy import DEFAULT_FIGURE_SIZE

from sciplot_core.visual_review.transaction import (
    PHYSICAL_SIZE_TOLERANCE_MM,
    TIFF_DPI_TOLERANCE,
)


def _parse_size_mm(value: object) -> tuple[float, float]:
    try:
        width, height = str(value).casefold().split("x", maxsplit=1)
        parsed = (float(width), float(height))
        if min(parsed) <= 0:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        width, height = DEFAULT_FIGURE_SIZE.split("x", maxsplit=1)
        return float(width), float(height)


def _round_pair(values: tuple[float, float], *, digits: int = 3) -> list[float]:
    return [round(value, digits) for value in values]


def _size_pair(value: object) -> tuple[float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    try:
        pair = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return pair if min(pair) > 0 else None


def _expected_size_from_manifest(manifest: dict[str, Any]) -> tuple[float, float]:
    layout_quality = (
        manifest.get("layout_quality")
        if isinstance(manifest.get("layout_quality"), dict)
        else {}
    )
    summaries = (
        layout_quality.get("summaries")
        if isinstance(layout_quality.get("summaries"), list)
        else []
    )
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        size = _size_pair(
            summary.get("figure_size_mm") or summary.get("requested_size_mm")
        )
        if size is not None:
            return size
    spec_value = manifest.get("veusz_spec")
    if isinstance(spec_value, str) and spec_value.strip():
        try:
            spec = json.loads(Path(spec_value).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            spec = {}
        size = _size_pair(spec.get("size_mm")) if isinstance(spec, dict) else None
        if size is not None:
            return size
    request = (
        manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    )
    render_options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    return _parse_size_mm(render_options.get("size") or DEFAULT_FIGURE_SIZE)


def _within_tolerance(
    actual: tuple[float, float], expected: tuple[float, float]
) -> bool:
    return all(
        abs(observed - target) <= PHYSICAL_SIZE_TOLERANCE_MM
        for observed, target in zip(actual, expected, strict=True)
    )


def _delivery_figure(
    manifest: dict[str, Any], artifact_format: str
) -> dict[str, Any] | None:
    delivery = (
        manifest.get("delivery_package")
        if isinstance(manifest.get("delivery_package"), dict)
        else {}
    )
    figures = (
        delivery.get("figures") if isinstance(delivery.get("figures"), list) else []
    )
    return next(
        (
            item
            for item in figures
            if isinstance(item, dict)
            and str(item.get("format") or "").casefold() == artifact_format
        ),
        None,
    )


def _pdf_size_mm(path: Path) -> tuple[float, float]:
    with fitz.open(path) as document:
        if document.page_count != 1:
            raise ValueError(
                f"Expected one-page acceptance PDF, found {document.page_count}: {path}"
            )
        rectangle = document[0].rect
        return float(rectangle.width) * 25.4 / 72.0, float(
            rectangle.height
        ) * 25.4 / 72.0


def _tiff_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        dpi_value = image.info.get("dpi")
        if not isinstance(dpi_value, tuple | list) or len(dpi_value) < 2:
            raise ValueError(f"TIFF has no two-axis DPI metadata: {path}")
        dpi = float(dpi_value[0]), float(dpi_value[1])
        if min(dpi) <= 0:
            raise ValueError(f"TIFF has invalid DPI metadata {dpi}: {path}")
        pixels = int(image.width), int(image.height)
        physical = pixels[0] * 25.4 / dpi[0], pixels[1] * 25.4 / dpi[1]
        return {
            "pixels": list(pixels),
            "dpi": _round_pair(dpi),
            "physical_size_mm": _round_pair(physical),
            "mode": image.mode,
            "frame_count": int(getattr(image, "n_frames", 1)),
        }


def _record_for_row(row: dict[str, Any]) -> dict[str, Any]:
    rule_id = str(row.get("rule_id") or "unknown")
    manifest_value = row.get("manifest")
    if not manifest_value:
        return {
            "rule_id": rule_id,
            "status": "not_run",
            "expected_size_mm": None,
            "manifest": None,
            "pdf": None,
            "tiff": None,
            "errors": [],
        }

    manifest_path = Path(str(manifest_value))
    errors: list[str] = []
    record: dict[str, Any] = {
        "rule_id": rule_id,
        "status": "failed",
        "expected_size_mm": None,
        "manifest": str(manifest_path),
        "pdf": None,
        "tiff": None,
        "errors": errors,
    }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"manifest_unreadable: {exc}")
        return record

    expected = _expected_size_from_manifest(manifest)
    record["expected_size_mm"] = _round_pair(expected)

    pdf_item = _delivery_figure(manifest, "pdf")
    tiff_item = _delivery_figure(manifest, "tiff")
    pdf_path = (
        Path(str(pdf_item.get("path"))) if pdf_item and pdf_item.get("path") else None
    )
    tiff_path = (
        Path(str(tiff_item.get("path")))
        if tiff_item and tiff_item.get("path")
        else None
    )

    if pdf_path is None or not pdf_path.exists():
        errors.append("canonical_pdf_missing")
    else:
        try:
            actual_pdf = _pdf_size_mm(pdf_path)
            record["pdf"] = {
                "path": str(pdf_path),
                "physical_size_mm": _round_pair(actual_pdf),
                "within_tolerance": _within_tolerance(actual_pdf, expected),
                "copy_hash_matches": bool(pdf_item.get("copy_hash_matches")),
            }
            if not record["pdf"]["within_tolerance"]:
                errors.append("pdf_physical_size_mismatch")
            if not record["pdf"]["copy_hash_matches"]:
                errors.append("pdf_delivery_hash_mismatch")
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f"pdf_inspection_failed: {exc}")

    if tiff_path is None or not tiff_path.exists():
        errors.append("canonical_tiff_missing")
    else:
        try:
            tiff = _tiff_metadata(tiff_path)
            actual_tiff = tuple(float(value) for value in tiff["physical_size_mm"])
            dpi = tuple(float(value) for value in tiff["dpi"])
            tiff.update(
                {
                    "path": str(tiff_path),
                    "within_tolerance": _within_tolerance(actual_tiff, expected),
                    "dpi_is_300": all(
                        abs(value - 300.0) <= TIFF_DPI_TOLERANCE for value in dpi
                    ),
                    "copy_hash_matches": bool(tiff_item.get("copy_hash_matches")),
                }
            )
            record["tiff"] = tiff
            if not tiff["within_tolerance"]:
                errors.append("tiff_physical_size_mismatch")
            if not tiff["dpi_is_300"]:
                errors.append("tiff_dpi_mismatch")
            if not tiff["copy_hash_matches"]:
                errors.append("tiff_delivery_hash_mismatch")
        except (OSError, ValueError) as exc:
            errors.append(f"tiff_inspection_failed: {exc}")

    record["status"] = "passed" if not errors else "failed"
    return record
