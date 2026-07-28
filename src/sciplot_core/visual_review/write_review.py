"""Write one complete final-size visual-review evidence package."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.json_values import json_safe

from sciplot_core.visual_review.transaction import (
    PHYSICAL_SIZE_TOLERANCE_MM,
    TIFF_DPI_TOLERANCE,
    FINAL_SIZE_VISUAL_REVIEW_VERSION,
    REVIEW_SURFACE,
    PENDING_REVIEW_STATUS,
    REQUIRED_PREVIEW_CHECKS,
)

from sciplot_core.visual_review.artifact_records import (
    _record_for_row,
)

from sciplot_core.visual_review.contact_sheets import (
    _write_contact_sheets,
    _contact_sheet_metadata,
    _write_csv,
)

from sciplot_core.visual_review.report_text import (
    _write_markdown,
    _write_html,
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
        "automated_status": "passed"
        if eligible and not failed_count
        else ("not_run" if not eligible else "failed"),
        "manual_visual_status": PENDING_REVIEW_STATUS
        if contact_sheets
        else "not_available",
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
