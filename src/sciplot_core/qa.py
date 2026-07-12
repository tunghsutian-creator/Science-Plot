from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from PIL import Image

from sciplot_core.publication import resolve_publication_profile


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _canonical_artifacts(output_dir: Path, suffixes: tuple[str, ...]) -> list[Path]:
    figures_dir = output_dir / "figures"
    if figures_dir.exists():
        direct_figures = sorted(
            path
            for path in figures_dir.iterdir()
            if path.is_file() and path.suffix.casefold() in suffixes
        )
        if direct_figures:
            return direct_figures
        figures = sorted(
            path
            for path in figures_dir.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in suffixes
            and not any(part.startswith("_") for part in path.relative_to(figures_dir).parts)
        )
        if figures:
            return figures
    direct = sorted(path for path in output_dir.iterdir() if path.is_file() and path.suffix.casefold() in suffixes)
    if direct:
        return direct
    excluded = {"delivery", "studio", "_veusz", "_sciplot_internal"}
    return sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in suffixes
        and not excluded.intersection(path.relative_to(output_dir).parts)
    )


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalized_export_format(value: object) -> str | None:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    aliases = {
        "pdf": "pdf",
        "tif": "tiff_300",
        "tiff": "tiff_300",
        "tiff300": "tiff_300",
        "tiff_300dpi": "tiff_300",
        "tiff_300": "tiff_300",
    }
    return aliases.get(normalized)


def _required_export_formats(output_dir: Path, profile: dict[str, Any]) -> dict[str, Any]:
    required = {"pdf"}
    sources = ["qa_pdf_contract"]

    profile_formats = profile.get("required_formats")
    if not isinstance(profile_formats, list):
        formats_block = profile.get("formats") if isinstance(profile.get("formats"), dict) else {}
        profile_formats = formats_block.get("required")
    if isinstance(profile_formats, list):
        sources.append("publication_profile")
        required.update(
            normalized for value in profile_formats if (normalized := _normalized_export_format(value)) is not None
        )

    request_payload = _read_json_object(output_dir / "request_snapshot.json")
    if request_payload is None:
        manifest = _read_json_object(output_dir / "manifest.json")
        request_payload = manifest.get("request") if isinstance(manifest, dict) else None
    if isinstance(request_payload, dict) and isinstance(request_payload.get("exports"), list):
        sources.append("request_exports")
        required.update(
            normalized
            for value in request_payload["exports"]
            if (normalized := _normalized_export_format(value)) is not None
        )
    return {"formats": sorted(required), "sources": sources}


def _canonical_figure_stem(path_value: object) -> str:
    stem = Path(str(path_value)).stem
    return re.sub(r"_\d+dpi$", "", stem, flags=re.IGNORECASE).casefold()


def _canonical_pairing_report(
    pdfs: list[dict[str, Any]],
    tiffs: list[dict[str, Any]],
    *,
    required_formats: set[str],
) -> dict[str, Any]:
    pdf_index: dict[str, list[str]] = {}
    tiff_index: dict[str, list[str]] = {}
    for report in pdfs:
        pdf_index.setdefault(_canonical_figure_stem(report["path"]), []).append(str(report["path"]))
    for report in tiffs:
        tiff_index.setdefault(_canonical_figure_stem(report["path"]), []).append(str(report["path"]))

    pdf_stems = set(pdf_index)
    tiff_stems = set(tiff_index)
    tiff_required = "tiff_300" in required_formats
    pairing_expected = tiff_required or bool(tiffs)
    missing_tiffs = sorted(pdf_stems - tiff_stems) if pairing_expected else []
    orphan_tiffs = sorted(tiff_stems - pdf_stems)
    duplicate_pdfs = {stem: paths for stem, paths in pdf_index.items() if len(paths) != 1}
    duplicate_tiffs = {stem: paths for stem, paths in tiff_index.items() if len(paths) != 1}
    required_missing = []
    if "pdf" in required_formats and not pdfs:
        required_missing.append("pdf")
    if tiff_required and not tiffs:
        required_missing.append("tiff_300")
    passed = not any((missing_tiffs, orphan_tiffs, duplicate_pdfs, duplicate_tiffs, required_missing))
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


