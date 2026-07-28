"""Normalize and verify exact-current export artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core._paths import resolved_path_is_within
from sciplot_core.policy import canonical_export_format

from sciplot_gui.studio_project_status.project_runs import (
    _read_json,
    _canonical_json_sha256,
)


def _normalized_export_format(value: object) -> str:
    try:
        return canonical_export_format(value, allow_legacy=True)
    except ValueError:
        return ""


def _export_records(
    evidence: dict[str, Any],
    *,
    standalone: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    if standalone:
        records = evidence.get("exports")
        requested = evidence.get("requested_formats")
    else:
        result = (
            evidence.get("result") if isinstance(evidence.get("result"), dict) else {}
        )
        records = result.get("exports")
        if not isinstance(records, list):
            records = evidence.get("exports")
        requested = result.get("export_formats")
    record_list = (
        [item for item in records if isinstance(item, dict)]
        if isinstance(records, list)
        else []
    )
    requested_list = (
        [_normalized_export_format(item) for item in requested]
        if isinstance(requested, list)
        else []
    )
    return record_list, [item for item in requested_list if item]


def _verify_export_artifacts(
    *,
    evidence: dict[str, Any],
    evidence_path: Path | None,
    standalone: bool,
) -> dict[str, Any]:
    records, requested_formats = _export_records(
        evidence,
        standalone=standalone,
    )
    recorded_formats = {
        _normalized_export_format(record.get("format"))
        for record in records
        if _normalized_export_format(record.get("format"))
    }
    required_formats = (
        set(requested_formats) or recorded_formats
        if standalone
        else {"pdf", "tiff_300", *requested_formats}
    )
    issues: list[str] = []
    verified_formats: set[str] = set()
    verified_records: list[dict[str, Any]] = []
    evidence_root = (
        evidence_path.parent.expanduser().resolve()
        if evidence_path is not None
        else None
    )
    qa_payload = (
        evidence.get("artifact_qa")
        if standalone and isinstance(evidence.get("artifact_qa"), dict)
        else evidence.get("qa")
        if isinstance(evidence.get("qa"), dict)
        else {}
    )
    qa_hashes_by_path: dict[Path, tuple[str, str]] = {}
    for key, export_format in (("pdfs", "pdf"), ("tiffs", "tiff_300")):
        qa_records = qa_payload.get(key)
        if not isinstance(qa_records, list):
            continue
        for qa_record in qa_records:
            if not isinstance(qa_record, dict):
                continue
            path_value = qa_record.get("path")
            qa_hash = str(qa_record.get("sha256") or "").strip()
            if not isinstance(path_value, str) or not qa_hash:
                continue
            try:
                qa_path = Path(path_value).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            qa_hashes_by_path[qa_path] = (export_format, qa_hash)
    if not records:
        issues.append("No export artifact records are present.")
    seen_bindings: set[tuple[str, str]] = set()
    seen_paths: set[Path] = set()
    for index, record in enumerate(records):
        export_format = _normalized_export_format(record.get("format"))
        path_value = record.get("path")
        recorded_hash = str(record.get("sha256") or "").strip()
        if not export_format:
            issues.append(f"Export record {index + 1} has no format.")
            continue
        if not isinstance(path_value, str) or not path_value.strip():
            issues.append(f"Export record {index + 1} has no path.")
            continue
        artifact_path = Path(path_value).expanduser()
        if not artifact_path.is_absolute() and evidence_root is not None:
            artifact_path = evidence_root / artifact_path
        try:
            artifact_path = artifact_path.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            issues.append(f"Export record {index + 1} path is invalid: {exc}")
            continue
        if evidence_root is None or not resolved_path_is_within(
            artifact_path,
            evidence_root,
        ):
            issues.append(
                f"Export artifact is outside the evidence directory: {artifact_path}"
            )
            continue
        figure_binding = str(
            record.get("figure_id") or record.get("document") or "primary"
        ).strip()
        binding = (figure_binding, export_format)
        if binding in seen_bindings:
            issues.append(
                "Duplicate export format record for one figure: "
                f"{figure_binding} / {export_format}"
            )
        if artifact_path in seen_paths:
            issues.append(f"Duplicate export artifact path: {artifact_path}")
        seen_bindings.add(binding)
        seen_paths.add(artifact_path)
        qa_binding = qa_hashes_by_path.get(artifact_path)
        if qa_binding is not None and qa_binding[0] != export_format:
            issues.append(
                f"Artifact QA format does not match export record: {artifact_path}"
            )
        if recorded_hash and qa_binding is not None and qa_binding[1] != recorded_hash:
            issues.append(
                f"Artifact QA hash does not match export record: {artifact_path}"
            )
        expected_hash = recorded_hash or (
            qa_binding[1] if qa_binding is not None else ""
        )
        try:
            exists = artifact_path.is_file()
            size_bytes = artifact_path.stat().st_size if exists else 0
            actual_hash = existing_file_sha256(artifact_path) if exists else None
        except OSError as exc:
            issues.append(f"Could not inspect export {artifact_path}: {exc}")
            continue
        try:
            recorded_size = int(record.get("size_bytes") or 0)
        except (TypeError, ValueError):
            recorded_size = -1
        suffix_matches = (
            artifact_path.suffix.casefold() == ".pdf"
            if export_format == "pdf"
            else artifact_path.suffix.casefold() in {".tif", ".tiff"}
            if export_format == "tiff_300"
            else artifact_path.suffix.casefold() == ".png"
            if export_format in {"png_300", "png_600"}
            else artifact_path.suffix.casefold() == ".svg"
            if export_format == "svg"
            else False
        )
        current = bool(
            exists
            and size_bytes > 0
            and record.get("exists") is True
            and recorded_size == size_bytes
            and expected_hash
            and actual_hash == expected_hash
            and suffix_matches
        )
        verified_records.append(
            {
                "format": export_format,
                "path": str(artifact_path),
                "exists": exists,
                "size_bytes": size_bytes,
                "expected_sha256": expected_hash or None,
                "actual_sha256": actual_hash,
                "current": current,
            }
        )
        if current:
            verified_formats.add(export_format)
        else:
            issues.append(
                f"Export artifact is missing, empty, changed, or has the "
                f"wrong suffix: {artifact_path}"
            )
    missing_formats = sorted(required_formats - verified_formats)
    if missing_formats:
        issues.append("Missing current export formats: " + ", ".join(missing_formats))
    current = bool(records and not issues)
    return {
        "status": "passed" if current else "failed",
        "current": current,
        "required_formats": sorted(required_formats),
        "verified_formats": sorted(verified_formats),
        "records": verified_records,
        "issues": issues,
    }


def _standalone_qa_report_current(
    *,
    evidence: dict[str, Any],
    evidence_path: Path | None,
    embedded_qa: dict[str, Any],
) -> bool:
    if evidence_path is None:
        return False
    value = evidence.get("artifact_qa_path")
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = evidence_path.parent / candidate
    try:
        candidate = candidate.resolve()
        candidate.relative_to(evidence_path.parent.resolve())
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return False
        recorded = _read_json(candidate)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        return False
    return _canonical_json_sha256(recorded) == _canonical_json_sha256(embedded_qa)
