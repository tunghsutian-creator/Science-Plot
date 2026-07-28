"""Render final-size contact sheets and metadata."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sciplot_core.foundation.file_hashing import file_sha256

from sciplot_core.visual_review.transaction import (
    CONTACT_SHEET_COLUMNS,
    CONTACT_SHEET_ROWS,
    CONTACT_SHEET_TILE_SIZE,
    REVIEW_SURFACE,
)


def _contact_sheet_label(record: dict[str, Any]) -> tuple[str, str]:
    expected = record.get("expected_size_mm") or [0.0, 0.0]
    tiff = record.get("tiff") if isinstance(record.get("tiff"), dict) else {}
    pdf = record.get("pdf") if isinstance(record.get("pdf"), dict) else {}
    tiff_size = tiff.get("physical_size_mm") or [0.0, 0.0]
    pdf_size = pdf.get("physical_size_mm") or [0.0, 0.0]
    headline = f"{record['rule_id']}  [{record['status']}]"
    detail = (
        f"expected {expected[0]:.0f}x{expected[1]:.0f} mm | "
        f"TIFF {tiff_size[0]:.2f}x{tiff_size[1]:.2f} mm | "
        f"PDF {pdf_size[0]:.2f}x{pdf_size[1]:.2f} mm"
    )
    return headline, detail


def _write_contact_sheets(
    output_dir: Path, records: list[dict[str, Any]]
) -> list[Path]:
    drawable = [
        record
        for record in records
        if isinstance(record.get("tiff"), dict)
        and Path(str(record["tiff"].get("path"))).exists()
    ]
    if not drawable:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    capacity = CONTACT_SHEET_COLUMNS * CONTACT_SHEET_ROWS
    font = ImageFont.load_default()
    paths: list[Path] = []
    for sheet_index, start in enumerate(range(0, len(drawable), capacity), start=1):
        batch = drawable[start : start + capacity]
        canvas = Image.new(
            "RGB",
            (
                CONTACT_SHEET_TILE_SIZE[0] * CONTACT_SHEET_COLUMNS,
                CONTACT_SHEET_TILE_SIZE[1] * CONTACT_SHEET_ROWS,
            ),
            "#eef1ee",
        )
        draw = ImageDraw.Draw(canvas)
        for index, record in enumerate(batch):
            column = index % CONTACT_SHEET_COLUMNS
            row = index // CONTACT_SHEET_COLUMNS
            left = column * CONTACT_SHEET_TILE_SIZE[0]
            top = row * CONTACT_SHEET_TILE_SIZE[1]
            tile_box = (
                left + 8,
                top + 8,
                left + CONTACT_SHEET_TILE_SIZE[0] - 8,
                top + CONTACT_SHEET_TILE_SIZE[1] - 8,
            )
            draw.rounded_rectangle(
                tile_box, radius=10, fill="white", outline="#cbd3ce", width=2
            )
            headline, detail = _contact_sheet_label(record)
            draw.text((left + 22, top + 20), headline, fill="#16221b", font=font)
            draw.text((left + 22, top + 39), detail, fill="#59675f", font=font)
            image_box = (
                CONTACT_SHEET_TILE_SIZE[0] - 36,
                CONTACT_SHEET_TILE_SIZE[1] - 82,
            )
            with Image.open(Path(str(record["tiff"]["path"]))) as source:
                preview = ImageOps.contain(
                    source.convert("RGB"), image_box, Image.Resampling.LANCZOS
                )
            image_left = left + (CONTACT_SHEET_TILE_SIZE[0] - preview.width) // 2
            image_top = top + 67 + (image_box[1] - preview.height) // 2
            canvas.paste(preview, (image_left, image_top))
        path = output_dir / f"contact_sheet_{sheet_index:02d}.png"
        canvas.save(path, format="PNG", optimize=True)
        paths.append(path)
    return paths


def _contact_sheet_metadata(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if resolved.suffix.casefold() != ".png" or not resolved.is_file():
        raise ValueError(f"Review preview must be a PNG file: {resolved}")
    try:
        with Image.open(resolved) as image:
            if image.format != "PNG":
                raise ValueError(f"Review preview is not encoded as PNG: {resolved}")
            image.verify()
        with Image.open(resolved) as image:
            pixels = [int(image.width), int(image.height)]
            frame_count = int(getattr(image, "n_frames", 1))
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(f"Review preview is not a decodable PNG: {resolved}") from exc
    if min(pixels) <= 0 or frame_count != 1:
        raise ValueError(
            f"Review preview has invalid image dimensions or frames: {resolved}"
        )
    return {
        "path": str(resolved),
        "sha256": file_sha256(resolved),
        "pixels": pixels,
        "format": "PNG",
        "frame_count": frame_count,
        "review_surface": REVIEW_SURFACE,
    }


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "rule_id",
        "status",
        "expected_width_mm",
        "expected_height_mm",
        "pdf_width_mm",
        "pdf_height_mm",
        "tiff_width_mm",
        "tiff_height_mm",
        "tiff_width_px",
        "tiff_height_px",
        "tiff_x_dpi",
        "tiff_y_dpi",
        "errors",
        "manifest",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            expected = record.get("expected_size_mm") or [None, None]
            pdf = record.get("pdf") if isinstance(record.get("pdf"), dict) else {}
            tiff = record.get("tiff") if isinstance(record.get("tiff"), dict) else {}
            pdf_size = pdf.get("physical_size_mm") or [None, None]
            tiff_size = tiff.get("physical_size_mm") or [None, None]
            pixels = tiff.get("pixels") or [None, None]
            dpi = tiff.get("dpi") or [None, None]
            writer.writerow(
                {
                    "rule_id": record["rule_id"],
                    "status": record["status"],
                    "expected_width_mm": expected[0],
                    "expected_height_mm": expected[1],
                    "pdf_width_mm": pdf_size[0],
                    "pdf_height_mm": pdf_size[1],
                    "tiff_width_mm": tiff_size[0],
                    "tiff_height_mm": tiff_size[1],
                    "tiff_width_px": pixels[0],
                    "tiff_height_px": pixels[1],
                    "tiff_x_dpi": dpi[0],
                    "tiff_y_dpi": dpi[1],
                    "errors": " | ".join(record.get("errors") or []),
                    "manifest": record.get("manifest"),
                }
            )
