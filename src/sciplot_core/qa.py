from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import unicodedata
from itertools import combinations
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from PIL import Image

from sciplot_core._utils import file_sha256, read_json_object
from sciplot_core.publication import resolve_publication_profile


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

    request_payload = read_json_object(output_dir / "request_snapshot.json")
    if request_payload is None:
        manifest = read_json_object(output_dir / "manifest.json")
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


def _span_text_role(
    span: dict[str, Any],
    line_spans: list[dict[str, Any]],
    *,
    line_direction: object = None,
) -> str:
    """Distinguish reduced mathematical scripts from ordinary final-size text."""

    text = str(span.get("text") or "").strip()
    size = float(span.get("size") or 0.0)
    bbox = span.get("bbox")
    origin = span.get("origin")
    if not text or size <= 0.0 or not re.fullmatch(r"[0-9A-Za-z*∗+\-−–]+", text):
        return "ordinary"
    if not isinstance(bbox, tuple | list) or len(bbox) != 4:
        return "ordinary"
    if not isinstance(origin, tuple | list) or len(origin) != 2:
        return "ordinary"
    if not isinstance(line_direction, tuple | list) or len(line_direction) != 2:
        return "ordinary"
    direction_x, direction_y = (float(value) for value in line_direction)
    direction_norm = (direction_x**2 + direction_y**2) ** 0.5
    if direction_norm <= 0.0:
        return "ordinary"
    direction_x /= direction_norm
    direction_y /= direction_norm
    perpendicular_x, perpendicular_y = -direction_y, direction_x
    origin_x, origin_y = (float(value) for value in origin)
    cross_axis_origin = (
        origin_x * perpendicular_x + origin_y * perpendicular_y
    )
    x0, y0, x1, y1 = (float(value) for value in bbox)
    for neighbour in line_spans:
        neighbour_size = float(neighbour.get("size") or 0.0)
        neighbour_bbox = neighbour.get("bbox")
        neighbour_origin = neighbour.get("origin")
        if neighbour is span or size > neighbour_size * 0.8:
            continue
        if not isinstance(neighbour_bbox, tuple | list) or len(neighbour_bbox) != 4:
            continue
        if not isinstance(neighbour_origin, tuple | list) or len(neighbour_origin) != 2:
            continue
        other_x0, other_y0, other_x1, other_y1 = (float(value) for value in neighbour_bbox)
        horizontal_gap = min(abs(x0 - other_x1), abs(other_x0 - x1))
        horizontal_overlap = min(x1, other_x1) - max(x0, other_x0)
        vertical_gap = min(abs(y0 - other_y1), abs(other_y0 - y1))
        adjacent = bool(
            horizontal_gap <= max(1.0, neighbour_size * 0.25)
            or (
                horizontal_overlap >= -0.5
                and vertical_gap <= max(1.0, neighbour_size * 0.25)
            )
        )
        if not adjacent:
            continue
        other_origin_x, other_origin_y = (
            float(value) for value in neighbour_origin
        )
        other_cross_axis_origin = (
            other_origin_x * perpendicular_x
            + other_origin_y * perpendicular_y
        )
        cross_axis_offset = abs(cross_axis_origin - other_cross_axis_origin)
        if cross_axis_offset >= max(0.75, neighbour_size * 0.12):
            return "math_script"
    return "ordinary"


