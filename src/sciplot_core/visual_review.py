# ruff: noqa: E501
# Embedded self-contained HTML/CSS is intentionally kept literal for auditability.

from __future__ import annotations

import csv
import hashlib
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw, ImageFont, ImageOps

from sciplot_core._utils import json_safe
from sciplot_core.policy import DEFAULT_FIGURE_SIZE

PHYSICAL_SIZE_TOLERANCE_MM = 0.25
TIFF_DPI_TOLERANCE = 0.5
CONTACT_SHEET_COLUMNS = 4
CONTACT_SHEET_ROWS = 2
CONTACT_SHEET_TILE_SIZE = (620, 660)


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

    request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    render_options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
    expected = _parse_size_mm(render_options.get("size") or DEFAULT_FIGURE_SIZE)
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


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# SciPlot final-size visual review",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"- Physical size passed: {summary['physical_size_passed_count']}/{summary['eligible_rule_count']}",
        f"- Contact sheets: {summary['contact_sheet_count']}",
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
            "Physical dimensions and TIFF DPI are machine-checked. Contact sheets are generated for human review "
            "of labels, legends, clipping, occlusion, and final-size readability. This artifact does not claim "
            "journal compliance or a completed manual review.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_html(path: Path, payload: dict[str, Any], contact_sheets: list[Path]) -> None:
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
        f'<figure><img src="{html.escape(sheet.relative_to(path.parent).as_posix(), quote=True)}" '
        f'alt="Final-size contact sheet {index}"><figcaption>Contact sheet {index}</figcaption></figure>'
        for index, sheet in enumerate(contact_sheets, start=1)
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SciPlot final-size visual review</title><style>
:root{{--ink:#17211d;--muted:#607068;--line:#dbe3de;--paper:#f5f7f5;--green:#176b46;--red:#9f2d2d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 ui-sans-serif,system-ui,sans-serif}}
main{{max-width:1500px;margin:auto;padding:34px 28px 60px}}h1{{margin:0 0 4px;font-size:28px}}.lede{{color:var(--muted)}}
.cards{{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}}.card{{background:white;border:1px solid var(--line);border-radius:12px;padding:12px 16px;min-width:180px}}.card strong{{display:block;font-size:24px}}
.table-wrap{{overflow:auto;background:white;border:1px solid var(--line);border-radius:12px}}table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{background:#eef2ef}}
.pill{{border-radius:999px;padding:2px 8px;font-size:12px}}.pill.ok{{background:#e3f3ea;color:var(--green)}}.pill.bad{{background:#f8e2e2;color:var(--red)}}.pill.muted{{background:#eef1ef;color:var(--muted)}}
figure{{margin:24px 0;background:white;border:1px solid var(--line);border-radius:12px;padding:12px}}img{{display:block;width:100%;height:auto}}figcaption{{color:var(--muted);padding-top:8px}}
</style></head><body><main><h1>SciPlot final-size visual review</h1>
<p class="lede">Machine-checked physical dimensions plus contact sheets for human inspection. Lifecycle and journal compliance remain separate.</p>
<section class="cards"><article class="card"><span>Eligible rules</span><strong>{summary['eligible_rule_count']}</strong></article>
<article class="card"><span>Physical size passed</span><strong>{summary['physical_size_passed_count']}</strong></article>
<article class="card"><span>Contact sheets</span><strong>{summary['contact_sheet_count']}</strong></article>
<article class="card"><span>Manual visual status</span><strong>{html.escape(summary['manual_visual_status'])}</strong></article></section>
<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Expected mm</th><th>PDF mm</th><th>TIFF mm</th><th>TIFF dpi</th><th>Status</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<section>{images}</section></main></body></html>"""
    path.write_text(document, encoding="utf-8")


def write_final_size_visual_review(
    *,
    output_dir: Path,
    rows: list[dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or datetime.now(UTC).isoformat()
    review_dir = output_dir / "final_size_visual_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    records = [_record_for_row(row) for row in rows]
    contact_sheets = _write_contact_sheets(review_dir / "contact_sheets", records)
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
        "manual_visual_status": "pending_contact_sheet_review" if contact_sheets else "not_available",
        "physical_size_tolerance_mm": PHYSICAL_SIZE_TOLERANCE_MM,
        "tiff_dpi_tolerance": TIFF_DPI_TOLERANCE,
    }
    payload = {
        "kind": "sciplot_final_size_visual_review",
        "version": 1,
        "generated_at": timestamp,
        "summary": summary,
        "records": records,
        "contact_sheets": [str(path) for path in contact_sheets],
        "manual_review": {
            "status": summary["manual_visual_status"],
            "required_checks": [
                "labels_legible_at_final_size",
                "legend_not_occluding_data",
                "no_text_or_data_clipping",
                "markers_and_lines_distinguishable",
                "no_unexplained_blank_or_corrupt_panel",
            ],
            "decision": None,
            "reviewed_at": None,
            "reviewer": None,
            "notes": [],
        },
        "limitations": [
            "Automated checks validate physical page size, TIFF pixel density, and delivery-copy identity.",
            "Generated contact sheets require an explicit human or agent visual decision.",
            "This review is not a journal-compliance claim and does not replace exact-current publication QA.",
        ],
    }
    json_path = review_dir / "final_size_visual_review.json"
    csv_path = review_dir / "final_size_visual_review.csv"
    markdown_path = review_dir / "final_size_visual_review.md"
    html_path = review_dir / "final_size_visual_review.html"
    json_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record_final_size_visual_decision(
    review_json: Path,
    *,
    reviewer: str,
    decision: str,
    notes: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Record the explicit visual decision after all generated contact sheets are inspected."""

    review_path = review_json.expanduser().resolve()
    normalized_decision = str(decision).strip().casefold()
    if normalized_decision not in {"passed", "failed"}:
        raise ValueError("Visual decision must be `passed` or `failed`.")
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    if normalized_decision == "passed" and summary.get("automated_status") != "passed":
        raise ValueError("Cannot record a passing visual decision while automated size checks are not passed.")
    contact_sheets = [Path(str(value)) for value in payload.get("contact_sheets", [])]
    missing = [str(path) for path in contact_sheets if not path.exists()]
    if not contact_sheets or missing:
        raise FileNotFoundError(f"Visual decision requires all contact sheets; missing: {missing or 'all'}")

    reviewed_at = datetime.now(UTC).isoformat()
    reviewed_rules = [
        str(record["rule_id"])
        for record in payload.get("records", [])
        if isinstance(record, dict) and record.get("status") != "not_run"
    ]
    required_checks = list((payload.get("manual_review") or {}).get("required_checks") or [])
    source_sha256 = _sha256(review_path)
    manual_review = {
        "status": "completed",
        "decision": normalized_decision,
        "reviewed_at": reviewed_at,
        "reviewer": str(reviewer).strip() or "unspecified",
        "reviewed_rule_ids": reviewed_rules,
        "contact_sheets_inspected": [str(path) for path in contact_sheets],
        "checks": {check_id: normalized_decision == "passed" for check_id in required_checks},
        "notes": [str(note) for note in notes if str(note).strip()],
    }
    payload["manual_review"] = manual_review
    summary["manual_visual_status"] = normalized_decision
    summary["manual_reviewed_at"] = reviewed_at
    payload["summary"] = summary
    review_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    _write_markdown(review_path.with_suffix(".md"), payload)
    _write_html(review_path.with_suffix(".html"), payload, contact_sheets)

    decision_payload = {
        "kind": "sciplot_final_size_visual_decision",
        "version": 1,
        "review_source": str(review_path),
        "review_source_sha256_before_decision": source_sha256,
        "automated_status": summary.get("automated_status"),
        **manual_review,
        "limitations": [
            "This records final-size artifact inspection, not broader journal compliance.",
            "Scientific claims and publication intent remain independently reviewable contracts.",
        ],
    }
    decision_path = review_path.parent / "manual_visual_review_decision.json"
    decision_path.write_text(
        json.dumps(json_safe(decision_payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    project_dir = review_path.parent.parent
    acceptance_path = project_dir / "acceptance_summary.json"
    if acceptance_path.exists():
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
        acceptance["visual_review"] = summary
        artifacts = acceptance.get("artifacts") if isinstance(acceptance.get("artifacts"), dict) else {}
        artifacts["manual_visual_review_decision"] = str(decision_path)
        acceptance["artifacts"] = artifacts
        if normalized_decision == "failed":
            acceptance["state"] = "needs_rule_repair"
            acceptance["selected_state"] = "needs_rule_repair"
        acceptance_path.write_text(
            json.dumps(json_safe(acceptance), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    evidence_path = project_dir / "evidence_status.json"
    if evidence_path.exists():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence_summary = evidence.get("summary") if isinstance(evidence.get("summary"), dict) else {}
        evidence_summary["manual_visual_status"] = normalized_decision
        evidence_summary["manual_reviewed_at"] = reviewed_at
        evidence["summary"] = evidence_summary
        evidence_path.write_text(json.dumps(json_safe(evidence), indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "decision": decision_payload,
        "decision_path": str(decision_path),
        "review_path": str(review_path),
        "acceptance_summary": str(acceptance_path) if acceptance_path.exists() else None,
    }


__all__ = [
    "CONTACT_SHEET_COLUMNS",
    "CONTACT_SHEET_ROWS",
    "PHYSICAL_SIZE_TOLERANCE_MM",
    "TIFF_DPI_TOLERANCE",
    "record_final_size_visual_decision",
    "write_final_size_visual_review",
]
