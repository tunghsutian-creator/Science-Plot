# ruff: noqa: E501
# Embedded self-contained HTML/CSS is intentionally kept literal for auditability.

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import shutil
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw, ImageFont, ImageOps

from sciplot_core._utils import atomic_write_json, file_sha256, json_safe
from sciplot_core.policy import DEFAULT_FIGURE_SIZE
from sciplot_core.readiness import READY_RULE_ACCEPTANCE_VERSION

PHYSICAL_SIZE_TOLERANCE_MM = 0.25
TIFF_DPI_TOLERANCE = 0.5
CONTACT_SHEET_COLUMNS = 4
CONTACT_SHEET_ROWS = 2
CONTACT_SHEET_TILE_SIZE = (620, 660)
FINAL_SIZE_VISUAL_REVIEW_VERSION = 2
FINAL_SIZE_VISUAL_DECISION_VERSION = 2
REVIEW_SURFACE = "uncalibrated_screen_preview"
PENDING_REVIEW_STATUS = "pending_uncalibrated_preview_review"
REQUIRED_PREVIEW_CHECKS = (
    "labels_visible_in_uncalibrated_preview",
    "legend_not_occluding_data_in_preview",
    "no_visible_text_or_data_clipping_in_preview",
    "markers_and_lines_distinguishable_in_preview",
    "no_unexplained_blank_or_corrupt_panel_in_preview",
)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            json_safe(payload),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stage_bytes(target: Path, content: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def _replace_files_transactionally(outputs: dict[Path, bytes]) -> None:
    """Replace a related artifact set and restore every target on failure."""

    resolved_outputs = {path.expanduser().resolve(): content for path, content in outputs.items()}
    if len(resolved_outputs) != len(outputs):
        raise ValueError("Transactional output paths must be unique.")

    originals: dict[Path, bytes | None] = {}
    staged: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        for target in resolved_outputs:
            if target.exists() and not target.is_file():
                raise ValueError(f"Transactional output target is not a file: {target}")
            originals[target] = target.read_bytes() if target.is_file() else None
        for target, content in resolved_outputs.items():
            staged[target] = _stage_bytes(target, content)
        for target in resolved_outputs:
            os.replace(staged[target], target)
            committed.append(target)
    except Exception as exc:
        rollback_errors: list[str] = []
        for target in reversed(committed):
            try:
                original = originals[target]
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(_stage_bytes(target, original), target)
            except Exception as rollback_exc:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(f"{target}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "Visual-review transaction failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


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
    layout_quality = manifest.get("layout_quality") if isinstance(manifest.get("layout_quality"), dict) else {}
    summaries = layout_quality.get("summaries") if isinstance(layout_quality.get("summaries"), list) else []
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        size = _size_pair(summary.get("figure_size_mm") or summary.get("requested_size_mm"))
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
    request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    render_options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
    return _parse_size_mm(render_options.get("size") or DEFAULT_FIGURE_SIZE)


def _within_tolerance(actual: tuple[float, float], expected: tuple[float, float]) -> bool:
    return all(
        abs(observed - target) <= PHYSICAL_SIZE_TOLERANCE_MM
        for observed, target in zip(actual, expected, strict=True)
    )


def _delivery_figure(manifest: dict[str, Any], artifact_format: str) -> dict[str, Any] | None:
    delivery = manifest.get("delivery_package") if isinstance(manifest.get("delivery_package"), dict) else {}
    figures = delivery.get("figures") if isinstance(delivery.get("figures"), list) else []
    return next(
        (
            item
            for item in figures
            if isinstance(item, dict) and str(item.get("format") or "").casefold() == artifact_format
        ),
        None,
    )


def _pdf_size_mm(path: Path) -> tuple[float, float]:
    with fitz.open(path) as document:
        if document.page_count != 1:
            raise ValueError(f"Expected one-page acceptance PDF, found {document.page_count}: {path}")
        rectangle = document[0].rect
        return float(rectangle.width) * 25.4 / 72.0, float(rectangle.height) * 25.4 / 72.0


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
    pdf_path = Path(str(pdf_item.get("path"))) if pdf_item and pdf_item.get("path") else None
    tiff_path = Path(str(tiff_item.get("path"))) if tiff_item and tiff_item.get("path") else None

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
                    "dpi_is_300": all(abs(value - 300.0) <= TIFF_DPI_TOLERANCE for value in dpi),
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


def _write_contact_sheets(output_dir: Path, records: list[dict[str, Any]]) -> list[Path]:
    drawable = [
        record
        for record in records
        if isinstance(record.get("tiff"), dict) and Path(str(record["tiff"].get("path"))).exists()
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
            (CONTACT_SHEET_TILE_SIZE[0] * CONTACT_SHEET_COLUMNS, CONTACT_SHEET_TILE_SIZE[1] * CONTACT_SHEET_ROWS),
            "#eef1ee",
        )
        draw = ImageDraw.Draw(canvas)
        for index, record in enumerate(batch):
            column = index % CONTACT_SHEET_COLUMNS
            row = index // CONTACT_SHEET_COLUMNS
            left = column * CONTACT_SHEET_TILE_SIZE[0]
            top = row * CONTACT_SHEET_TILE_SIZE[1]
            tile_box = (left + 8, top + 8, left + CONTACT_SHEET_TILE_SIZE[0] - 8, top + CONTACT_SHEET_TILE_SIZE[1] - 8)
            draw.rounded_rectangle(tile_box, radius=10, fill="white", outline="#cbd3ce", width=2)
            headline, detail = _contact_sheet_label(record)
            draw.text((left + 22, top + 20), headline, fill="#16221b", font=font)
            draw.text((left + 22, top + 39), detail, fill="#59675f", font=font)
            image_box = (CONTACT_SHEET_TILE_SIZE[0] - 36, CONTACT_SHEET_TILE_SIZE[1] - 82)
            with Image.open(Path(str(record["tiff"]["path"]))) as source:
                preview = ImageOps.contain(source.convert("RGB"), image_box, Image.Resampling.LANCZOS)
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
        raise ValueError(f"Review preview has invalid image dimensions or frames: {resolved}")
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


def _markdown_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# SciPlot physical-size QA and review preview",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"- Physical size passed: {summary['physical_size_passed_count']}/{summary['eligible_rule_count']}",
        f"- Uncalibrated review previews: {summary['contact_sheet_count']}",
        f"- Automated status: `{summary['automated_status']}`",
        f"- Manual visual status: `{summary['manual_visual_status']}`",
        "",
        "| Rule | Expected mm | PDF mm | TIFF mm | DPI | Size status |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for record in payload["records"]:
        expected = record.get("expected_size_mm") or ["-", "-"]
        pdf = (record.get("pdf") or {}).get("physical_size_mm") or ["-", "-"]
        tiff = (record.get("tiff") or {}).get("physical_size_mm") or ["-", "-"]
        dpi = (record.get("tiff") or {}).get("dpi") or ["-", "-"]
        lines.append(
            f"| `{record['rule_id']}` | {expected[0]}x{expected[1]} | {pdf[0]}x{pdf[1]} | "
            f"{tiff[0]}x{tiff[1]} | {dpi[0]}x{dpi[1]} | `{record['status']}` |"
        )
    lines.extend(
        [
            "",
            "## Review boundary",
            "",
            "Physical dimensions and TIFF DPI are machine-checked. Contact sheets are uncalibrated screen "
            "previews for visible corruption, clipping, occlusion, and basic distinguishability only. They do "
            "not establish final-size legibility. Inspect the canonical PDF/TIFF at a calibrated physical size "
            "when final-size readability is required. This artifact does not claim journal compliance.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(_markdown_text(payload), encoding="utf-8")


def _html_text(payload: dict[str, Any], contact_sheets: list[Path], *, parent: Path) -> str:
    summary = payload["summary"]
    rows = []
    for record in payload["records"]:
        expected = record.get("expected_size_mm") or ["-", "-"]
        pdf = (record.get("pdf") or {}).get("physical_size_mm") or ["-", "-"]
        tiff = (record.get("tiff") or {}).get("physical_size_mm") or ["-", "-"]
        dpi = (record.get("tiff") or {}).get("dpi") or ["-", "-"]
        css = "ok" if record["status"] == "passed" else ("muted" if record["status"] == "not_run" else "bad")
        rows.append(
            f"<tr><td><code>{html.escape(record['rule_id'])}</code></td>"
            f"<td>{expected[0]}x{expected[1]}</td><td>{pdf[0]}x{pdf[1]}</td>"
            f"<td>{tiff[0]}x{tiff[1]}</td><td>{dpi[0]}x{dpi[1]}</td>"
            f'<td><span class="pill {css}">{html.escape(record["status"])}</span></td></tr>'
        )
    images = "".join(
        f'<figure><img src="{html.escape(sheet.relative_to(parent).as_posix(), quote=True)}" '
        f'alt="Uncalibrated review preview {index}"><figcaption>Uncalibrated review preview {index}</figcaption></figure>'
        for index, sheet in enumerate(contact_sheets, start=1)
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SciPlot physical-size QA and review preview</title><style>
:root{{--ink:#17211d;--muted:#607068;--line:#dbe3de;--paper:#f5f7f5;--green:#176b46;--red:#9f2d2d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 ui-sans-serif,system-ui,sans-serif}}
main{{max-width:1500px;margin:auto;padding:34px 28px 60px}}h1{{margin:0 0 4px;font-size:28px}}.lede{{color:var(--muted)}}
.cards{{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}}.card{{background:white;border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:180px}}.card strong{{display:block;font-size:24px}}
.table-wrap{{overflow:auto;background:white;border:1px solid var(--line);border-radius:12px}}table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{background:#eef2ef}}
.pill{{border-radius:999px;padding:2px 8px;font-size:12px}}.pill.ok{{background:#e3f3ea;color:var(--green)}}.pill.bad{{background:#f8e2e2;color:var(--red)}}.pill.muted{{background:#eef1ef;color:var(--muted)}}
figure{{margin:24px 0;background:white;border:1px solid var(--line);border-radius:12px;padding:12px}}img{{display:block;width:100%;height:auto}}figcaption{{color:var(--muted);padding-top:8px}}
</style></head><body><main><h1>SciPlot physical-size QA and review preview</h1>
<p class="lede">Physical dimensions are machine-checked. The mosaics below are uncalibrated screen previews and do not establish final-size legibility.</p>
<section class="cards"><article class="card"><span>Eligible rules</span><strong>{summary['eligible_rule_count']}</strong></article>
<article class="card"><span>Physical size passed</span><strong>{summary['physical_size_passed_count']}</strong></article>
<article class="card"><span>Review previews</span><strong>{summary['contact_sheet_count']}</strong></article>
<article class="card"><span>Manual visual status</span><strong>{html.escape(summary['manual_visual_status'])}</strong></article></section>
<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Expected mm</th><th>PDF mm</th><th>TIFF mm</th><th>TIFF dpi</th><th>Status</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<section>{images}</section></main></body></html>"""
    return document


def _write_html(path: Path, payload: dict[str, Any], contact_sheets: list[Path]) -> None:
    path.write_text(
        _html_text(payload, contact_sheets, parent=path.parent),
        encoding="utf-8",
    )


def write_final_size_visual_review(
    *,
    output_dir: Path,
    rows: list[dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or datetime.now(UTC).isoformat()
    review_dir = output_dir / "final_size_visual_review"
    if review_dir.exists():
        shutil.rmtree(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    records = [_record_for_row(row) for row in rows]
    contact_sheets = _write_contact_sheets(review_dir / "contact_sheets", records)
    contact_sheet_sources = [_contact_sheet_metadata(path) for path in contact_sheets]
    eligible = [record for record in records if record["status"] != "not_run"]
    passed_count = sum(record["status"] == "passed" for record in eligible)
    failed_count = sum(record["status"] == "failed" for record in eligible)
    summary = {
        "rule_count": len(records),
        "eligible_rule_count": len(eligible),
        "physical_size_passed_count": passed_count,
        "physical_size_failed_count": failed_count,
        "not_run_count": sum(record["status"] == "not_run" for record in records),
        "contact_sheet_count": len(contact_sheets),
        "automated_status": "passed" if eligible and not failed_count else ("not_run" if not eligible else "failed"),
        "manual_visual_status": PENDING_REVIEW_STATUS if contact_sheets else "not_available",
        "review_surface": REVIEW_SURFACE,
        "physical_size_tolerance_mm": PHYSICAL_SIZE_TOLERANCE_MM,
        "tiff_dpi_tolerance": TIFF_DPI_TOLERANCE,
    }
    payload = {
        "kind": "sciplot_final_size_visual_review",
        "version": FINAL_SIZE_VISUAL_REVIEW_VERSION,
        "generated_at": timestamp,
        "summary": summary,
        "records": records,
        "contact_sheets": [str(path) for path in contact_sheets],
        "contact_sheet_sources": contact_sheet_sources,
        "manual_review": {
            "status": summary["manual_visual_status"],
            "review_surface": REVIEW_SURFACE,
            "required_checks": list(REQUIRED_PREVIEW_CHECKS),
            "decision": None,
            "reviewed_at": None,
            "reviewer": None,
            "notes": [],
        },
        "limitations": [
            "Automated checks validate physical page size, TIFF pixel density, and delivery-copy identity.",
            "Generated contact sheets are uncalibrated screen previews for visible defects only.",
            "A preview decision does not establish legibility at the canonical artifact's physical size.",
            "This review is not a journal-compliance claim and does not replace exact-current publication QA.",
        ],
    }
    json_path = review_dir / "final_size_visual_review.json"
    csv_path = review_dir / "final_size_visual_review.csv"
    markdown_path = review_dir / "final_size_visual_review.md"
    html_path = review_dir / "final_size_visual_review.html"
    atomic_write_json(json_path, json_safe(payload))
    _write_csv(csv_path, records)
    _write_markdown(markdown_path, payload)
    _write_html(html_path, payload, contact_sheets)
    return {
        "summary": summary,
        "records_by_rule": {record["rule_id"]: record for record in records},
        "artifacts": {
            "visual_review_json": str(json_path),
            "visual_review_csv": str(csv_path),
            "visual_review_markdown": str(markdown_path),
            "visual_review_html": str(html_path),
            **{
                f"visual_contact_sheet_{index:02d}": str(path)
                for index, path in enumerate(contact_sheets, start=1)
            },
        },
    }


def _read_json_object_strict(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain one object: {path}")
    return payload


def _strict_nonnegative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer.")
    return value


def _strict_positive_pair(value: object, *, label: str) -> tuple[float, float]:
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise ValueError(f"{label} must contain two positive numbers.")
    if any(isinstance(item, bool) or not isinstance(item, int | float) for item in value):
        raise ValueError(f"{label} must contain two positive numbers.")
    pair = float(value[0]), float(value[1])
    if min(pair) <= 0:
        raise ValueError(f"{label} must contain two positive numbers.")
    return pair


def _validate_passed_record(record: dict[str, Any], *, rule_id: str) -> None:
    if record.get("errors") != []:
        raise ValueError(f"Passed visual-review record `{rule_id}` contains errors.")
    _strict_positive_pair(
        record.get("expected_size_mm"),
        label=f"{rule_id} expected_size_mm",
    )
    pdf = record.get("pdf")
    tiff = record.get("tiff")
    if not isinstance(pdf, dict) or not isinstance(tiff, dict):
        raise ValueError(f"Passed visual-review record `{rule_id}` is missing PDF/TIFF evidence.")
    _strict_positive_pair(pdf.get("physical_size_mm"), label=f"{rule_id} PDF size")
    _strict_positive_pair(tiff.get("physical_size_mm"), label=f"{rule_id} TIFF size")
    _strict_positive_pair(tiff.get("dpi"), label=f"{rule_id} TIFF DPI")
    pixels = tiff.get("pixels")
    if (
        not isinstance(pixels, list | tuple)
        or len(pixels) != 2
        or any(type(value) is not int or value <= 0 for value in pixels)
    ):
        raise ValueError(f"Passed visual-review record `{rule_id}` has invalid TIFF pixels.")
    if any(
        value is not True
        for value in (
            pdf.get("within_tolerance"),
            pdf.get("copy_hash_matches"),
            tiff.get("within_tolerance"),
            tiff.get("dpi_is_300"),
            tiff.get("copy_hash_matches"),
        )
    ):
        raise ValueError(f"Passed visual-review record `{rule_id}` has failed artifact checks.")
    for label, artifact in (("PDF", pdf), ("TIFF", tiff)):
        if not isinstance(artifact.get("path"), str) or not artifact["path"].strip():
            raise ValueError(f"Passed visual-review record `{rule_id}` has no {label} path.")


def _validate_records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("Final-size visual review records must be a non-empty list.")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in value:
        if not isinstance(record, dict):
            raise ValueError("Final-size visual review records must contain objects.")
        rule_id = record.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id.strip() or rule_id != rule_id.strip():
            raise ValueError("Final-size visual review rule ids must be non-empty normalized strings.")
        if rule_id in seen:
            raise ValueError(f"Duplicate visual-review rule id `{rule_id}`.")
        seen.add(rule_id)
        status = record.get("status")
        if status not in {"passed", "failed", "not_run"}:
            raise ValueError(f"Visual-review record `{rule_id}` has invalid status `{status}`.")
        errors = record.get("errors")
        if not isinstance(errors, list) or not all(
            isinstance(error, str) and error.strip() for error in errors
        ):
            raise ValueError(f"Visual-review record `{rule_id}` has invalid errors.")
        if status == "passed":
            _validate_passed_record(record, rule_id=rule_id)
        elif status == "failed" and not errors:
            raise ValueError(f"Failed visual-review record `{rule_id}` has no error evidence.")
        elif status == "not_run" and (
            errors or record.get("manifest") is not None
        ):
            raise ValueError(f"Not-run visual-review record `{rule_id}` contains artifact evidence.")
        records.append(record)
    return records


def _validate_summary(
    value: object,
    *,
    records: list[dict[str, Any]],
    contact_sheet_count: int,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Final-size visual review summary must be an object.")
    counts = {
        "rule_count": len(records),
        "eligible_rule_count": sum(record["status"] != "not_run" for record in records),
        "physical_size_passed_count": sum(record["status"] == "passed" for record in records),
        "physical_size_failed_count": sum(record["status"] == "failed" for record in records),
        "not_run_count": sum(record["status"] == "not_run" for record in records),
        "contact_sheet_count": contact_sheet_count,
    }
    for key, expected in counts.items():
        observed = _strict_nonnegative_int(value.get(key), label=f"summary {key}")
        if observed != expected:
            raise ValueError(
                f"Final-size visual review summary `{key}` is {observed}; expected {expected}."
            )
    eligible = counts["eligible_rule_count"]
    failed = counts["physical_size_failed_count"]
    expected_automated = "passed" if eligible and not failed else ("not_run" if not eligible else "failed")
    if value.get("automated_status") != expected_automated:
        raise ValueError("Final-size visual review automated status does not match its records.")
    if value.get("manual_visual_status") not in {
        PENDING_REVIEW_STATUS,
        "passed",
        "failed",
    }:
        raise ValueError("Final-size visual review manual status is invalid.")
    if value.get("review_surface") != REVIEW_SURFACE:
        raise ValueError("Final-size visual review must declare an uncalibrated preview surface.")
    if value.get("physical_size_tolerance_mm") != PHYSICAL_SIZE_TOLERANCE_MM:
        raise ValueError("Final-size visual review physical-size tolerance drifted.")
    if value.get("tiff_dpi_tolerance") != TIFF_DPI_TOLERANCE:
        raise ValueError("Final-size visual review TIFF-DPI tolerance drifted.")
    return value


def _validate_manual_source(value: object, *, summary: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict):
        raise ValueError("Final-size visual review manual-review contract is missing.")
    if value.get("status") != summary["manual_visual_status"]:
        raise ValueError("Manual-review status does not match the visual-review summary.")
    if value.get("review_surface") != REVIEW_SURFACE:
        raise ValueError("Manual review must declare an uncalibrated preview surface.")
    checks = value.get("required_checks")
    if (
        not isinstance(checks, list)
        or len(checks) != len(REQUIRED_PREVIEW_CHECKS)
        or set(checks) != set(REQUIRED_PREVIEW_CHECKS)
        or not all(isinstance(check, str) for check in checks)
    ):
        raise ValueError("Final-size visual review required-check set is invalid.")
    return list(REQUIRED_PREVIEW_CHECKS)


def _validate_contact_sheets(
    payload: dict[str, Any],
    *,
    review_path: Path,
) -> tuple[list[Path], list[dict[str, Any]]]:
    raw_paths = payload.get("contact_sheets")
    if not isinstance(raw_paths, list) or not raw_paths or not all(
        isinstance(value, str) and value.strip() for value in raw_paths
    ):
        raise ValueError("Final-size visual review contact sheets are invalid.")
    contact_sheets = [Path(value).expanduser().resolve() for value in raw_paths]
    if len(set(contact_sheets)) != len(contact_sheets):
        raise ValueError("Final-size visual review contact sheets must be unique.")
    preview_root = (review_path.parent / "contact_sheets").resolve()
    for index, sheet in enumerate(contact_sheets, start=1):
        expected = preview_root / f"contact_sheet_{index:02d}.png"
        if sheet != expected:
            raise ValueError(
                "Visual-review previews must use the generated contact_sheets/contact_sheet_NN.png paths."
            )
    actual_sources = [_contact_sheet_metadata(path) for path in contact_sheets]
    stored_sources = payload.get("contact_sheet_sources")
    if stored_sources != actual_sources:
        raise ValueError("Visual-review preview hashes or image metadata no longer match generation.")
    return contact_sheets, actual_sources


def _resolved_artifact_path(value: object, *, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Acceptance artifact `{label}` is missing.")
    path = Path(value).expanduser()
    return (root / path if not path.is_absolute() else path).resolve()


def _validate_acceptance_binding(
    acceptance: dict[str, Any],
    *,
    acceptance_path: Path,
    review_path: Path,
    review_payload: dict[str, Any],
    records: list[dict[str, Any]],
    contact_sheets: list[Path],
    evidence_path: Path,
    decision_path: Path,
    source_sha256: str,
) -> None:
    if acceptance.get("kind") != "sciplot_ready_rule_acceptance":
        raise ValueError("Not a SciPlot ready-rule acceptance summary.")
    version = acceptance.get("version")
    if type(version) is not int or version != READY_RULE_ACCEPTANCE_VERSION:
        raise ValueError("Unsupported ready-rule acceptance version.")
    if acceptance.get("generated_at") != review_payload["generated_at"]:
        raise ValueError("Acceptance and visual-review generation timestamps do not match.")
    if acceptance.get("visual_review") != review_payload["summary"]:
        raise ValueError("Acceptance visual-review summary is not the supplied review source.")
    artifacts = acceptance.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("Acceptance artifacts are missing.")
    root = acceptance_path.parent
    expected_artifacts = {
        "summary": acceptance_path,
        "visual_review_json": review_path,
        "visual_review_csv": review_path.with_suffix(".csv"),
        "visual_review_markdown": review_path.with_suffix(".md"),
        "visual_review_html": review_path.with_suffix(".html"),
        "evidence_json": evidence_path,
    }
    for key, expected in expected_artifacts.items():
        if _resolved_artifact_path(artifacts.get(key), root=root, label=key) != expected:
            raise ValueError(f"Acceptance artifact `{key}` is not bound to this review run.")
    expected_sheet_keys = {
        f"visual_contact_sheet_{index:02d}" for index in range(1, len(contact_sheets) + 1)
    }
    actual_sheet_keys = {
        str(key) for key in artifacts if str(key).startswith("visual_contact_sheet_")
    }
    if actual_sheet_keys != expected_sheet_keys:
        raise ValueError("Acceptance contact-sheet artifact set does not match the review source.")
    for index, sheet in enumerate(contact_sheets, start=1):
        key = f"visual_contact_sheet_{index:02d}"
        if _resolved_artifact_path(artifacts.get(key), root=root, label=key) != sheet:
            raise ValueError(f"Acceptance artifact `{key}` is not bound to the reviewed PNG.")
    stored_review_hash = artifacts.get("visual_review_json_sha256")
    if stored_review_hash is not None and stored_review_hash != source_sha256:
        raise ValueError("Acceptance visual-review source hash no longer matches.")
    stored_decision = artifacts.get("manual_visual_review_decision")
    if stored_decision is not None and (
        _resolved_artifact_path(stored_decision, root=root, label="manual_visual_review_decision")
        != decision_path
    ):
        raise ValueError("Acceptance manual-decision artifact points outside this review run.")

    matrix = acceptance.get("matrix")
    if not isinstance(matrix, list) or not all(isinstance(row, dict) for row in matrix):
        raise ValueError("Acceptance matrix is invalid.")
    matrix_ids = [row.get("rule_id") for row in matrix]
    record_ids = [record["rule_id"] for record in records]
    if matrix_ids != record_ids or len(set(matrix_ids)) != len(matrix_ids):
        raise ValueError("Acceptance matrix rule ids do not match the visual-review records.")
    for row, record in zip(matrix, records, strict=True):
        if row.get("artifact_review") != record:
            raise ValueError(
                f"Acceptance artifact review for `{record['rule_id']}` does not match the review source."
            )
    selected = acceptance.get("selected_rule_ids")
    if not isinstance(selected, list) or len(set(selected)) != len(selected):
        raise ValueError("Acceptance selected rule ids are invalid.")
    eligible_ids = {record["rule_id"] for record in records if record["status"] != "not_run"}
    if set(selected) != eligible_ids:
        raise ValueError("Acceptance selected rule ids do not match eligible visual-review records.")


def _validate_evidence_binding(
    evidence: dict[str, Any],
    *,
    acceptance: dict[str, Any],
    generated_at: str,
    record_ids: list[str],
) -> None:
    if evidence.get("kind") != "sciplot_23_rule_evidence_status":
        raise ValueError("Not a SciPlot rule-evidence status artifact.")
    if type(evidence.get("version")) is not int or evidence["version"] != 1:
        raise ValueError("Unsupported rule-evidence status version.")
    if evidence.get("generated_at") != generated_at:
        raise ValueError("Evidence and visual-review generation timestamps do not match.")
    if not isinstance(evidence.get("summary"), dict):
        raise ValueError("Evidence summary is invalid.")
    if acceptance.get("evidence_status") != evidence["summary"]:
        raise ValueError("Acceptance and evidence summaries are not bound.")
    matrix = evidence.get("matrix")
    if not isinstance(matrix, list) or not all(isinstance(row, dict) for row in matrix):
        raise ValueError("Evidence matrix is invalid.")
    if [row.get("rule_id") for row in matrix] != record_ids:
        raise ValueError("Evidence matrix rule ids do not match the visual-review records.")


def _validate_existing_decision(
    decision: dict[str, Any],
    *,
    decision_path: Path,
    review_path: Path,
    acceptance: dict[str, Any],
) -> None:
    if decision.get("kind") != "sciplot_final_size_visual_decision":
        raise ValueError("Existing manual visual decision has the wrong kind.")
    if (
        type(decision.get("version")) is not int
        or decision["version"] != FINAL_SIZE_VISUAL_DECISION_VERSION
    ):
        raise ValueError("Existing manual visual decision has an unsupported version.")
    if Path(str(decision.get("review_source") or "")).expanduser().resolve() != review_path:
        raise ValueError("Existing manual visual decision belongs to another review source.")
    artifacts = acceptance.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("Acceptance artifacts are missing.")
    root = decision_path.parent.parent
    if (
        _resolved_artifact_path(
            artifacts.get("manual_visual_review_decision"),
            root=root,
            label="manual_visual_review_decision",
        )
        != decision_path
    ):
        raise ValueError("Acceptance is not bound to the existing manual decision.")
    expected_hash = artifacts.get("manual_visual_review_decision_sha256")
    if expected_hash != file_sha256(decision_path):
        raise ValueError("Existing manual visual decision hash no longer matches acceptance.")


def record_final_size_visual_decision(
    review_json: Path,
    *,
    reviewer: str,
    decision: str,
    notes: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Record a decision about uncalibrated previews after strict run binding."""

    review_path = review_json.expanduser().resolve()
    if review_path.name != "final_size_visual_review.json" or review_path.parent.name != "final_size_visual_review":
        raise ValueError("Visual review must use final_size_visual_review/final_size_visual_review.json.")
    normalized_decision = str(decision).strip().casefold()
    if normalized_decision not in {"passed", "failed"}:
        raise ValueError("Visual decision must be `passed` or `failed`.")
    normalized_reviewer = str(reviewer).strip()
    if not normalized_reviewer:
        raise ValueError("Visual decision reviewer must be a non-empty name.")

    project_dir = review_path.parent.parent
    acceptance_path = project_dir / "acceptance_summary.json"
    evidence_path = project_dir / "evidence_status.json"
    decision_path = review_path.parent / "manual_visual_review_decision.json"

    payload = _read_json_object_strict(review_path, label="Visual review JSON")
    acceptance = _read_json_object_strict(acceptance_path, label="Acceptance summary")
    evidence = _read_json_object_strict(evidence_path, label="Evidence status")
    if payload.get("kind") != "sciplot_final_size_visual_review":
        raise ValueError("Not a SciPlot final-size visual review artifact.")
    version = payload.get("version")
    if type(version) is not int or version != FINAL_SIZE_VISUAL_REVIEW_VERSION:
        raise ValueError("Unsupported final-size visual review version.")
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise ValueError("Final-size visual review is missing generated_at.")

    records = _validate_records(payload.get("records"))
    contact_sheets, contact_sheet_sources = _validate_contact_sheets(
        payload,
        review_path=review_path,
    )
    summary = _validate_summary(
        payload.get("summary"),
        records=records,
        contact_sheet_count=len(contact_sheets),
    )
    required_checks = _validate_manual_source(payload.get("manual_review"), summary=summary)
    if normalized_decision == "passed" and summary["automated_status"] != "passed":
        raise ValueError("Cannot pass preview review while automated artifact checks are not passed.")

    source_sha256 = file_sha256(review_path)
    _validate_acceptance_binding(
        acceptance,
        acceptance_path=acceptance_path,
        review_path=review_path,
        review_payload=payload,
        records=records,
        contact_sheets=contact_sheets,
        evidence_path=evidence_path,
        decision_path=decision_path,
        source_sha256=source_sha256,
    )
    _validate_evidence_binding(
        evidence,
        acceptance=acceptance,
        generated_at=generated_at,
        record_ids=[record["rule_id"] for record in records],
    )
    if decision_path.exists():
        existing_decision = _read_json_object_strict(
            decision_path,
            label="Existing manual visual decision",
        )
        _validate_existing_decision(
            existing_decision,
            decision_path=decision_path,
            review_path=review_path,
            acceptance=acceptance,
        )

    reviewed_at = datetime.now(UTC).isoformat()
    reviewed_rules = [
        record["rule_id"] for record in records if record["status"] != "not_run"
    ]
    manual_review = {
        "status": "completed",
        "decision": normalized_decision,
        "reviewed_at": reviewed_at,
        "reviewer": normalized_reviewer,
        "review_surface": REVIEW_SURFACE,
        "required_checks": required_checks,
        "reviewed_rule_ids": reviewed_rules,
        "contact_sheets_inspected": [str(path) for path in contact_sheets],
        "contact_sheet_sources": contact_sheet_sources,
        "checks": {check_id: normalized_decision == "passed" for check_id in required_checks},
        "notes": [str(note).strip() for note in notes if str(note).strip()],
    }
    updated_payload = deepcopy(payload)
    updated_summary = deepcopy(summary)
    updated_summary["manual_visual_status"] = normalized_decision
    updated_summary["manual_reviewed_at"] = reviewed_at
    updated_payload["manual_review"] = manual_review
    updated_payload["summary"] = updated_summary
    review_bytes = _json_bytes(updated_payload)
    review_sha256_after = _bytes_sha256(review_bytes)

    decision_payload = {
        "kind": "sciplot_final_size_visual_decision",
        "version": FINAL_SIZE_VISUAL_DECISION_VERSION,
        "review_source": str(review_path),
        "review_source_sha256_before_decision": source_sha256,
        "review_source_sha256_after_decision": review_sha256_after,
        "automated_status": updated_summary["automated_status"],
        **manual_review,
        "limitations": [
            "This records inspection of uncalibrated screen previews, not final-size legibility.",
            "Scientific claims, calibrated physical-size inspection, and journal compliance remain separate.",
        ],
    }
    decision_bytes = _json_bytes(decision_payload)

    updated_acceptance = deepcopy(acceptance)
    updated_acceptance["visual_review"] = updated_summary
    updated_artifacts = deepcopy(acceptance["artifacts"])
    updated_artifacts["visual_review_json_sha256"] = review_sha256_after
    updated_artifacts["manual_visual_review_decision"] = str(decision_path)
    updated_artifacts["manual_visual_review_decision_sha256"] = _bytes_sha256(decision_bytes)
    updated_acceptance["artifacts"] = updated_artifacts
    if normalized_decision == "failed":
        updated_acceptance["state"] = "needs_rule_repair"
        updated_acceptance["selected_state"] = "needs_rule_repair"

    updated_evidence = deepcopy(evidence)
    updated_evidence_summary = deepcopy(evidence["summary"])
    updated_evidence_summary["manual_visual_status"] = normalized_decision
    updated_evidence_summary["manual_reviewed_at"] = reviewed_at
    updated_evidence_summary["review_surface"] = REVIEW_SURFACE
    updated_evidence["summary"] = updated_evidence_summary
    updated_acceptance["evidence_status"] = updated_evidence_summary

    markdown_path = review_path.with_suffix(".md")
    html_path = review_path.with_suffix(".html")
    _replace_files_transactionally(
        {
            review_path: review_bytes,
            markdown_path: _markdown_text(updated_payload).encode("utf-8"),
            html_path: _html_text(
                updated_payload,
                contact_sheets,
                parent=html_path.parent,
            ).encode("utf-8"),
            decision_path: decision_bytes,
            acceptance_path: _json_bytes(updated_acceptance),
            evidence_path: _json_bytes(updated_evidence),
        }
    )
    return {
        "decision": decision_payload,
        "decision_path": str(decision_path),
        "review_path": str(review_path),
        "acceptance_summary": str(acceptance_path),
    }


__all__ = [
    "CONTACT_SHEET_COLUMNS",
    "CONTACT_SHEET_ROWS",
    "PHYSICAL_SIZE_TOLERANCE_MM",
    "TIFF_DPI_TOLERANCE",
    "record_final_size_visual_decision",
    "write_final_size_visual_review",
]