def _text_object_info(document: fitz.Document) -> dict[str, Any]:
    extracted_spans: list[dict[str, Any]] = []
    visible_spans: list[dict[str, Any]] = []
    plain_text_by_page: list[dict[str, Any]] = []
    for page_index, page in enumerate(document):
        page_text = page.get_text("text")
        plain_text_by_page.append(
            {
                "page": page_index + 1,
                "text": page_text,
                "lines": [line.strip() for line in page_text.splitlines() if line.strip()],
            }
        )
        text = page.get_text("dict")
        for block in text.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_spans = [span for span in line.get("spans", []) if isinstance(span, dict)]
                for span in line_spans:
                    if str(span.get("text") or "").strip():
                        span_record = {
                            "page": page_index + 1,
                            "text": str(span.get("text") or ""),
                            "font": str(span.get("font") or ""),
                            "size": round(float(span.get("size") or 0.0), 3),
                            "bbox": [round(float(value), 3) for value in span.get("bbox", ())],
                            "role": _span_text_role(
                                span,
                                line_spans,
                                line_direction=line.get("dir"),
                            ),
                        }
                        extracted_spans.append(span_record)
                        if _span_is_visible(span, page.rect):
                            visible_spans.append(span_record)
    sizes = [float(span.get("size") or 0.0) for span in visible_spans if float(span.get("size") or 0.0) > 0]
    ordinary_sizes = [
        float(span.get("size") or 0.0)
        for span in visible_spans
        if span.get("role") != "math_script" and float(span.get("size") or 0.0) > 0
    ]
    math_script_sizes = [
        float(span.get("size") or 0.0)
        for span in visible_spans
        if span.get("role") == "math_script" and float(span.get("size") or 0.0) > 0
    ]
    fonts = sorted({str(span.get("font") or "") for span in visible_spans if str(span.get("font") or "")})
    return {
        "text_objects_preserved": bool(visible_spans),
        "span_count": len(visible_spans),
        "extracted_span_count": len(extracted_spans),
        "excluded_invisible_span_count": len(extracted_spans) - len(visible_spans),
        "character_count": sum(len(str(span.get("text") or "")) for span in visible_spans),
        "minimum_size_pt": round(min(sizes), 3) if sizes else None,
        "maximum_size_pt": round(max(sizes), 3) if sizes else None,
        "ordinary_minimum_size_pt": round(min(ordinary_sizes), 3) if ordinary_sizes else None,
        "math_script_minimum_size_pt": round(min(math_script_sizes), 3) if math_script_sizes else None,
        "sizes_pt": sorted({round(size, 3) for size in sizes}),
        "fonts": fonts,
        "visible_spans": visible_spans,
        "plain_text_by_page": plain_text_by_page,
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


def _vector_color_info(document: fitz.Document) -> dict[str, Any]:
    colors: list[dict[str, Any]] = []
    for page_index, page in enumerate(document):
        for drawing in page.get_drawings():
            for role in ("color", "fill"):
                value = drawing.get(role)
                if not isinstance(value, tuple | list) or len(value) < 3:
                    continue
                rgb = [round(float(channel), 6) for channel in value[:3]]
                colors.append({"page": page_index + 1, "role": role, "rgb": rgb})
    unique = sorted({tuple(item["rgb"]) for item in colors})
    return {
        "occurrence_count": len(colors),
        "unique_rgb": [list(value) for value in unique],
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
        vector_colors = _vector_color_info(document)
    first_page = pages[0]
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "page_count": page_count,
        "media_box_pt": first_page["media_box_pt"],
        "physical_size_mm": first_page["physical_size_mm"],
        "pages": pages,
        "text_objects": text_objects,
        "font_resources": fonts,
        "embedded_rasters": embedded_rasters,
        "strokes": strokes,
        "vector_colors": vector_colors,
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
        "sha256": file_sha256(path),
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


def _candidate_path(value: object, *, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    return resolved if resolved.exists() and resolved.is_file() and resolved.suffix.casefold() == ".vsz" else None


def _discover_veusz_documents(output_dir: Path, explicit: list[Path] | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.extend(path.expanduser().resolve() for path in explicit if path.expanduser().exists())
    manifest = read_json_object(output_dir / "manifest.json")
    if isinstance(manifest, dict):
        values: list[object] = [manifest.get("veusz_document")]
        values.extend(manifest.get("veusz_documents", []) if isinstance(manifest.get("veusz_documents"), list) else [])
        result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
        values.append(result.get("veusz_document"))
        values.extend(result.get("veusz_documents", []) if isinstance(result.get("veusz_documents"), list) else [])
        for value in values:
            candidate = _candidate_path(value, base_dir=output_dir)
            if candidate is not None:
                candidates.append(candidate)
    candidates.extend(sorted((output_dir / "studio").glob("document.vsz")))
    candidates.extend(sorted((output_dir / "figures" / "_veusz").glob("**/studio/document.vsz")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.exists() or not resolved.is_file():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _run_veusz_audit(paths: list[Path]) -> tuple[dict[str, Any] | None, str | None]:
    if not paths:
        return None, "No exact current Veusz document was available for artifact QA."
    from sciplot_core.veusz_runtime import veusz_worker_environment

    command = [
        sys.executable,
        "-m",
        "sciplot_core.veusz_worker",
        "audit-documents",
        *(str(path) for path in paths),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=True,
            env=veusz_worker_environment(),
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            detail = exc.stderr.strip().splitlines()[-1]
        return None, f"Veusz document audit failed: {detail}"
    if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
        return None, "Veusz document audit returned an invalid payload."
    return payload, None


def _publication_intent(output_dir: Path) -> dict[str, Any]:
    intent = read_json_object(output_dir / "publication_intent.json")
    if intent is not None:
        return intent
    request = read_json_object(output_dir / "request_snapshot.json")
    if isinstance(request, dict) and isinstance(request.get("publication_intent"), dict):
        return request["publication_intent"]
    manifest = read_json_object(output_dir / "manifest.json")
    if isinstance(manifest, dict) and isinstance(manifest.get("publication_intent"), dict):
        return manifest["publication_intent"]
    return {}


def _close(left: float, right: float, tolerance: float) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def _bounds_close(actual: object, expected: object, tolerance: float) -> bool:
    return (
        isinstance(actual, list)
        and isinstance(expected, list)
        and len(actual) == len(expected)
        and all(_close(float(left), float(right), tolerance) for left, right in zip(actual, expected, strict=True))
    )


def _fixed_frame_report(audit: dict[str, Any] | None, intent: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(audit, dict):
        return {
            "available": False,
            "coverage_complete": False,
            "passed": False,
            "reason": "exact_current_vsz_audit_unavailable",
            "documents": [],
        }
    from sciplot_core.contract import load_plot_contract, qa_profile
    from sciplot_core.publication import build_composite_layout

    contract = load_plot_contract()
    tolerance = float(qa_profile("alignment").get("frame_tolerance_mm", 0.05))
    expected_margins = {
        "left": float(contract.global_frame.left_margin_mm),
        "right": float(contract.global_frame.right_margin_mm),
        "bottom": float(contract.global_frame.bottom_margin_mm),
        "top": float(contract.global_frame.top_margin_mm),
    }
    documents = [item for item in audit.get("documents", []) if isinstance(item, dict)]
    issues: list[dict[str, Any]] = []
    all_graphs: list[dict[str, Any]] = []
    for document in documents:
        graphs = [item for item in document.get("graphs", []) if isinstance(item, dict)]
        all_graphs.extend(graphs)
        pages = {int(item["page"]): item for item in document.get("pages", []) if isinstance(item, dict)}
        for graph in graphs:
            margins = graph.get("margins_mm") if isinstance(graph.get("margins_mm"), dict) else {}
            margin_errors = {
                side: (
                    abs(float(margins[side]) - expected)
                    if margins.get(side) is not None
                    else float("inf")
                )
                for side, expected in expected_margins.items()
            }
            if any(error > tolerance for error in margin_errors.values()):
                issues.append(
                    {
                        "id": "fixed_publication_frame_misaligned",
                        "path": graph.get("path"),
                        "margin_error_mm": margin_errors,
                    }
                )
            if str(graph.get("aspect") or "Auto").casefold() != "auto":
                issues.append({"id": "fixed_publication_frame_aspect_override", "path": graph.get("path")})
            if graph.get("parent_type") == "page":
                page = pages.get(int(graph.get("page") or 0))
                if page is None or not _bounds_close(graph.get("slot_bounds_mm"), page.get("bounds_mm"), tolerance):
                    issues.append({"id": "standalone_graph_slot_misaligned", "path": graph.get("path")})
        graph_by_path = {str(item.get("path")): item for item in graphs}
        for auxiliary in document.get("auxiliaries", []):
            if not isinstance(auxiliary, dict) or auxiliary.get("type") != "colorbar":
                continue
            graph = graph_by_path.get(str(auxiliary.get("parent_path")))
            bounds = auxiliary.get("bounds_mm")
            frame = graph.get("plot_bounds_mm") if isinstance(graph, dict) else None
            contained = (
                isinstance(bounds, list)
                and isinstance(frame, list)
                and len(bounds) == len(frame) == 4
                and bounds[0] >= frame[0] - tolerance
                and bounds[1] >= frame[1] - tolerance
                and bounds[2] <= frame[2] + tolerance
                and bounds[3] <= frame[3] + tolerance
            )
            if not contained:
                issues.append({"id": "colorbar_outside_standard_graph_frame", "path": auxiliary.get("path")})

    layout_id = str(intent.get("layout_id") or "").strip()
    layout_confirmed = layout_id and str(intent.get("layout_status") or "").casefold() == "confirmed"
    layout_evidence: dict[str, Any] | None = None
    if layout_confirmed:
        figure_layout = intent.get("figure_layout") if isinstance(intent.get("figure_layout"), dict) else {}
        height = float(figure_layout.get("canvas_height_mm") or 55.0)
        layout = build_composite_layout(layout_id, canvas_height_mm=height)
        standalone_single = (
            layout_id == "single_180"
            and len(documents) == 1
            and len(documents[0].get("pages", [])) == 1
            and _bounds_close(
                documents[0]["pages"][0].get("size_mm"),
                [float(layout["nominal_content_width_mm"]), float(layout["canvas_height_mm"])],
                tolerance,
            )
        )
        layout_evidence = {
            "layout_id": layout_id,
            "expected": layout,
            "actual_graphs": all_graphs,
            "assembly_state": (
                "standalone_180_module_for_external_assembly"
                if standalone_single
                else "native_composite_document"
            ),
        }
        if not standalone_single:
            if len(documents) != 1 or len(documents[0].get("pages", [])) != 1:
                issues.append({"id": "composite_requires_one_vsz_page"})
            else:
                page = documents[0]["pages"][0]
                expected_page = [float(layout["canvas_width_mm"]), float(layout["canvas_height_mm"])]
                if not _bounds_close(page.get("size_mm"), expected_page, tolerance):
                    issues.append(
                        {
                            "id": "composite_page_size_mismatch",
                            "actual": page.get("size_mm"),
                            "expected": expected_page,
                        }
                    )
            ordered_graphs = sorted(
                all_graphs,
                key=lambda item: float((item.get("slot_bounds_mm") or [math.inf])[0]),
            )
            slots = [item for item in layout.get("slots", []) if isinstance(item, dict)]
            if len(ordered_graphs) != len(slots):
                issues.append(
                    {
                        "id": "composite_slot_count_mismatch",
                        "actual": len(ordered_graphs),
                        "expected": len(slots),
                    }
                )
            else:
                for graph, slot in zip(ordered_graphs, slots, strict=True):
                    expected_bounds = [
                        float(slot["x_mm"]),
                        0.0,
                        float(slot["x_mm"]) + float(slot["width_mm"]),
                        float(layout["canvas_height_mm"]),
                    ]
                    if not _bounds_close(graph.get("slot_bounds_mm"), expected_bounds, tolerance):
                        issues.append(
                            {
                                "id": "composite_slot_geometry_mismatch",
                                "path": graph.get("path"),
                                "actual": graph.get("slot_bounds_mm"),
                                "expected": expected_bounds,
                            }
                        )
    else:
        for document in documents:
            pages = [item for item in document.get("pages", []) if isinstance(item, dict)]
            graphs = [item for item in document.get("graphs", []) if isinstance(item, dict)]
            graph_counts_by_page = {
                int(page.get("page") or 0): sum(
                    int(graph.get("page") or 0) == int(page.get("page") or 0)
                    for graph in graphs
                )
                for page in pages
            }
            standalone_shape = (
                len(pages) == len(graphs)
                and all(count == 1 for count in graph_counts_by_page.values())
                and all(graph.get("parent_type") == "page" for graph in graphs)
            )
            if not standalone_shape:
                issues.append(
                    {
                        "id": "unconfirmed_multi_graph_layout",
                        "document": document.get("path"),
                        "page_count": len(pages),
                        "graph_count": len(graphs),
                        "graph_counts_by_page": graph_counts_by_page,
                        "parent_types": [graph.get("parent_type") for graph in graphs],
                    }
                )
    return {
        "available": bool(documents),
        "coverage_complete": bool(documents) and bool(all_graphs),
        "passed": bool(documents) and bool(all_graphs) and not issues,
        "tolerance_mm": tolerance,
        "expected_margins_mm": expected_margins,
        "layout": layout_evidence,
        "issues": issues,
        "documents": [
            {
                "path": item.get("path"),
                "sha256": item.get("sha256"),
                "pages": item.get("pages"),
                "graphs": item.get("graphs"),
                "grids": item.get("grids"),
                "auxiliaries": item.get("auxiliaries"),
            }
            for item in documents
        ],
    }


_VEUSZ_SYMBOLS = {
    "alpha": "α",
    "beta": "β",
    "delta": "δ",
    "eta": "η",
    "gamma": "γ",
    "mu": "μ",
    "omega": "ω",
    "phi": "φ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "theta": "θ",
    "times": "×",
}
_SUPERSCRIPT_TRANSLATION = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")


def _plain_veusz_label(value: object) -> str:
    text = str(value or "")
    wrapper = re.compile(r"\\(?:italic|textit|emph|bold|textbf|underline)\{([^{}]*)\}")
    while wrapper.search(text):
        text = wrapper.sub(r"\1", text)
    for name, symbol in _VEUSZ_SYMBOLS.items():
        text = re.sub(rf"\\{name}(?![A-Za-z])", symbol, text)
    # Veusz escapes literal markup characters in saved labels. PDF text
    # extraction returns the rendered character, so compare against that
    # rendered form instead of treating the escape slash as label content.
    text = re.sub(r"\\([_{}^\\])", r"\1", text)
    text = re.sub(r"\^\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"_\{([^{}]*)\}", r"\1", text)
    text = text.replace("{", "").replace("}", "")
    return text


def _normalized_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", _plain_veusz_label(value)).translate(_SUPERSCRIPT_TRANSLATION)
    text = text.casefold().replace("−", "-").replace("–", "-").replace("’", "′")
    return "".join(character for character in text if not character.isspace())


def _flatten_label_values(value: object, *, source: str) -> list[dict[str, str]]:
    if isinstance(value, str) and value.strip():
        return [{"source": source, "text": value.strip()}]
    if isinstance(value, dict):
        return [
            item
            for key, nested in value.items()
            for item in _flatten_label_values(nested, source=f"{source}.{key}")
        ]
    if isinstance(value, list):
        return [
            item
            for index, nested in enumerate(value)
            for item in _flatten_label_values(nested, source=f"{source}[{index}]")
        ]
    return []


def _semantic_label_report(
    audit: dict[str, Any] | None,
    intent: dict[str, Any],
    pdfs: list[dict[str, Any]],
) -> dict[str, Any]:
    expected: list[dict[str, str]] = []
    documents = audit.get("documents", []) if isinstance(audit, dict) else []
    for document in documents:
        if not isinstance(document, dict):
            continue
        for item in document.get("semantic_labels", []):
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
                expected.append(
                    {
                        "source": f"current_vsz:{document.get('path')}:{item.get('role')}:{item.get('path')}",
                        "text": item["text"].strip(),
                    }
                )
    expected.extend(_flatten_label_values(intent.get("exact_labels"), source="publication_intent.exact_labels"))
    panel_labels: list[str] = []
    if str(intent.get("layout_status") or "").casefold() == "confirmed":
        for index, panel in enumerate(intent.get("panels", [])):
            if not isinstance(panel, dict):
                continue
            if str(panel.get("confirmation_status") or "").casefold() != "confirmed":
                continue
            label = str(panel.get("panel_label") or "").strip()
            if label:
                panel_labels.append(label)
                expected.append({"source": f"publication_intent.panels[{index}].panel_label", "text": label})
    deduplicated: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in expected:
        normalized = _normalized_label(item["text"])
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduplicated.append({**item, "normalized": normalized})
    observed_lines = [
        str(line)
        for pdf in pdfs
        for page in pdf["text_objects"].get("plain_text_by_page", [])
        for line in page.get("lines", [])
    ]
    normalized_lines = [_normalized_label(line) for line in observed_lines]
    missing: list[dict[str, str]] = []
    matched: list[dict[str, str]] = []
    for item in deduplicated:
        target = item["normalized"]
        found = target in normalized_lines
        (matched if found else missing).append(item)
    return {
        "available": bool(documents) or bool(intent.get("exact_labels")),
        "coverage_complete": bool(documents) and bool(deduplicated),
        "passed": not missing and bool(deduplicated),
        "expected": deduplicated,
        "matched": matched,
        "missing": missing,
        "observed_lines": observed_lines,
        "panel_labels": panel_labels,
    }


def _panel_typography_report(
    semantic: dict[str, Any],
    pdfs: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    panel_labels = [str(value) for value in semantic.get("panel_labels", [])]
    panel_profile = (
        profile.get("typography", {}).get("panel_label")
        if isinstance(profile.get("typography"), dict)
        else None
    )
    if not panel_labels or not isinstance(panel_profile, dict):
        return {
            "applicable": False,
            "coverage_complete": True,
            "passed": True,
            "panel_labels": panel_labels,
            "matches": [],
        }
    spans = [span for pdf in pdfs for span in pdf["text_objects"].get("visible_spans", [])]
    matches: list[dict[str, Any]] = []
    expected_size = float(panel_profile.get("size_pt") or 0.0)
    for label in panel_labels:
        candidates = [span for span in spans if _normalized_label(span.get("text")) == _normalized_label(label)]
        valid = [
            span
            for span in candidates
            if abs(float(span.get("size") or 0.0) - expected_size) <= 0.15
            and (panel_profile.get("weight") != "bold" or "bold" in str(span.get("font") or "").casefold())
            and (
                panel_profile.get("style") != "upright"
                or all(token not in str(span.get("font") or "").casefold() for token in ("italic", "oblique"))
            )
        ]
        matches.append({"label": label, "candidates": candidates, "valid": valid})
    return {
        "applicable": True,
        "coverage_complete": True,
        "passed": all(item["valid"] for item in matches),
        "panel_labels": panel_labels,
        "expected": panel_profile,
        "matches": matches,
    }


_CVD_MATRICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.01182, 0.04294, 0.968881),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.3039),
    ),
}


def _srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(value: float) -> float:
    clipped = min(max(value, 0.0), 1.0)
    return 12.92 * clipped if clipped <= 0.0031308 else 1.055 * clipped ** (1.0 / 2.4) - 0.055


def _simulate_cvd(rgb: list[float], matrix: tuple[tuple[float, float, float], ...]) -> list[float]:
    linear = [_srgb_to_linear(float(value)) for value in rgb]
    simulated = [sum(row[index] * linear[index] for index in range(3)) for row in matrix]
    return [_linear_to_srgb(value) for value in simulated]


def _lab(rgb: list[float]) -> tuple[float, float, float]:
    red, green, blue = (_srgb_to_linear(float(value)) for value in rgb)
    x = (0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047
    y = 0.2126729 * red + 0.7151522 * green + 0.072175 * blue
    z = (0.0193339 * red + 0.119192 * green + 0.9503041 * blue) / 1.08883

    def transform(value: float) -> float:
        return value ** (1.0 / 3.0) if value > 0.008856 else 7.787 * value + 16.0 / 116.0

    fx, fy, fz = transform(x), transform(y), transform(z)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def _delta_e(left: list[float], right: list[float]) -> float:
    lab_left = _lab(left)
    lab_right = _lab(right)
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab_left, lab_right, strict=True)))


def _relative_luminance(rgb: list[float]) -> float:
    red, green, blue = (_srgb_to_linear(float(value)) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _rgb_matches(left: list[float], right: list[float], tolerance: float = 2.5 / 255.0) -> bool:
    return all(abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right, strict=True))


def _sample_color_scale(control_colors: list[dict[str, Any]], count: int = 16) -> list[list[float]]:
    controls = [item.get("rgb") for item in control_colors if isinstance(item.get("rgb"), list)]
    if len(controls) < 2:
        return []
    samples: list[list[float]] = []
    for index in range(count):
        position = index / max(count - 1, 1) * (len(controls) - 1)
        left_index = min(int(math.floor(position)), len(controls) - 2)
        fraction = position - left_index
        left = controls[left_index]
        right = controls[left_index + 1]
        samples.append(
            [float(a) + (float(b) - float(a)) * fraction for a, b in zip(left, right, strict=True)]
        )
    return samples


def _turn_count(values: list[float], tolerance: float = 0.005) -> int:
    signs: list[int] = []
    for left, right in zip(values, values[1:], strict=False):
        delta = right - left
        if abs(delta) <= tolerance:
            continue
        sign = 1 if delta > 0 else -1
        if not signs or signs[-1] != sign:
            signs.append(sign)
    return max(len(signs) - 1, 0)


def _series_accessibility_report(
    audit: dict[str, Any] | None,
    pdfs: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    documents = audit.get("documents", []) if isinstance(audit, dict) else []
    series = [
        {**item, "document": document.get("path")}
        for document in documents
        if isinstance(document, dict)
        for item in document.get("series", [])
        if isinstance(item, dict) and (item.get("plot_line_visible") or item.get("marker_visible"))
    ]
    color_scales = [
        {**item, "document": document.get("path")}
        for document in documents
        if isinstance(document, dict)
        for item in document.get("color_scales", [])
        if isinstance(item, dict)
    ]
    if not documents:
        return {
            "available": False,
            "coverage_complete": False,
            "passed": False,
            "reason": "exact_current_vsz_audit_unavailable",
            "series": [],
            "pairs": [],
        }
    active_color_entries = [
        {
            "path": item.get("path"),
            "role": entry.get("role"),
            "color": entry.get("color"),
        }
        for item in series
        for entry in item.get("rendered_colors", [])
        if isinstance(entry, dict)
    ]
    unresolved = [
        {"path": item.get("path"), "role": item.get("role")}
        for item in active_color_entries
        if not isinstance(item.get("color"), dict)
    ]
    unresolved.extend(
        {"path": item.get("path"), "role": "primary_series_color"}
        for item in series
        if not isinstance(item.get("color"), dict)
        and not any(entry.get("path") == item.get("path") for entry in unresolved)
    )
    pdf_colors = [
        color
        for pdf in pdfs
        for color in pdf.get("vector_colors", {}).get("unique_rgb", [])
        if isinstance(color, list) and len(color) == 3
    ]
    unrendered = [
        {"path": item.get("path"), "role": item.get("role"), "color": item.get("color")}
        for item in active_color_entries
        if isinstance(item.get("color"), dict)
        and not any(_rgb_matches(item["color"]["rgb"], candidate) for candidate in pdf_colors)
    ]
    accessibility = profile.get("accessibility") if isinstance(profile.get("accessibility"), dict) else {}
    minimum_delta_e = float(accessibility.get("minimum_simulated_delta_e") or 10.0)
    minimum_luminance_delta = float(accessibility.get("minimum_grayscale_luminance_delta") or 0.08)
    minimum_colormap_step = float(accessibility.get("minimum_colormap_step_delta_e") or 2.0)
    minimum_colormap_range = float(accessibility.get("minimum_colormap_luminance_range") or 0.3)
    maximum_colormap_turns = int(accessibility.get("maximum_colormap_luminance_turns") or 1)
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for item in series:
        key = (str(item.get("document")), str(item.get("graph_path")), int(item.get("page") or 0))
        groups.setdefault(key, []).append(item)
    categorical_graph_keys = {
        (
            str(document.get("path")),
            str(graph.get("graph_path")),
            int(graph.get("page") or 0),
        )
        for document in documents
        if isinstance(document, dict)
        for graph in document.get("categorical_graphs", [])
        if isinstance(graph, dict) and graph.get("spatial_identity_explicit") is True
    }
    pair_reports: list[dict[str, Any]] = []
    for group_key, group in groups.items():
        for left, right in combinations(group, 2):
            left_signature = (
                left.get("line_style") if left.get("plot_line_visible") else None,
                left.get("marker") if left.get("marker_visible") else None,
            )
            right_signature = (
                right.get("line_style") if right.get("plot_line_visible") else None,
                right.get("marker") if right.get("marker_visible") else None,
            )
            categorical_position_distinct = group_key in categorical_graph_keys
            non_color_distinct = bool(
                (left.get("direct_labelled") and right.get("direct_labelled"))
                or left_signature != right_signature
                or categorical_position_distinct
            )
            left_rgb = left.get("color", {}).get("rgb") if isinstance(left.get("color"), dict) else None
            right_rgb = right.get("color", {}).get("rgb") if isinstance(right.get("color"), dict) else None
            simulations = {}
            if isinstance(left_rgb, list) and isinstance(right_rgb, list):
                for name, matrix in _CVD_MATRICES.items():
                    simulations[name] = round(
                        _delta_e(_simulate_cvd(left_rgb, matrix), _simulate_cvd(right_rgb, matrix)),
                        3,
                    )
                luminance_delta = round(abs(_relative_luminance(left_rgb) - _relative_luminance(right_rgb)), 6)
            else:
                luminance_delta = None
            pair_reports.append(
                {
                    "group": list(group_key),
                    "left": {"path": left.get("path"), "label": left.get("label"), "signature": left_signature},
                    "right": {
                        "path": right.get("path"),
                        "label": right.get("label"),
                        "signature": right_signature,
                    },
                    "categorical_position_distinct": categorical_position_distinct,
                    "distinction_basis": (
                        "categorical_axis_position_and_label"
                        if categorical_position_distinct
                        else "direct_labels"
                        if left.get("direct_labelled") and right.get("direct_labelled")
                        else "line_or_marker_signature"
                        if left_signature != right_signature
                        else "none"
                    ),
                    "non_color_distinct": non_color_distinct,
                    "cvd_delta_e": simulations,
                    "grayscale_luminance_delta": luminance_delta,
                    "cvd_accessible": bool(simulations)
                    and (min(simulations.values()) >= minimum_delta_e or non_color_distinct),
                    "grayscale_accessible": luminance_delta is not None
                    and (luminance_delta >= minimum_luminance_delta or non_color_distinct),
                }
            )
    non_color_required = accessibility.get("non_color_distinction_required") is True
    non_color_passed = not non_color_required or all(item["non_color_distinct"] for item in pair_reports)
    cvd_passed = all(item["cvd_accessible"] for item in pair_reports)
    grayscale_passed = all(item["grayscale_accessible"] for item in pair_reports)
    embedded_raster_present = any(pdf.get("embedded_rasters") for pdf in pdfs)
    color_scale_reports: list[dict[str, Any]] = []
    forbidden_names = {"spectrum", "spectrum2", "spectrum2-step", "rainbow", "jet", "hsv"}
    for scale in color_scales:
        samples = _sample_color_scale(scale.get("control_colors", []))
        binding_samples = _sample_color_scale(scale.get("control_colors", []), count=256)
        matched_pdf_colors = [
            color
            for color in pdf_colors
            if binding_samples and min(_delta_e(color, sample) for sample in binding_samples) <= 2.5
        ]
        rendered_output_confirmed = embedded_raster_present or len(matched_pdf_colors) >= 3
        rendered_output_method = (
            "embedded_pdf_raster"
            if embedded_raster_present
            else "pdf_vector_palette_matches"
            if rendered_output_confirmed
            else "unconfirmed"
        )
        luminances = [_relative_luminance(rgb) for rgb in samples]
        cvd_steps = {
            name: [
                _delta_e(_simulate_cvd(left, matrix), _simulate_cvd(right, matrix))
                for left, right in zip(samples, samples[1:], strict=False)
            ]
            for name, matrix in _CVD_MATRICES.items()
        }
        minimum_steps = {name: round(min(values), 3) if values else None for name, values in cvd_steps.items()}
        luminance_range = max(luminances) - min(luminances) if luminances else 0.0
        turns = _turn_count(luminances)
        cvd_scale_passed = bool(samples) and all(
            value is not None and float(value) >= minimum_colormap_step for value in minimum_steps.values()
        )
        grayscale_scale_passed = (
            bool(samples) and luminance_range >= minimum_colormap_range and turns <= maximum_colormap_turns
        )
        rainbow_passed = not (
            accessibility.get("avoid_rainbow_palette") is True
            and str(scale.get("name") or "").strip().casefold() in forbidden_names
        )
        color_scale_reports.append(
            {
                "path": scale.get("path"),
                "name": scale.get("name"),
                "sample_count": len(samples),
                "minimum_adjacent_cvd_delta_e": minimum_steps,
                "luminance_range": round(luminance_range, 6),
                "luminance_turns": turns,
                "cvd_accessible": cvd_scale_passed,
                "grayscale_accessible": grayscale_scale_passed,
                "rainbow_avoidance_passed": rainbow_passed,
                "rendered_raster_confirmed": embedded_raster_present,
                "rendered_output_confirmed": rendered_output_confirmed,
                "rendered_output_method": rendered_output_method,
                "matched_pdf_colors": matched_pdf_colors,
                "passed": (
                    cvd_scale_passed
                    and grayscale_scale_passed
                    and rainbow_passed
                    and rendered_output_confirmed
                ),
            }
        )
    colormap_passed = all(item["passed"] for item in color_scale_reports)
    cvd_passed = cvd_passed and all(item["cvd_accessible"] for item in color_scale_reports)
    grayscale_passed = grayscale_passed and all(item["grayscale_accessible"] for item in color_scale_reports)
    scale_coverage = all(
        item["sample_count"] > 0 and item["rendered_output_confirmed"]
        for item in color_scale_reports
    )
    coverage_complete = not unresolved and not unrendered and scale_coverage
    return {
        "available": True,
        "coverage_complete": coverage_complete,
        "passed": coverage_complete and non_color_passed and cvd_passed and grayscale_passed and colormap_passed,
        "series": series,
        "categorical_graphs": [
            {**graph, "document": document.get("path")}
            for document in documents
            if isinstance(document, dict)
            for graph in document.get("categorical_graphs", [])
            if isinstance(graph, dict)
        ],
        "color_scales": color_scale_reports,
        "pairs": pair_reports,
        "unresolved_color_paths": unresolved,
        "colors_not_confirmed_in_pdf": unrendered,
        "non_color_required": non_color_required,
        "non_color_passed": non_color_passed,
        "colour_vision_passed": cvd_passed,
        "grayscale_passed": grayscale_passed,
        "colormap_passed": colormap_passed,
        "thresholds": {
            "minimum_simulated_delta_e": minimum_delta_e,
            "minimum_grayscale_luminance_delta": minimum_luminance_delta,
            "minimum_colormap_step_delta_e": minimum_colormap_step,
            "minimum_colormap_luminance_range": minimum_colormap_range,
            "maximum_colormap_luminance_turns": maximum_colormap_turns,
            "authority": accessibility.get("threshold_authority") or "sciplot_internal_operational_gate",
        },
    }


def _vsz_stroke_report(audit: dict[str, Any] | None, profile: dict[str, Any]) -> dict[str, Any]:
    stroke_profile = profile.get("strokes") if isinstance(profile.get("strokes"), dict) else {}
    minimum = float(stroke_profile.get("minimum_width_pt") or 0.0)
    maximum = float(stroke_profile.get("maximum_width_pt") or float("inf"))
    documents = audit.get("documents", []) if isinstance(audit, dict) else []
    items = [
        {**item, "document": document.get("path")}
        for document in documents
        if isinstance(document, dict)
        for item in document.get("stroke_inventory", {}).get("items", [])
        if isinstance(item, dict) and item.get("active")
    ]
    unsupported = [
        {**item, "document": document.get("path")}
        for document in documents
        if isinstance(document, dict)
        for item in document.get("stroke_inventory", {}).get("unsupported", [])
        if isinstance(item, dict)
    ]
    out_of_range = [
        item
        for item in items
        if item.get("width_pt") is None
        or float(item["width_pt"]) < minimum - 0.01
        or float(item["width_pt"]) > maximum + 0.01
    ]
    coverage_complete = bool(documents) and not unsupported and all(item.get("width_pt") is not None for item in items)
    return {
        "available": bool(documents),
        "coverage_complete": coverage_complete,
        "passed": coverage_complete and not out_of_range,
        "expected": {"minimum_pt": minimum, "maximum_pt": maximum},
        "active_count": len(items),
        "items": items,
        "unsupported": unsupported,
        "out_of_range": out_of_range,
        "evidence_model": "PDF strokes plus resolved active line settings from the exact current VSZ",
    }


def _publication_qa(
    *,
    profile: dict[str, Any],
    pdfs: list[dict[str, Any]],
    tiffs: list[dict[str, Any]],
    required_formats: dict[str, Any],
    veusz_audit: dict[str, Any] | None,
    publication_intent: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    fixed_frame = _fixed_frame_report(veusz_audit, publication_intent)
    semantic_labels = _semantic_label_report(veusz_audit, publication_intent, pdfs)
    panel_typography = _panel_typography_report(semantic_labels, pdfs, profile)
    accessibility = _series_accessibility_report(veusz_audit, pdfs, profile)
    vsz_strokes = _vsz_stroke_report(veusz_audit, profile)
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
    checks.append(
        _check(
            "fixed_frame_current_vsz",
            passed=bool(fixed_frame["passed"]),
            actual=fixed_frame,
            expected="Every rendered graph uses the fixed physical frame; confirmed composites match exact slots.",
            message="The exact current Veusz document must retain the fixed graph frame and declared slot geometry.",
            severity="error" if fixed_frame["available"] else "warning",
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
    minimum_math_script_size = float(typography.get("minimum_math_script_size_pt") or minimum_size)
    maximum_size = float(typography.get("maximum_text_size_pt") or float("inf"))
    observed_minima = [pdf["text_objects"]["ordinary_minimum_size_pt"] for pdf in pdfs]
    observed_math_script_minima = [pdf["text_objects"]["math_script_minimum_size_pt"] for pdf in pdfs]
    observed_maxima = [pdf["text_objects"]["maximum_size_pt"] for pdf in pdfs]
    text_size_passed = all(
        minimum is not None
        and maximum is not None
        and float(minimum) >= minimum_size - 0.01
        and float(maximum) <= maximum_size + 0.01
        and (script_minimum is None or float(script_minimum) >= minimum_math_script_size - 0.01)
        for minimum, script_minimum, maximum in zip(
            observed_minima,
            observed_math_script_minima,
            observed_maxima,
            strict=True,
        )
    )
    checks.append(
        _check(
            "text_size_range",
            passed=text_size_passed,
            actual={
                "ordinary_minimum_pt": observed_minima,
                "math_script_minimum_pt": observed_math_script_minima,
                "maximum_pt": observed_maxima,
            },
            expected={
                "ordinary_minimum_pt": minimum_size,
                "math_script_minimum_pt": minimum_math_script_size,
                "maximum_pt": maximum_size,
            },
            message="Ordinary PDF text and reduced mathematical scripts must stay within final-size ranges.",
        )
    )
    checks.append(
        _check(
            "semantic_label_inventory",
            passed=bool(semantic_labels["passed"]),
            actual=semantic_labels,
            expected="All labels required by the exact VSZ and publication intent are present as PDF text.",
            message="Axis, key, direct, exact, and confirmed panel labels must survive into the final PDF.",
            severity="error" if semantic_labels["available"] else "warning",
        )
    )
    checks.append(
        _check(
            "panel_label_typography",
            passed=bool(panel_typography["passed"]),
            actual=panel_typography,
            expected=panel_typography.get("expected") or "not applicable",
            message="Multipart panel labels must use their role-specific final-size typography.",
            severity="error" if panel_typography["applicable"] else "warning",
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
    checks.extend(
        [
            _check(
                "series_colors_rendered",
                passed=bool(accessibility["coverage_complete"]),
                actual={
                    "unresolved_color_paths": accessibility.get("unresolved_color_paths", []),
                    "colors_not_confirmed_in_pdf": accessibility.get("colors_not_confirmed_in_pdf", []),
                    "series": accessibility.get("series", []),
                    "color_scales": accessibility.get("color_scales", []),
                },
                expected=(
                    "Every visible semantic series colour or colour scale resolves from the current VSZ and "
                    "is confirmed in the PDF."
                ),
                message="Colour simulations must be bound to colours actually rendered in the final PDF.",
                severity="error" if accessibility["available"] else "warning",
            ),
            _check(
                "non_color_series_distinction",
                passed=bool(accessibility.get("non_color_passed")),
                actual=accessibility.get("pairs", []),
                expected=(
                    "Every same-graph series pair has a distinct line/marker signature, direct labels, "
                    "or explicit labelled categorical positions."
                ),
                message="Series identity must not depend on colour alone.",
                severity="error" if accessibility["available"] else "warning",
            ),
            _check(
                "colour_vision_simulation",
                passed=bool(accessibility.get("colour_vision_passed")),
                actual=accessibility,
                expected=accessibility.get("thresholds", {}),
                message=(
                    "Protanopia, deuteranopia, and tritanopia simulations must retain colour or non-colour separation."
                ),
                severity="error" if accessibility["available"] else "warning",
            ),
            _check(
                "grayscale_accessibility",
                passed=bool(accessibility.get("grayscale_passed")),
                actual=accessibility,
                expected=accessibility.get("thresholds", {}),
                message="Grayscale review must retain luminance or non-colour separation for every series pair.",
                severity="error" if accessibility["available"] else "warning",
            ),
        ]
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
            "stroke_range_pdf_partial",
            passed=stroke_passed,
            actual=stroke_ranges,
            expected={"minimum_pt": minimum_stroke, "maximum_pt": maximum_stroke},
            message=(
                "Measured PDF strokes should fit the profile; filled Veusz curve paths remain a documented limitation."
            ),
            severity="warning",
        )
    )
    checks.append(
        _check(
            "stroke_range_current_vsz_complete",
            passed=bool(vsz_strokes["passed"]),
            actual=vsz_strokes,
            expected=vsz_strokes["expected"],
            message="All active physical stroke settings in the exact current VSZ must fit the profile range.",
            severity="error" if vsz_strokes["available"] else "warning",
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
    coverage = {
        "fixed_frame_current_vsz": bool(fixed_frame["coverage_complete"]),
        "rendered_colour_vision_and_grayscale_accessibility": bool(accessibility["coverage_complete"]),
        "semantic_panel_and_required_label_inventory": bool(semantic_labels["coverage_complete"])
        and bool(panel_typography["coverage_complete"]),
        "complete_stroke_coverage_for_filled_veusz_paths": bool(vsz_strokes["coverage_complete"]),
    }
    unchecked_constraints = [constraint for constraint, complete in coverage.items() if not complete]
    coverage_complete = not unchecked_constraints
    limitations = []
    if not vsz_strokes["coverage_complete"]:
        limitations.append("Complete stroke coverage requires a successfully loaded exact current VSZ document.")
    if not accessibility["coverage_complete"]:
        limitations.append(
            "Rendered colour accessibility requires resolved current-VSZ colours confirmed in final PDF "
            "vectors or embedded rasters."
        )
    if not semantic_labels["coverage_complete"]:
        limitations.append("Semantic label coverage requires current-VSZ label inventory and final PDF text objects.")
    if not fixed_frame["coverage_complete"]:
        limitations.append("Fixed-frame coverage requires Veusz-computed bounds from the exact current VSZ document.")
    return {
        "kind": "sciplot_publication_qa",
        "version": 2,
        "status": "passed" if checked_constraints_passed else "needs_revision",
        "checked_constraints_passed": checked_constraints_passed,
        "coverage_complete": coverage_complete,
        "journal_compliance_established": False,
        "journal_compliance_status": (
            "not_established_profile_scope" if coverage_complete else "not_established_incomplete_coverage"
        ),
        "status_semantics": (
            "passed means only the implemented constraints passed; it is not a claim of journal compliance"
        ),
        "profile": profile,
        "required_formats": required_formats,
        "checks": checks,
        "blocking_check_ids": [check["id"] for check in blocking_failures],
        "coverage": coverage,
        "veusz_document_audit": veusz_audit,
        "limitations": limitations,
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
    veusz_documents: list[Path] | None = None,
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
    discovered_veusz_documents = _discover_veusz_documents(output_dir, veusz_documents)
    veusz_audit, veusz_audit_error = _run_veusz_audit(discovered_veusz_documents) if profile else (None, None)
    intent = _publication_intent(output_dir)
    publication = (
        _publication_qa(
            profile=profile,
            pdfs=pdf_reports,
            tiffs=tiff_reports,
            required_formats=required_formats,
            veusz_audit=veusz_audit,
            publication_intent=intent,
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
        if veusz_audit_error:
            publication["veusz_document_audit_error"] = veusz_audit_error
        payload["publication"] = publication
        payload["publication_strict"] = bool(strict_publication)
    return payload


__all__ = ["run_qa"]