def _font_resource_info(document: fitz.Document) -> list[dict[str, Any]]:
    resources: dict[int, dict[str, Any]] = {}
    for page in document:
        for font in page.get_fonts(full=True):
            xref = int(font[0])
            if xref in resources:
                continue
            content = b""
            try:
                _basename, _extension, _font_type, content = document.extract_font(xref)
            except Exception:
                content = b""
            resources[xref] = {
                "xref": xref,
                "extension": str(font[1]),
                "type": str(font[2]),
                "base_font": str(font[3]),
                "resource_name": str(font[4]),
                "encoding": str(font[5]),
                "embedded": bool(content),
                "embedded_size_bytes": len(content),
            }
    return list(resources.values())


def _span_is_visible(span: dict[str, Any], page_rect: fitz.Rect) -> bool:
    alpha = span.get("alpha")
    if alpha is not None and int(alpha) <= 0:
        return False
    bbox = span.get("bbox")
    if isinstance(bbox, tuple | list) and len(bbox) == 4:
        span_rect = fitz.Rect(*(float(value) for value in bbox))
        if span_rect.is_empty or not span_rect.intersects(page_rect):
            return False
    return True


def _text_object_info(document: fitz.Document) -> dict[str, Any]:
    extracted_spans: list[dict[str, Any]] = []
    visible_spans: list[dict[str, Any]] = []
    for page in document:
        text = page.get_text("dict")
        for block in text.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if str(span.get("text") or "").strip():
                        extracted_spans.append(span)
                        if _span_is_visible(span, page.rect):
                            visible_spans.append(span)
    sizes = [float(span.get("size") or 0.0) for span in visible_spans if float(span.get("size") or 0.0) > 0]
    fonts = sorted({str(span.get("font") or "") for span in visible_spans if str(span.get("font") or "")})
    return {
        "text_objects_preserved": bool(visible_spans),
        "span_count": len(visible_spans),
        "extracted_span_count": len(extracted_spans),
        "excluded_invisible_span_count": len(extracted_spans) - len(visible_spans),
        "character_count": sum(len(str(span.get("text") or "")) for span in visible_spans),
        "minimum_size_pt": round(min(sizes), 3) if sizes else None,
        "maximum_size_pt": round(max(sizes), 3) if sizes else None,
        "sizes_pt": sorted({round(size, 3) for size in sizes}),
        "fonts": fonts,
    }


def _embedded_raster_info(document: fitz.Document) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for page_index, page in enumerate(document):
        for info in page.get_image_info(xrefs=True):
            bbox = info.get("bbox")
            if not isinstance(bbox, tuple | list) or len(bbox) != 4:
                continue
            width_pt = max(float(bbox[2]) - float(bbox[0]), 0.0)
            height_pt = max(float(bbox[3]) - float(bbox[1]), 0.0)
            width_px = int(info.get("width") or 0)
            height_px = int(info.get("height") or 0)
            effective_x = width_px * 72.0 / width_pt if width_pt > 0 else None
            effective_y = height_px * 72.0 / height_pt if height_pt > 0 else None
            images.append(
                {
                    "page": page_index + 1,
                    "xref": int(info.get("xref") or 0),
                    "width_px": width_px,
                    "height_px": height_px,
                    "placed_width_pt": round(width_pt, 3),
                    "placed_height_pt": round(height_pt, 3),
                    "effective_dpi": (
                        round(min(effective_x, effective_y), 3)
                        if effective_x is not None and effective_y is not None
                        else None
                    ),
                }
            )
    return images


