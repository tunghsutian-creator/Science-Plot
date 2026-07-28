"""Validate review summaries, records, and manual source checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.visual_review.transaction import (
    PHYSICAL_SIZE_TOLERANCE_MM,
    TIFF_DPI_TOLERANCE,
    REVIEW_SURFACE,
    PENDING_REVIEW_STATUS,
    REQUIRED_PREVIEW_CHECKS,
)

from sciplot_core.visual_review.contact_sheets import (
    _contact_sheet_metadata,
)


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
    if any(
        isinstance(item, bool) or not isinstance(item, int | float) for item in value
    ):
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
        raise ValueError(
            f"Passed visual-review record `{rule_id}` is missing PDF/TIFF evidence."
        )
    _strict_positive_pair(pdf.get("physical_size_mm"), label=f"{rule_id} PDF size")
    _strict_positive_pair(tiff.get("physical_size_mm"), label=f"{rule_id} TIFF size")
    _strict_positive_pair(tiff.get("dpi"), label=f"{rule_id} TIFF DPI")
    pixels = tiff.get("pixels")
    if (
        not isinstance(pixels, list | tuple)
        or len(pixels) != 2
        or any(type(value) is not int or value <= 0 for value in pixels)
    ):
        raise ValueError(
            f"Passed visual-review record `{rule_id}` has invalid TIFF pixels."
        )
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
        raise ValueError(
            f"Passed visual-review record `{rule_id}` has failed artifact checks."
        )
    for label, artifact in (("PDF", pdf), ("TIFF", tiff)):
        if not isinstance(artifact.get("path"), str) or not artifact["path"].strip():
            raise ValueError(
                f"Passed visual-review record `{rule_id}` has no {label} path."
            )


def _validate_records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("Final-size visual review records must be a non-empty list.")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in value:
        if not isinstance(record, dict):
            raise ValueError("Final-size visual review records must contain objects.")
        rule_id = record.get("rule_id")
        if (
            not isinstance(rule_id, str)
            or not rule_id.strip()
            or rule_id != rule_id.strip()
        ):
            raise ValueError(
                "Final-size visual review rule ids must be non-empty normalized strings."
            )
        if rule_id in seen:
            raise ValueError(f"Duplicate visual-review rule id `{rule_id}`.")
        seen.add(rule_id)
        status = record.get("status")
        if status not in {"passed", "failed", "not_run"}:
            raise ValueError(
                f"Visual-review record `{rule_id}` has invalid status `{status}`."
            )
        errors = record.get("errors")
        if not isinstance(errors, list) or not all(
            isinstance(error, str) and error.strip() for error in errors
        ):
            raise ValueError(f"Visual-review record `{rule_id}` has invalid errors.")
        if status == "passed":
            _validate_passed_record(record, rule_id=rule_id)
        elif status == "failed" and not errors:
            raise ValueError(
                f"Failed visual-review record `{rule_id}` has no error evidence."
            )
        elif status == "not_run" and (errors or record.get("manifest") is not None):
            raise ValueError(
                f"Not-run visual-review record `{rule_id}` contains artifact evidence."
            )
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
        "physical_size_passed_count": sum(
            record["status"] == "passed" for record in records
        ),
        "physical_size_failed_count": sum(
            record["status"] == "failed" for record in records
        ),
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
    expected_automated = (
        "passed"
        if eligible and not failed
        else ("not_run" if not eligible else "failed")
    )
    if value.get("automated_status") != expected_automated:
        raise ValueError(
            "Final-size visual review automated status does not match its records."
        )
    if value.get("manual_visual_status") not in {
        PENDING_REVIEW_STATUS,
        "passed",
        "failed",
    }:
        raise ValueError("Final-size visual review manual status is invalid.")
    if value.get("review_surface") != REVIEW_SURFACE:
        raise ValueError(
            "Final-size visual review must declare an uncalibrated preview surface."
        )
    if value.get("physical_size_tolerance_mm") != PHYSICAL_SIZE_TOLERANCE_MM:
        raise ValueError("Final-size visual review physical-size tolerance drifted.")
    if value.get("tiff_dpi_tolerance") != TIFF_DPI_TOLERANCE:
        raise ValueError("Final-size visual review TIFF-DPI tolerance drifted.")
    return value


def _validate_manual_source(value: object, *, summary: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict):
        raise ValueError("Final-size visual review manual-review contract is missing.")
    if value.get("status") != summary["manual_visual_status"]:
        raise ValueError(
            "Manual-review status does not match the visual-review summary."
        )
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
    if (
        not isinstance(raw_paths, list)
        or not raw_paths
        or not all(isinstance(value, str) and value.strip() for value in raw_paths)
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
        raise ValueError(
            "Visual-review preview hashes or image metadata no longer match generation."
        )
    return contact_sheets, actual_sources