def _stroke_info(document: fitz.Document) -> dict[str, Any]:
    widths = [
        float(drawing.get("width"))
        for page in document
        for drawing in page.get_drawings()
        if drawing.get("width") is not None and float(drawing.get("width")) > 0
    ]
    return {
        "coverage": "partial",
        "reason": "PDF strokes are measurable, but Veusz data curves may be exported as filled paths.",
        "measured_count": len(widths),
        "minimum_width_pt": round(min(widths), 3) if widths else None,
        "maximum_width_pt": round(max(widths), 3) if widths else None,
        "widths_pt": sorted({round(width, 3) for width in widths}),
    }


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
                raise ValueError(f"{path} page {page_index + 1} could not be rasterized.")
            rect = page.rect
            pages.append(
                {
                    "page": page_index + 1,
                    "media_box_pt": [round(float(rect.width), 3), round(float(rect.height), 3)],
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
    first_page = pages[0]
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "page_count": page_count,
        "media_box_pt": first_page["media_box_pt"],
        "physical_size_mm": first_page["physical_size_mm"],
        "pages": pages,
        "text_objects": text_objects,
        "font_resources": fonts,
        "embedded_rasters": embedded_rasters,
        "strokes": strokes,
        "visual_qa": first_page["visual_qa"],
    }


def _tiff_info(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        dpi_value = image.info.get("dpi")
        if isinstance(dpi_value, tuple | list) and len(dpi_value) >= 2:
            dpi = [float(dpi_value[0]), float(dpi_value[1])]
        else:
            dpi = [0.0, 0.0]
        width_px, height_px = image.size
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "pixel_size": [int(width_px), int(height_px)],
        "dpi": [round(dpi[0], 3), round(dpi[1], 3)],
        "physical_size_mm": [
            round(width_px / dpi[0] * 25.4, 3) if dpi[0] > 0 else None,
            round(height_px / dpi[1] * 25.4, 3) if dpi[1] > 0 else None,
        ],
    }


def _check(
    check_id: str,
    *,
    passed: bool,
    actual: Any,
    expected: Any,
    message: str,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "severity": severity,
        "actual": actual,
        "expected": expected,
        "message": message,
    }


def _normalized_font_name(value: str) -> str:
    name = value.split("+", 1)[-1].casefold()
    return "".join(character for character in name if character.isalnum())


_FONT_FAMILY_ALIASES: dict[str, set[str]] = {
    "arial": {
        "arial",
        "arialbold",
        "arialbolditalic",
        "arialbolditalicmt",
        "arialboldmt",
        "arialitalic",
        "arialitalicmt",
        "arialmt",
        "arialregular",
    },
    "helvetica": {
        "helvetica",
        "helveticabold",
        "helveticaboldoblique",
        "helveticaoblique",
        "helveticaregular",
    },
    "liberationsans": {
        "liberationsans",
        "liberationsansbold",
        "liberationsansbolditalic",
        "liberationsansitalic",
        "liberationsansregular",
    },
}


def _font_family_key(value: str) -> str:
    normalized = _normalized_font_name(value)
    for family, aliases in _FONT_FAMILY_ALIASES.items():
        if normalized in aliases:
            return family
    return normalized


def _font_face_key(value: str) -> tuple[str, str]:
    normalized = _normalized_font_name(value)
    family = _font_family_key(value)
    bold = "bold" in normalized
    italic = "italic" in normalized or "oblique" in normalized
    if bold and italic:
        style = "bold_italic"
    elif bold:
        style = "bold"
    elif italic:
        style = "italic"
    else:
        style = "regular"
    return family, style


def _font_allowed(font: str, allowed: list[str]) -> bool:
    family = _font_family_key(font)
    return family in {_font_family_key(candidate) for candidate in allowed}


def _font_embedding_evidence(pdf: dict[str, Any]) -> list[dict[str, Any]]:
    resources = pdf["font_resources"]
    evidence = []
    for used_font in pdf["text_objects"]["fonts"]:
        face_key = _font_face_key(used_font)
        matches = [resource for resource in resources if _font_face_key(resource["base_font"]) == face_key]
        evidence.append(
            {
                "font": used_font,
                "face_key": list(face_key),
                "matched_resources": matches,
                "embedded": bool(matches) and any(bool(resource["embedded"]) for resource in matches),
            }
        )
    return evidence


def _matching_pdf(tiff: dict[str, Any], pdfs: list[dict[str, Any]]) -> dict[str, Any] | None:
    tiff_stem = _canonical_figure_stem(tiff["path"])
    return next((pdf for pdf in pdfs if _canonical_figure_stem(pdf["path"]) == tiff_stem), None)


def _publication_qa(
    *,
    profile: dict[str, Any],
    pdfs: list[dict[str, Any]],
    tiffs: list[dict[str, Any]],
    required_formats: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    required_format_set = set(required_formats["formats"])
    pairing = _canonical_pairing_report(pdfs, tiffs, required_formats=required_format_set)
    checks.append(
        _check(
            "canonical_format_pairs",
            passed=bool(pairing["passed"]),
            actual=pairing,
            expected={
                "required_formats": sorted(required_format_set),
                "cardinality": "one PDF and one TIFF per canonical stem whenever TIFF is required or present",
            },
            message="Canonical PDF/TIFF artifacts must be complete, uniquely named, and paired one-to-one.",
        )
    )

    page_counts = [int(pdf["page_count"]) for pdf in pdfs]
    single_page_passed = all(count == 1 for count in page_counts)
    checks.append(
        _check(
            "single_page_pdf",
            passed=single_page_passed,
            actual=page_counts,
            expected=1,
            message="Each canonical figure PDF must contain exactly one fully inspected page.",
        )
    )

    page = profile.get("page") if isinstance(profile.get("page"), dict) else {}
    allowed_widths = [float(value) for value in page.get("allowed_widths_mm", [])]
    width_tolerance = float(page.get("width_tolerance_mm") or 0.5)
    maximum_height = float(page.get("maximum_height_mm") or float("inf"))
    observed_sizes = [page_info["physical_size_mm"] for pdf in pdfs for page_info in pdf["pages"]]
    size_passed = all(
        any(abs(float(size[0]) - width) <= width_tolerance for width in allowed_widths)
        and float(size[1]) <= maximum_height + width_tolerance
        for size in observed_sizes
    )
    checks.append(
        _check(
            "physical_size",
            passed=size_passed,
            actual=observed_sizes,
            expected={"allowed_widths_mm": allowed_widths, "maximum_height_mm": maximum_height},
            message="Final PDF page size must match a profile width and remain below the maximum height.",
        )
    )

    typography = profile.get("typography") if isinstance(profile.get("typography"), dict) else {}
    text_passed = all(bool(pdf["text_objects"]["text_objects_preserved"]) for pdf in pdfs)
    checks.append(
        _check(
            "text_objects_preserved",
            passed=text_passed,
            actual=[pdf["text_objects"]["character_count"] for pdf in pdfs],
            expected="extractable text objects",
            message="Figure labels must remain PDF text objects rather than outlined or raster-only text.",
        )
    )
    embedded_fonts = [evidence for pdf in pdfs for evidence in _font_embedding_evidence(pdf)]
    fonts_embedded = bool(embedded_fonts) and all(bool(evidence["embedded"]) for evidence in embedded_fonts)
    checks.append(
        _check(
            "fonts_embedded",
            passed=fonts_embedded,
            actual=embedded_fonts,
            expected=True,
            message="Every visible PDF text face used by the figure must map to an embedded font resource.",
        )
    )
    allowed_fonts = [str(value) for value in typography.get("allowed_font_families", [])]
    used_fonts = sorted({font for pdf in pdfs for font in pdf["text_objects"]["fonts"]})
    fonts_allowed = bool(used_fonts) and all(_font_allowed(font, allowed_fonts) for font in used_fonts)
    checks.append(
        _check(
            "font_families",
            passed=fonts_allowed,
            actual=used_fonts,
            expected=allowed_fonts,
            message="PDF text must use one of the profile's approved font families.",
        )
    )
    minimum_size = float(typography.get("minimum_text_size_pt") or 0.0)
    maximum_size = float(typography.get("maximum_text_size_pt") or float("inf"))
    observed_minima = [pdf["text_objects"]["minimum_size_pt"] for pdf in pdfs]
    observed_maxima = [pdf["text_objects"]["maximum_size_pt"] for pdf in pdfs]
    text_size_passed = all(
        minimum is not None
        and maximum is not None
        and float(minimum) >= minimum_size - 0.01
        and float(maximum) <= maximum_size + 0.01
        for minimum, maximum in zip(observed_minima, observed_maxima, strict=True)
    )
    checks.append(
        _check(
            "text_size_range",
            passed=text_size_passed,
            actual={"minimum_pt": observed_minima, "maximum_pt": observed_maxima},
            expected={"minimum_pt": minimum_size, "maximum_pt": maximum_size},
            message="Actual PDF text sizes must stay within the final-size profile range.",
        )
    )

    minimum_raster_dpi = float(profile.get("raster", {}).get("minimum_effective_dpi") or 300.0)
    embedded_images = [image for pdf in pdfs for image in pdf["embedded_rasters"]]
    embedded_dpi_passed = all(
        image.get("effective_dpi") is not None and float(image["effective_dpi"]) >= minimum_raster_dpi - 0.5
        for image in embedded_images
    )
    checks.append(
        _check(
            "embedded_raster_effective_dpi",
            passed=embedded_dpi_passed,
            actual=embedded_images,
            expected={"minimum_dpi": minimum_raster_dpi},
            message="Any raster embedded in a PDF must retain sufficient effective resolution at placed size.",
        )
    )

    tiff_required = "tiff_300" in required_format_set
    tiff_dpi_passed = (not tiff_required or bool(tiffs)) and all(
        min(tiff["dpi"]) >= minimum_raster_dpi - 0.5 for tiff in tiffs
    )
    checks.append(
        _check(
            "tiff_dpi",
            passed=tiff_dpi_passed,
            actual=[tiff["dpi"] for tiff in tiffs],
            expected={"minimum_dpi": minimum_raster_dpi},
            message="Delivered TIFF previews must retain the declared publication-resolution metadata.",
        )
    )
    tiff_size_pairs = []
    tiff_size_passed = bool(pairing["passed"])
    for tiff in tiffs:
        pdf = _matching_pdf(tiff, pdfs)
        if pdf is None:
            tiff_size_passed = False
            continue
        pair = {"tiff": tiff["physical_size_mm"], "pdf": pdf["physical_size_mm"]}
        tiff_size_pairs.append(pair)
        if any(value is None for value in tiff["physical_size_mm"]):
            tiff_size_passed = False
        else:
            tiff_size_passed = tiff_size_passed and all(
                abs(float(left) - float(right)) <= width_tolerance
                for left, right in zip(tiff["physical_size_mm"], pdf["physical_size_mm"], strict=True)
            )
    checks.append(
        _check(
            "tiff_pdf_physical_size_match",
            passed=tiff_size_passed,
            actual=tiff_size_pairs,
            expected={"tolerance_mm": width_tolerance},
            message="TIFF and PDF exports of the same figure must describe the same physical size.",
        )
    )

    stroke_profile = profile.get("strokes") if isinstance(profile.get("strokes"), dict) else {}
    stroke_ranges = [pdf["strokes"] for pdf in pdfs]
    minimum_stroke = float(stroke_profile.get("minimum_width_pt") or 0.0)
    maximum_stroke = float(stroke_profile.get("maximum_width_pt") or float("inf"))
    stroke_passed = all(
        stroke["minimum_width_pt"] is None
        or (
            float(stroke["minimum_width_pt"]) >= minimum_stroke - 0.01
            and float(stroke["maximum_width_pt"]) <= maximum_stroke + 0.01
        )
        for stroke in stroke_ranges
    )
    checks.append(
        _check(
            "stroke_range_partial",
            passed=stroke_passed,
            actual=stroke_ranges,
            expected={"minimum_pt": minimum_stroke, "maximum_pt": maximum_stroke},
            message=(
                "Measured PDF strokes should fit the profile; filled Veusz curve paths remain a documented limitation."
            ),
            severity="warning",
        )
    )

    integrity = profile.get("integrity") if isinstance(profile.get("integrity"), dict) else {}
    integrity_passed = (
        integrity.get("scientific_outcome_agnostic") is True
        and integrity.get("significance_required") is False
        and integrity.get("silent_data_omission_allowed") is False
    )
    checks.append(
        _check(
            "scientific_integrity_policy",
            passed=integrity_passed,
            actual=integrity,
            expected={
                "scientific_outcome_agnostic": True,
                "significance_required": False,
                "silent_data_omission_allowed": False,
            },
            message="Publication QA must never require a significant, separated, or visually exciting result.",
        )
    )
    blocking_failures = [check for check in checks if check["status"] == "failed" and check["severity"] == "error"]
    checked_constraints_passed = not blocking_failures
    unchecked_constraints = [
        "rendered_colour_vision_and_grayscale_accessibility",
        "semantic_panel_and_required_label_inventory",
        "complete_stroke_coverage_for_filled_veusz_paths",
    ]
    return {
        "kind": "sciplot_publication_qa",
        "version": 1,
        "status": "passed" if checked_constraints_passed else "needs_revision",
        "checked_constraints_passed": checked_constraints_passed,
        "coverage_complete": False,
        "journal_compliance_established": False,
        "journal_compliance_status": "not_established_incomplete_coverage",
        "status_semantics": (
            "passed means only the implemented constraints passed; it is not a claim of journal compliance"
        ),
        "profile": profile,
        "required_formats": required_formats,
        "checks": checks,
        "blocking_check_ids": [check["id"] for check in blocking_failures],
        "limitations": [
            "PDF stroke inspection is partial because Veusz may export data curves as filled paths.",
            "Colour-vision simulation and semantic non-colour encoding require renderer/spec evidence in a later gate.",
            "Expected panel labels and complete semantic text inventory are not yet reconciled against the PDF.",
        ],
        "unchecked_constraints": unchecked_constraints,
        "invariants": {
            "scientific_outcome_agnostic": True,
            "effect_size_gate_applied": False,
            "significance_gate_applied": False,
        },
    }


def run_qa(
    output_dir: Path,
    *,
    goldens_dir: Path | None = None,
    require_all_goldens: bool = False,
    publication_profile: str | Path | dict[str, Any] | None = None,
    strict_publication: bool = False,
) -> dict[str, Any]:
    if publication_profile is None:
        discovered_profile = output_dir / "journal_profile.json"
        if discovered_profile.exists():
            publication_profile = discovered_profile
    pdfs = _canonical_artifacts(output_dir, (".pdf",))
    if not pdfs:
        raise ValueError(f"No PDF outputs found in {output_dir}.")
    pdf_reports = [_pdf_info(path) for path in pdfs]
    tiff_reports = [_tiff_info(path) for path in _canonical_artifacts(output_dir, (".tif", ".tiff"))]
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
    profile = resolve_publication_profile(publication_profile)
    required_formats = _required_export_formats(output_dir, profile) if profile else None
    publication = (
        _publication_qa(
            profile=profile,
            pdfs=pdf_reports,
            tiffs=tiff_reports,
            required_formats=required_formats,
        )
        if profile and required_formats
        else None
    )
    status = "passed"
    if strict_publication and publication is not None and publication["status"] != "passed":
        status = "failed"
    payload = {
        "kind": "sciplot_artifact_qa",
        "version": 2,
        "status": status,
        "pdf_count": len(pdf_reports),
        "pdfs": pdf_reports,
        "tiff_count": len(tiff_reports),
        "tiffs": tiff_reports,
        "goldens_checked": len(golden_reports),
        "goldens_skipped": skipped_goldens,
        "scientific_outcome_agnostic": True,
    }
    if publication is not None:
        payload["publication"] = publication
        payload["publication_strict"] = bool(strict_publication)
    return payload


__all__ = ["run_qa"]
