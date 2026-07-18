from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core._utils import existing_file_sha256, json_safe
from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.studio import (
    export_studio_document,
    publish_standalone_export_receipt,
    publish_studio_export_run,
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return payload


def _request_path_value(value: object, *, base_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _validate_project_request_pair(
    project_dir: Path | None,
    request_path: Path | None,
) -> None:
    if (project_dir is None) != (request_path is None):
        raise ValueError(
            "project_dir and request_path must be provided together."
        )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _project_manifest_payload(project_dir: Path) -> dict[str, Any]:
    candidates = [
        project_dir / "intake_manifest.json",
        *sorted(project_dir.glob("*.sciplot.json")),
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            return _read_json(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return {}


def _registered_manifest_candidates(
    project_dir: Path,
    project_manifest: dict[str, Any],
) -> list[Path]:
    resolved_project = project_dir.expanduser().resolve()
    runs_root = (resolved_project / "runs").resolve()
    local_candidates = [
        candidate.resolve()
        for candidate in reversed(
            sorted(
                (resolved_project / "runs").glob(
                    "studio_*/manifest.json"
                )
            )
        )
    ]
    registered_candidates: list[Path] = []
    studio = (
        project_manifest.get("studio")
        if isinstance(project_manifest.get("studio"), dict)
        else {}
    )
    last_export = (
        studio.get("last_export_run")
        if isinstance(studio.get("last_export_run"), dict)
        else {}
    )
    last_run = (
        project_manifest.get("last_run")
        if isinstance(project_manifest.get("last_run"), dict)
        else {}
    )
    for value in (
        last_export.get("manifest"),
        Path(str(last_export["output"])) / "manifest.json"
        if last_export.get("output")
        else None,
        Path(str(last_run["output"])) / "manifest.json"
        if last_run.get("output")
        else None,
    ):
        if value is None:
            continue
        candidate = Path(str(value)).expanduser()
        if not candidate.is_absolute():
            candidate = resolved_project / candidate
        registered_candidates.append(candidate.resolve())
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in [*local_candidates, *registered_candidates]:
        if (
            candidate.name != "manifest.json"
            or not _is_within(candidate, runs_root)
            or candidate in seen
        ):
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _latest_project_run(
    project_dir: Path,
    project_manifest: dict[str, Any],
    *,
    request: dict[str, Any],
) -> tuple[Path | None, dict[str, Any]]:
    request_digest = _canonical_json_sha256(request)
    for candidate in _registered_manifest_candidates(project_dir, project_manifest):
        if not candidate.is_file():
            continue
        snapshot_path = candidate.parent / "request_snapshot.json"
        try:
            snapshot = _read_json(snapshot_path)
            manifest = _read_json(candidate)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if _canonical_json_sha256(snapshot) != request_digest:
            continue
        manifest_request = manifest.get("request")
        if (
            isinstance(manifest_request, dict)
            and _canonical_json_sha256(manifest_request) != request_digest
        ):
            continue
        return candidate, manifest
    return None, {}


def _source_reference(
    source_path: Path | None,
    *,
    transform_ledger: object,
) -> dict[str, Any] | None:
    if source_path is None or not isinstance(transform_ledger, dict):
        return None
    try:
        resolved_source = source_path.expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    steps = (
        transform_ledger.get("steps")
        if isinstance(transform_ledger.get("steps"), list)
        else []
    )
    records: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        inputs = (
            step.get("input_artifacts")
            if isinstance(step.get("input_artifacts"), list)
            else []
        )
        records.extend(item for item in inputs if isinstance(item, dict))
    for record in records:
        value = record.get("path")
        if not isinstance(value, str):
            continue
        try:
            referenced_path = Path(value).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if referenced_path == resolved_source:
            return record
    return None


def _source_content_record(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if resolved.is_file():
        return {
            "kind": "file",
            "size_bytes": resolved.stat().st_size,
            "sha256": existing_file_sha256(resolved),
        }
    digest = hashlib.sha256()
    member_count = 0
    total_bytes = 0
    for member in sorted(
        candidate for candidate in resolved.rglob("*") if candidate.is_file()
    ):
        member_hash = existing_file_sha256(member)
        if member_hash is None:
            raise OSError(f"Could not hash source member: {member}")
        digest.update(member.relative_to(resolved).as_posix().encode("utf-8"))
        digest.update(member_hash.encode("ascii"))
        member_count += 1
        total_bytes += member.stat().st_size
    return {
        "kind": "directory",
        "size_bytes": total_bytes,
        "member_count": member_count,
        "sha256": digest.hexdigest(),
    }


def _source_status(
    source_path: Path | None,
    *,
    transform_ledger: object,
    audit_source: bool,
) -> dict[str, Any]:
    if source_path is None:
        return {
            "status": "not_established",
            "path": None,
            "exists": False,
            "audit_status": "not_available",
        }
    try:
        resolved = source_path.expanduser().resolve()
        exists = resolved.exists()
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "status": "audit_failed",
            "path": str(source_path),
            "exists": False,
            "audit_status": "audit_failed",
            "audit_error": str(exc),
        }
    base = {
        "status": "present" if exists else "missing",
        "path": str(resolved),
        "exists": exists,
        "audit_status": "not_computed",
    }
    if not audit_source or not exists:
        return base
    try:
        current = _source_content_record(resolved)
        reference = _source_reference(
            resolved,
            transform_ledger=transform_ledger,
        )
        current_hash = current.get("sha256")
        reference_hash = (
            reference.get("sha256")
            if isinstance(reference, dict)
            else None
        )
        if reference_hash and current_hash == reference_hash:
            audit_status = "matches_last_run_lineage"
        elif reference_hash:
            audit_status = "changed_since_last_run"
        else:
            audit_status = "current_hash_not_bound_to_a_run"
    except Exception as exc:
        return {
            **base,
            "audit_status": "audit_failed",
            "audit_error": f"{type(exc).__name__}: {exc}",
        }
    return {
        **base,
        "kind": current.get("kind"),
        "size_bytes": current.get("size_bytes"),
        "member_count": current.get("member_count"),
        "sha256": current_hash,
        "reference_sha256": reference_hash,
        "audit_status": audit_status,
    }


def _mapping_application_from_run(
    latest_run: dict[str, Any],
) -> dict[str, Any]:
    application = latest_run.get("data_mapping_application")
    if isinstance(application, dict):
        return application
    result = (
        latest_run.get("result")
        if isinstance(latest_run.get("result"), dict)
        else {}
    )
    application = result.get("data_mapping_application")
    return application if isinstance(application, dict) else {}


def _mapping_coverage_from_run(
    latest_run: dict[str, Any],
) -> dict[str, Any]:
    coverage = latest_run.get("data_mapping_coverage")
    if isinstance(coverage, dict):
        return coverage
    result = (
        latest_run.get("result")
        if isinstance(latest_run.get("result"), dict)
        else {}
    )
    coverage = result.get("data_mapping_coverage")
    return coverage if isinstance(coverage, dict) else {}


def _bind_mapping_to_artifact_qa(
    mapping: dict[str, Any],
    *,
    artifact_qa_current: bool,
) -> dict[str, Any]:
    updated = dict(mapping)
    base_verified = updated.get("verification_base_valid") is True
    evidence_current = bool(base_verified and artifact_qa_current)
    updated["artifact_qa_current"] = bool(artifact_qa_current)
    updated["evidence_current"] = evidence_current
    if updated.get("status") not in {
        "not_applied",
        "invalid",
        "audit_pending",
    }:
        updated["status"] = "verified" if evidence_current else "unverified"
    return updated


def _mapping_status(
    request: dict[str, Any],
    *,
    request_path: Path,
    latest_run: dict[str, Any],
    request_error: str | None,
    artifact_qa_current: bool,
    audit_mapping: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if request_error is not None:
        return (
            {
                "status": "invalid",
                "coverage_status": "invalid",
                "reason": f"The current request is invalid: {request_error}",
                "verification_base_valid": False,
                "artifact_qa_current": False,
                "evidence_current": False,
            },
            request,
        )
    if not request.get("data_mapping_execution"):
        return (
            {
                "status": "not_applied",
                "coverage_status": "not_applicable",
                "reason": "The project uses its confirmed source directly.",
                "verification_base_valid": True,
                "artifact_qa_current": bool(artifact_qa_current),
                "evidence_current": bool(artifact_qa_current),
            },
            request,
        )
    if not audit_mapping:
        return (
            {
                "status": "audit_pending",
                "coverage_status": "not_computed",
                "reason": (
                    "Use Refresh Audit to revalidate the current data-mapping "
                    "application and rendered-source coverage."
                ),
                "verification_base_valid": False,
                "artifact_qa_current": bool(artifact_qa_current),
                "evidence_current": False,
            },
            request,
        )
    try:
        effective, application = resolve_data_mapping_request(
            request,
            base_dir=request_path.parent,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        return (
            {
                "status": "invalid",
                "coverage_status": "unknown",
                "reason": str(exc),
                "verification_base_valid": False,
                "artifact_qa_current": False,
                "evidence_current": False,
            },
            request,
        )
    coverage = _mapping_coverage_from_run(latest_run)
    application_payload = application if isinstance(application, dict) else {}
    run_application = _mapping_application_from_run(latest_run)
    application_status = str(application_payload.get("status") or "validated")
    coverage_status = str(coverage.get("status") or "not_run")
    application_matches = bool(
        application_payload
        and run_application
        and _canonical_json_sha256(application_payload)
        == _canonical_json_sha256(run_application)
    )
    base_verified = bool(
        application_status == "validated"
        and coverage_status == "passed"
        and application_matches
    )
    if application_status != "validated":
        status = "invalid"
        reason = "The current data-mapping application is not validated."
    elif coverage_status != "passed":
        status = "unverified"
        reason = (
            "Current-run mapping coverage has not passed; "
            f"reported status is {coverage_status}."
        )
    elif not application_matches:
        status = "unverified"
        reason = (
            "Current-run coverage is not bound to the current "
            "data_mapping_application."
        )
    else:
        status = "unverified"
        reason = "Current mapping evidence is awaiting artifact-QA binding."
    mapping = {
        "status": status,
        "application_status": application_status,
        "coverage_status": coverage_status,
        "proposal_id": application_payload.get("proposal_id"),
        "source_root": application_payload.get("source_root"),
        "effective_input": application_payload.get("effective_input"),
        "application_matches_current_run": application_matches,
        "verification_base_valid": base_verified,
        "reason": reason,
    }
    return (
        _bind_mapping_to_artifact_qa(
            mapping,
            artifact_qa_current=artifact_qa_current,
        ),
        effective,
    )


def _normalized_export_format(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"tif", "tiff", "tiff300", "tiff_300dpi"}:
        return "tiff_300"
    return normalized


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
            evidence.get("result")
            if isinstance(evidence.get("result"), dict)
            else {}
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
    seen_formats: set[str] = set()
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
            issues.append(
                f"Export record {index + 1} path is invalid: {exc}"
            )
            continue
        if evidence_root is None or not _is_within(
            artifact_path,
            evidence_root,
        ):
            issues.append(
                f"Export artifact is outside the evidence directory: "
                f"{artifact_path}"
            )
            continue
        if export_format in seen_formats:
            issues.append(
                f"Duplicate export format record: {export_format}"
            )
        if artifact_path in seen_paths:
            issues.append(
                f"Duplicate export artifact path: {artifact_path}"
            )
        seen_formats.add(export_format)
        seen_paths.add(artifact_path)
        qa_binding = qa_hashes_by_path.get(artifact_path)
        if (
            qa_binding is not None
            and qa_binding[0] != export_format
        ):
            issues.append(
                f"Artifact QA format does not match export record: "
                f"{artifact_path}"
            )
        if (
            recorded_hash
            and qa_binding is not None
            and qa_binding[1] != recorded_hash
        ):
            issues.append(
                f"Artifact QA hash does not match export record: "
                f"{artifact_path}"
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
        issues.append(
            "Missing current export formats: " + ", ".join(missing_formats)
        )
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
    return _canonical_json_sha256(recorded) == _canonical_json_sha256(
        embedded_qa
    )


def _qa_display_status(
    *,
    artifact_status: str,
    ready: bool,
    current_document: bool,
    exports_current: bool,
) -> tuple[str, bool]:
    artifact_qa_current = bool(
        current_document
        and exports_current
        and artifact_status in {"passed", "not_required"}
    )
    if not current_document:
        status = "stale_for_current_document"
    elif not exports_current:
        status = "stale_or_invalid_export_artifacts"
    elif ready and artifact_qa_current:
        status = "passed_for_current_document"
    else:
        status = "failed_for_current_document"
    return status, artifact_qa_current


def _qa_status(
    *,
    evidence: dict[str, Any],
    evidence_path: Path | None,
    saved_sha256: str | None,
    modified: bool,
    standalone: bool,
) -> dict[str, Any]:
    if not evidence:
        return {
            "status": "not_run",
            "artifact_status": "not_run",
            "ready_to_use": False,
            "current_document": False,
            "exports_current": False,
            "qa_report_current": False,
            "artifact_qa_current": False,
            "export_artifacts": {
                "status": "not_run",
                "current": False,
                "issues": [],
            },
            "evidence": None,
        }
    qa = (
        evidence.get("artifact_qa")
        if standalone and isinstance(evidence.get("artifact_qa"), dict)
        else evidence.get("qa")
        if isinstance(evidence.get("qa"), dict)
        else {}
    )
    artifact_status = str(qa.get("status") or "not_run")
    evidence_hash = (
        evidence.get("document_sha256")
        if standalone
        else evidence.get("exported_document_hash")
        or (
            evidence.get("document_state", {}).get("current_hash")
            if isinstance(evidence.get("document_state"), dict)
            else None
        )
    )
    ready = (
        evidence.get("export_ready") is True
        if standalone
        else evidence.get("ready_to_use") is True
    )
    document_hash_current = bool(
        not modified
        and saved_sha256
        and evidence_hash
        and saved_sha256 == evidence_hash
    )
    export_artifacts = _verify_export_artifacts(
        evidence=evidence,
        evidence_path=evidence_path,
        standalone=standalone,
    )
    qa_report_current = (
        _standalone_qa_report_current(
            evidence=evidence,
            evidence_path=evidence_path,
            embedded_qa=qa,
        )
        if standalone
        else True
    )
    evidence_artifacts_current = bool(
        export_artifacts["current"] is True
        and qa_report_current
    )
    current_document = bool(
        document_hash_current
        and evidence_artifacts_current
    )
    status, artifact_qa_current = _qa_display_status(
        artifact_status=artifact_status,
        ready=bool(ready),
        current_document=current_document,
        exports_current=evidence_artifacts_current,
    )
    return {
        "status": status,
        "artifact_status": artifact_status,
        "ready_to_use": bool(ready),
        "current_document": current_document,
        "document_hash_current": document_hash_current,
        "exports_current": export_artifacts["current"] is True,
        "qa_report_current": qa_report_current,
        "artifact_qa_current": artifact_qa_current,
        "scope": "exact_current_artifact_qa",
        "evidence_document_sha256": evidence_hash,
        "evidence": str(evidence_path) if evidence_path is not None else None,
        "export_artifacts": export_artifacts,
        "state": evidence.get("state"),
    }


def _project_audit_state(status: dict[str, Any]) -> str:
    if status.get("mode") != "project":
        return "not_applicable"
    source = (
        status.get("source")
        if isinstance(status.get("source"), dict)
        else {}
    )
    mapping = (
        status.get("mapping")
        if isinstance(status.get("mapping"), dict)
        else {}
    )
    provenance = (
        status.get("provenance")
        if isinstance(status.get("provenance"), dict)
        else {}
    )
    if provenance.get("full_project_evidence_current") is True:
        return "current"
    source_audit = str(source.get("audit_status") or "")
    mapping_status = str(mapping.get("status") or "")
    if source_audit == "audit_failed" or mapping_status in {
        "audit_failed",
        "invalid",
    }:
        return "failed"
    if source_audit == "not_computed" or mapping_status == "audit_pending":
        return "pending"
    return "stale"


def _workflow_status(
    status: dict[str, Any],
    *,
    exporting: bool = False,
) -> dict[str, Any]:
    if exporting:
        state = "exporting"
        message = "Saving and validating the exact-current Veusz document."
    else:
        document = (
            status.get("document")
            if isinstance(status.get("document"), dict)
            else {}
        )
        qa = (
            status.get("qa")
            if isinstance(status.get("qa"), dict)
            else {}
        )
        provenance = (
            status.get("provenance")
            if isinstance(status.get("provenance"), dict)
            else {}
        )
        result_ready = bool(
            qa.get("artifact_qa_current") is True
            and (
                status.get("mode") == "standalone_vsz"
                or provenance.get("project_delivery_current") is True
            )
        )
        if result_ready:
            state = "ready"
            message = "Exact-current result artifacts are ready."
        elif (
            document.get("modified") is True
            or qa.get("evidence") is None
            or qa.get("document_hash_current") is False
        ):
            state = "editing"
            message = "Save and export the current Veusz document when ready."
        else:
            state = "needs_fix"
            message = "The current export or delivery needs review."
    return {
        "state": state,
        "result_ready": state == "ready",
        "audit_state": _project_audit_state(status),
        "message": message,
    }


def _result_targets(
    *,
    live_document: dict[str, Any],
    qa: dict[str, Any],
    evidence_path: Path | None,
    delivery: object = None,
    delivery_current: bool = False,
) -> dict[str, dict[str, Any]]:
    pdf_path: Path | None = None
    pdf_sha256: str | None = None
    export_artifacts = (
        qa.get("export_artifacts")
        if isinstance(qa.get("export_artifacts"), dict)
        else {}
    )
    records = (
        export_artifacts.get("records")
        if isinstance(export_artifacts.get("records"), list)
        else []
    )
    evidence_root = (
        evidence_path.parent.expanduser().resolve()
        if evidence_path is not None
        else None
    )
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("format") != "pdf"
            or record.get("current") is not True
            or evidence_root is None
        ):
            continue
        candidate = _evidence_path(
            record.get("path"),
            evidence_root=evidence_root,
        )
        if candidate is not None and candidate.is_file():
            pdf_path = candidate
            pdf_sha256 = str(
                record.get("expected_sha256")
                or record.get("actual_sha256")
                or ""
            ).strip() or None
            break

    delivery_root: Path | None = None
    if (
        delivery_current
        and qa.get("artifact_qa_current") is True
        and isinstance(delivery, dict)
        and evidence_root is not None
    ):
        candidate = _evidence_path(
            delivery.get("delivery_root") or delivery.get("path"),
            evidence_root=evidence_root,
        )
        if candidate is not None and candidate.is_dir():
            delivery_root = candidate

    document_value = live_document.get("path")
    document_path = (
        Path(str(document_value)).expanduser().resolve()
        if isinstance(document_value, str) and document_value.strip()
        else None
    )
    return {
        "pdf": {
            "path": str(pdf_path) if pdf_path is not None else None,
            "evidence_root": (
                str(evidence_root)
                if evidence_root is not None
                else None
            ),
            "sha256": pdf_sha256,
            "current": bool(
                pdf_path is not None
                and qa.get("artifact_qa_current") is True
            ),
            "available": False,
        },
        "delivery": {
            "path": (
                str(delivery_root)
                if delivery_root is not None
                else None
            ),
            "evidence_root": (
                str(evidence_root)
                if evidence_root is not None
                else None
            ),
            "current": delivery_root is not None,
            "available": False,
        },
        "vsz": {
            "path": (
                str(document_path)
                if document_path is not None
                else None
            ),
            "reveal_path": (
                str(document_path.parent)
                if document_path is not None
                else None
            ),
            "evidence_root": (
                str(document_path.parent)
                if document_path is not None
                else None
            ),
            "current": bool(
                document_path is not None
                and document_path.is_file()
            ),
            "available": False,
        },
    }


def _finalize_status(
    status: dict[str, Any],
    *,
    exporting: bool = False,
) -> dict[str, Any]:
    updated = dict(status)
    workflow = _workflow_status(updated, exporting=exporting)
    updated["workflow"] = workflow
    results = (
        updated.get("results")
        if isinstance(updated.get("results"), dict)
        else {}
    )
    finalized_results: dict[str, Any] = {}
    for key in ("pdf", "delivery", "vsz"):
        target = (
            dict(results.get(key))
            if isinstance(results.get(key), dict)
            else {
                "path": None,
                "current": False,
            }
        )
        target["available"] = bool(
            not exporting
            and target.get("current") is True
            and (
                target.get("reveal_path")
                if key == "vsz"
                else target.get("path")
            )
        )
        finalized_results[key] = target
    updated["results"] = finalized_results
    return updated


def _live_document_payload(
    *,
    document_path: Path,
    document: Any,
    render_sha256: str | None,
    saved_sha256: str | None = None,
) -> dict[str, Any]:
    resolved_document = document_path.expanduser().resolve()
    modified = bool(document.isModified())
    if saved_sha256 is None or not modified:
        saved_sha256 = existing_file_sha256(resolved_document)
    return {
        "path": str(resolved_document),
        "exists": resolved_document.is_file(),
        "modified": modified,
        "revision": int(document.changeset),
        "saved_sha256": saved_sha256,
        "live_render_sha256": render_sha256,
        "hash_scope": (
            "saved_vsz_and_exact_current_render"
            if render_sha256
            else "saved_vsz_only"
        ),
    }


def _evidence_path(
    value: object,
    *,
    evidence_root: Path,
) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = evidence_root / candidate
    try:
        candidate = candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if _is_within(candidate, evidence_root) else None


def _nonempty_evidence_path(
    value: object,
    *,
    evidence_root: Path,
) -> bool:
    candidate = _evidence_path(value, evidence_root=evidence_root)
    if candidate is None:
        return False
    try:
        if candidate.is_file():
            return candidate.stat().st_size > 0
        if candidate.is_dir():
            return any(item.is_file() for item in candidate.rglob("*"))
    except OSError:
        return False
    return False


def _recorded_file_current(
    record: dict[str, Any],
    *,
    evidence_root: Path,
    hash_fields: tuple[str, ...],
) -> bool:
    candidate = _evidence_path(
        record.get("path"),
        evidence_root=evidence_root,
    )
    if candidate is None:
        return False
    try:
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return False
        actual_hash = existing_file_sha256(candidate)
    except OSError:
        return False
    expected_hash = next(
        (
            str(record.get(field) or "").strip()
            for field in hash_fields
            if str(record.get(field) or "").strip()
        ),
        "",
    )
    return bool(expected_hash and actual_hash == expected_hash)


def _contract_artifacts_current(
    contract: object,
    *,
    evidence_root: Path,
) -> bool:
    if not isinstance(contract, dict) or contract.get("complete") is not True:
        return False
    artifacts = contract.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False
    for record in artifacts:
        if not isinstance(record, dict) or record.get("exists") is not True:
            return False
        path_value = record.get("path")
        if isinstance(path_value, str) and path_value.strip():
            candidate = _evidence_path(
                path_value,
                evidence_root=evidence_root,
            )
            if candidate is None or not candidate.exists():
                return False
    return True


def _delivery_artifacts_current(
    delivery: object,
    *,
    evidence_root: Path,
) -> bool:
    if not _contract_artifacts_current(
        delivery,
        evidence_root=evidence_root,
    ):
        return False
    assert isinstance(delivery, dict)
    for key, hash_fields in (
        ("data_csvs", ("sha256",)),
        ("figures", ("delivery_sha256",)),
        ("project_documents", ("delivery_sha256",)),
    ):
        records = delivery.get(key)
        if not isinstance(records, list) or not records:
            return False
        if not all(
            isinstance(record, dict)
            and _recorded_file_current(
                record,
                evidence_root=evidence_root,
                hash_fields=hash_fields,
            )
            for record in records
        ):
            return False
    return _nonempty_evidence_path(
        delivery.get("open_in_veusz"),
        evidence_root=evidence_root,
    )


def _provenance_status(
    *,
    latest_path: Path | None,
    transform_status: str,
    raw_archive_path: Path | None,
    package: object,
    delivery: object,
    mapping: dict[str, Any],
    qa: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    evidence_root = latest_path.parent if latest_path is not None else None
    raw_archive_current = bool(
        evidence_root is not None
        and raw_archive_path is not None
        and _nonempty_evidence_path(
            str(raw_archive_path),
            evidence_root=evidence_root,
        )
    )
    package_current = bool(
        evidence_root is not None
        and _contract_artifacts_current(
            package,
            evidence_root=evidence_root,
        )
    )
    delivery_current = bool(
        evidence_root is not None
        and _delivery_artifacts_current(
            delivery,
            evidence_root=evidence_root,
        )
    )
    run_evidence_complete = bool(
        latest_path is not None
        and transform_status in {"runtime_recorded", "confirmed"}
        and raw_archive_current
        and package_current
        and delivery_current
    )
    mapping_current = mapping.get("status") in {
        "not_applied",
        "verified",
    }
    source_current = (
        source.get("audit_status") == "matches_last_run_lineage"
    )
    full_project_evidence_current = bool(
        run_evidence_complete
        and source_current
        and mapping_current
        and qa.get("artifact_qa_current") is True
    )
    audit_pending = bool(
        source.get("audit_status") == "not_computed"
        or mapping.get("status") == "audit_pending"
    )
    current_result_awaiting_audit = bool(
        run_evidence_complete
        and qa.get("artifact_qa_current") is True
        and audit_pending
    )
    return {
        "status": (
            "current_full_project_evidence"
            if full_project_evidence_current
            else "audit_pending_for_current_project"
            if current_result_awaiting_audit
            else "incomplete_or_stale_project_evidence"
        ),
        "complete": full_project_evidence_current,
        "full_project_evidence_current": full_project_evidence_current,
        "audit_pending": current_result_awaiting_audit,
        "run_evidence_complete": run_evidence_complete,
        "request_snapshot_current": latest_path is not None,
        "source_current": source_current,
        "artifact_qa_current": qa.get("artifact_qa_current") is True,
        "mapping_current": mapping_current,
        "transform_status": transform_status,
        "raw_archive": (
            str(raw_archive_path)
            if raw_archive_path is not None
            else None
        ),
        "raw_archive_current": raw_archive_current,
        "package_complete": (
            isinstance(package, dict)
            and package.get("complete") is True
        ),
        "package_current": package_current,
        "project_delivery_complete": (
            isinstance(delivery, dict)
            and delivery.get("complete") is True
        ),
        "project_delivery_current": delivery_current,
    }


def build_studio_project_status(
    *,
    document_path: Path,
    document: Any,
    project_dir: Path | None,
    request_path: Path | None,
    render_sha256: str | None = None,
    audit_source: bool = False,
) -> dict[str, Any]:
    _validate_project_request_pair(project_dir, request_path)
    resolved_document = document_path.expanduser().resolve()
    live_document = _live_document_payload(
        document_path=resolved_document,
        document=document,
        render_sha256=render_sha256,
    )
    saved_sha256 = live_document.get("saved_sha256")
    modified = live_document["modified"] is True
    if project_dir is None:
        receipt_path = (
            resolved_document.parent
            / "exports"
            / "standalone_export_receipt.json"
        )
        try:
            receipt = _read_json(receipt_path) if receipt_path.is_file() else {}
        except (OSError, ValueError, json.JSONDecodeError):
            receipt = {}
        qa = _qa_status(
            evidence=receipt,
            evidence_path=receipt_path if receipt else None,
            saved_sha256=(
                str(saved_sha256)
                if isinstance(saved_sha256, str)
                else None
            ),
            modified=modified,
            standalone=True,
        )
        status = {
            "kind": "sciplot_studio_project_status",
            "version": 1,
            "mode": "standalone_vsz",
            "project": None,
            "document": live_document,
            "source": {
                "status": "not_established",
                "path": None,
                "exists": False,
                "audit_status": "not_available",
                "reason": (
                    "A standalone receipt does not establish the raw-source "
                    "or transform lineage."
                ),
            },
            "mapping": {
                "status": "unavailable",
                "coverage_status": "unavailable",
            },
            "provenance": {
                "status": "not_established",
                "complete": False,
                "full_project_evidence_current": False,
                "project_delivery_complete": False,
                "project_delivery_current": False,
            },
            "qa": qa,
            "results": _result_targets(
                live_document=live_document,
                qa=qa,
                evidence_path=receipt_path if receipt else None,
            ),
        }
        return _finalize_status(status)

    resolved_project = project_dir.expanduser().resolve()
    assert request_path is not None
    resolved_request = request_path.expanduser().resolve()
    project_manifest = _project_manifest_payload(resolved_project)
    try:
        request = _read_json(resolved_request)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        request = {}
        request_error: str | None = str(exc)
    else:
        request_error = None
    if request_error is None:
        latest_path, latest_run = _latest_project_run(
            resolved_project,
            project_manifest,
            request=request,
        )
    else:
        latest_path, latest_run = None, {}
    qa = _qa_status(
        evidence=latest_run,
        evidence_path=latest_path,
        saved_sha256=(
            str(saved_sha256)
            if isinstance(saved_sha256, str)
            else None
        ),
        modified=modified,
        standalone=False,
    )
    mapping, _effective_request = _mapping_status(
        request,
        request_path=resolved_request,
        latest_run=latest_run,
        request_error=request_error,
        artifact_qa_current=qa.get("artifact_qa_current") is True,
        audit_mapping=audit_source,
    )
    try:
        source_path = _request_path_value(
            request.get("input"),
            base_dir=resolved_request.parent,
        )
    except (OSError, RuntimeError, ValueError):
        source_path = None
    try:
        mapping_source_root = _request_path_value(
            mapping.get("source_root"),
            base_dir=resolved_request.parent,
        )
    except (OSError, RuntimeError, ValueError):
        mapping_source_root = None
    if mapping.get("status") == "verified" and mapping_source_root is not None:
        source_path = mapping_source_root
    transform_ledger = (
        latest_run.get("transform_ledger")
        if isinstance(latest_run.get("transform_ledger"), dict)
        else {}
    )
    raw_archive = (
        latest_run.get("raw_archive")
        if isinstance(latest_run.get("raw_archive"), dict)
        else {}
    )
    try:
        raw_archive_path = _request_path_value(
            raw_archive.get("path"),
            base_dir=(
                latest_path.parent
                if latest_path is not None
                else resolved_project
            ),
        )
    except (OSError, RuntimeError, ValueError):
        raw_archive_path = None
    transform_status = (
        str(transform_ledger.get("status") or "not_run")
        if isinstance(transform_ledger, dict)
        else "not_run"
    )
    package = (
        latest_run.get("package_contract")
        if isinstance(latest_run.get("package_contract"), dict)
        else {}
    )
    delivery = (
        latest_run.get("delivery_package")
        if isinstance(latest_run.get("delivery_package"), dict)
        else {}
    )
    source = {
        **_source_status(
            source_path,
            transform_ledger=transform_ledger,
            audit_source=audit_source,
        ),
        "effective_input": mapping.get("effective_input"),
    }
    provenance = _provenance_status(
        latest_path=latest_path,
        transform_status=transform_status,
        raw_archive_path=raw_archive_path,
        package=package,
        delivery=delivery,
        mapping=mapping,
        qa=qa,
        source=source,
    )
    status = {
        "kind": "sciplot_studio_project_status",
        "version": 1,
        "mode": "project",
        "project": {
            "name": (
                project_manifest.get("project_name")
                or resolved_project.name
            ),
            "path": str(resolved_project),
            "request": str(resolved_request),
            "request_status": "invalid" if request_error else "loaded",
            "request_error": request_error,
            "request_snapshot_current": latest_path is not None,
            "evidence_run": (
                str(latest_path)
                if latest_path is not None
                else None
            ),
            "rule_id": request.get("rule_id"),
            "template": request.get("template"),
        },
        "document": live_document,
        "source": source,
        "mapping": mapping,
        "provenance": provenance,
        "qa": qa,
        "results": _result_targets(
            live_document=live_document,
            qa=qa,
            evidence_path=latest_path,
            delivery=delivery,
            delivery_current=(
                provenance.get("project_delivery_current") is True
            ),
        ),
    }
    return _finalize_status(status)


def export_result_message(
    payload: dict[str, Any],
) -> tuple[str, str, str]:
    if payload.get("ready_to_use") is True and payload.get("status") == "passed":
        if payload.get("scope") == "standalone_exact_current_export":
            receipt = (
                payload.get("standalone_export")
                if isinstance(payload.get("standalone_export"), dict)
                else {}
            )
            return (
                "information",
                "SciPlot exact-current export",
                "PDF/TIFF export and artifact QA passed.\n\n"
                f"Receipt: {receipt.get('receipt_path')}\n\n"
                "This standalone receipt does not establish raw-source, "
                "transform-lineage, or portable-project provenance.",
            )
        run = (
            payload.get("studio_run")
            if isinstance(payload.get("studio_run"), dict)
            else {}
        )
        return (
            "information",
            "SciPlot project export",
            "PDF/TIFF, QA, and the portable project delivery passed.\n\n"
            f"Review: {run.get('review_html')}\n"
            f"Output: {run.get('output')}",
        )
    evidence = (
        payload.get("standalone_export")
        if isinstance(payload.get("standalone_export"), dict)
        else payload.get("studio_run")
        if isinstance(payload.get("studio_run"), dict)
        else {}
    )
    qa = (
        evidence.get("artifact_qa")
        if isinstance(evidence.get("artifact_qa"), dict)
        else evidence.get("qa")
        if isinstance(evidence.get("qa"), dict)
        else {}
    )
    return (
        "warning",
        "SciPlot export needs review",
        "Files may have been written, but SciPlot did not mark this export "
        "ready.\n\n"
        f"State: {payload.get('state') or evidence.get('state') or 'failed'}\n"
        f"QA: {qa.get('status') or 'not_run'}\n"
        f"Evidence: {evidence.get('receipt_path') or evidence.get('output')}",
    )


def _short_hash(value: object) -> str:
    text = str(value or "")
    return f"{text[:12]}…" if len(text) > 12 else text or "—"


def _status_text(status: dict[str, Any]) -> str:
    document = status["document"]
    source = status["source"]
    mapping = status["mapping"]
    provenance = status["provenance"]
    qa = status["qa"]
    workflow = (
        status.get("workflow")
        if isinstance(status.get("workflow"), dict)
        else _workflow_status(status)
    )
    project = status.get("project")
    lines = [
        f"Mode: {'Project package' if status['mode'] == 'project' else 'Standalone VSZ'}",
        f"Result: {workflow.get('state')} — {workflow.get('message')}",
        f"Audit: {workflow.get('audit_state')}",
    ]
    if isinstance(project, dict):
        lines.extend(
            [
                f"Project: {project.get('name')}",
                f"Request: {project.get('request_status')} "
                f"(snapshot current: "
                f"{project.get('request_snapshot_current') is True})",
                f"Rule / template: {project.get('rule_id') or '—'} / "
                f"{project.get('template') or '—'}",
            ]
        )
    lines.extend(
        [
            "",
            f"Document: {Path(str(document['path'])).name}",
            f"Live state: {'modified, not saved' if document['modified'] else 'saved'} "
            f"(revision {document['revision']})",
            f"Saved VSZ SHA-256: {_short_hash(document.get('saved_sha256'))}",
            f"Live render SHA-256: {_short_hash(document.get('live_render_sha256'))}",
            "",
            f"Source: {source.get('status')} / {source.get('audit_status')}",
            f"Source path: {source.get('path') or 'not established'}",
            f"Source SHA-256: {_short_hash(source.get('sha256'))}",
            f"Mapping: {mapping.get('status')} "
            f"(coverage: {mapping.get('coverage_status')})",
            f"Project evidence: {provenance.get('status')}",
            f"Artifact QA: {qa.get('status')} "
            f"(QA result: {qa.get('artifact_status')}, "
            f"exports current: {qa.get('exports_current') is True})",
            f"Evidence: {qa.get('evidence') or 'not run'}",
        ]
    )
    return "\n".join(lines)


class StudioProjectBridge(QtCore.QObject):
    """Read-only SciPlot status and exact-current export on one Veusz window."""

    statusChanged = QtCore.pyqtSignal(object)
    exportFinished = QtCore.pyqtSignal(object)

    def __init__(
        self,
        window: Any,
        document_path: Path,
        *,
        project_dir: Path | None,
        request_path: Path | None,
    ) -> None:
        _validate_project_request_pair(project_dir, request_path)
        super().__init__(window)
        self.window = window
        self.document = window.document
        self.plot = window.plot
        self.document_path = document_path.expanduser().resolve()
        self.project_dir = (
            project_dir.expanduser().resolve()
            if project_dir is not None
            else None
        )
        self.request_path = (
            request_path.expanduser().resolve()
            if request_path is not None
            else None
        )
        self.status_snapshot: dict[str, Any] = {}
        self._exporting = False
        self.dock = self._build_dock()
        self.dock.hide()
        self.window.addDockWidget(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
            self.dock,
        )
        self.document.signalModified.connect(self._document_modified)
        self.dock.visibilityChanged.connect(self._dock_visibility_changed)
        self.refresh_button.clicked.connect(self.refresh_full)
        self.export_button.clicked.connect(self.export_current_document)
        self.open_pdf_button.clicked.connect(self.open_current_pdf)
        self.show_delivery_button.clicked.connect(self.show_current_delivery)
        self.reveal_vsz_button.clicked.connect(self.reveal_current_vsz)
        self.refresh()

    @property
    def mode(self) -> str:
        return "project" if self.project_dir is not None else "standalone_vsz"

    def _build_dock(self) -> QtWidgets.QDockWidget:
        dock = QtWidgets.QDockWidget("SciPlot Project", self.window)
        dock.setObjectName("sciplotStudioProjectDock")
        dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        body = QtWidgets.QWidget(dock)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        intro = QtWidgets.QLabel(
            "Read-only project, source, mapping, and exact-current QA status. "
            "All editing remains in Veusz."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.status_view = QtWidgets.QPlainTextEdit()
        self.status_view.setReadOnly(True)
        self.status_view.setLineWrapMode(
            QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self.status_view.setMinimumWidth(320)
        layout.addWidget(self.status_view, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("Refresh Audit")
        self.export_button = QtWidgets.QPushButton("Save && Export PDF/TIFF")
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.export_button, 1)
        layout.addLayout(buttons)

        result_buttons = QtWidgets.QHBoxLayout()
        self.open_pdf_button = QtWidgets.QPushButton("Open PDF")
        self.show_delivery_button = QtWidgets.QPushButton("Show Delivery")
        self.reveal_vsz_button = QtWidgets.QPushButton("Reveal VSZ")
        self.open_pdf_button.setToolTip(
            "Open the current PDF that passed exact-current artifact QA."
        )
        self.show_delivery_button.setToolTip(
            "Show the current portable project delivery directory."
        )
        self.reveal_vsz_button.setToolTip(
            "Reveal the directory containing the authoritative Veusz document."
        )
        result_buttons.addWidget(self.open_pdf_button)
        result_buttons.addWidget(self.show_delivery_button)
        result_buttons.addWidget(self.reveal_vsz_button)
        layout.addLayout(result_buttons)
        dock.setWidget(body)
        return dock

    def _current_render_sha256(self) -> str | None:
        assistant = getattr(self.window, "_sciplot_assistant_bridge", None)
        if assistant is not None and hasattr(assistant, "current_render_sha256"):
            try:
                digest = assistant.current_render_sha256()
            except Exception:
                return None
            normalized = str(digest or "").strip().casefold()
            if len(normalized) == 64 and all(
                character in "0123456789abcdef"
                for character in normalized
            ):
                return normalized
        # The native plot pixmap can lag the Veusz document queue. Without the
        # assistant's revision-checked capture, no render digest is asserted.
        return None

    def _publish_status(self, status: dict[str, Any]) -> dict[str, Any]:
        self.status_snapshot = status
        self.status_view.setPlainText(_status_text(status))
        self._update_controls(status)
        self.statusChanged.emit(status)
        return status

    def _update_controls(self, status: dict[str, Any]) -> None:
        workflow = (
            status.get("workflow")
            if isinstance(status.get("workflow"), dict)
            else {}
        )
        exporting = bool(
            self._exporting or workflow.get("state") == "exporting"
        )
        self.refresh_button.setEnabled(not exporting)
        self.export_button.setEnabled(not exporting)
        results = (
            status.get("results")
            if isinstance(status.get("results"), dict)
            else {}
        )
        for key, button in (
            ("pdf", self.open_pdf_button),
            ("delivery", self.show_delivery_button),
            ("vsz", self.reveal_vsz_button),
        ):
            target = (
                results.get(key)
                if isinstance(results.get(key), dict)
                else {}
            )
            button.setEnabled(
                bool(not exporting and target.get("available") is True)
            )

    def _audit_failure_status(self, exc: Exception) -> dict[str, Any]:
        if self.status_snapshot:
            status = {
                **self.status_snapshot,
                "audit_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
            workflow = (
                dict(status.get("workflow"))
                if isinstance(status.get("workflow"), dict)
                else _workflow_status(status)
            )
            workflow["audit_state"] = "failed"
            status["workflow"] = workflow
        else:
            status = {
                "kind": "sciplot_studio_project_status",
                "version": 1,
                "mode": self.mode,
                "project": None,
                "document": _live_document_payload(
                    document_path=self.document_path,
                    document=self.document,
                    render_sha256=None,
                ),
                "source": {
                    "status": "audit_failed",
                    "path": None,
                    "audit_status": "audit_failed",
                },
                "mapping": {
                    "status": "audit_failed",
                    "coverage_status": "unknown",
                },
                "provenance": {
                    "status": "audit_failed",
                    "complete": False,
                    "full_project_evidence_current": False,
                },
                "qa": {
                    "status": "audit_failed",
                    "artifact_status": "not_run",
                    "artifact_qa_current": False,
                    "exports_current": False,
                    "evidence": None,
                },
                "audit_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        self.status_snapshot = status
        self.status_view.setPlainText(
            f"{_status_text(status)}\n\n"
            f"Audit error: {type(exc).__name__}: {exc}"
        )
        self._update_controls(status)
        self.statusChanged.emit(status)
        return status

    def refresh(
        self,
        *,
        capture_render: bool = False,
        audit_source: bool = False,
    ) -> dict[str, Any]:
        render_sha256 = (
            self._current_render_sha256()
            if capture_render
            else self.status_snapshot.get("document", {}).get(
                "live_render_sha256"
            )
        )
        if self.status_snapshot:
            previous_revision = self.status_snapshot.get("document", {}).get(
                "revision"
            )
            if previous_revision != int(self.document.changeset):
                render_sha256 = None
        try:
            status = build_studio_project_status(
                document_path=self.document_path,
                document=self.document,
                project_dir=self.project_dir,
                request_path=self.request_path,
                render_sha256=render_sha256,
                audit_source=audit_source,
            )
        except Exception as exc:
            return self._audit_failure_status(exc)
        return self._publish_status(status)

    def _refresh_document_state(self) -> dict[str, Any]:
        if not self.status_snapshot:
            return self.refresh()
        previous_document = (
            self.status_snapshot.get("document")
            if isinstance(self.status_snapshot.get("document"), dict)
            else {}
        )
        previous_revision = previous_document.get("revision")
        current_revision = int(self.document.changeset)
        render_sha256 = (
            previous_document.get("live_render_sha256")
            if previous_revision == current_revision
            else None
        )
        live_document = _live_document_payload(
            document_path=self.document_path,
            document=self.document,
            render_sha256=(
                str(render_sha256)
                if isinstance(render_sha256, str)
                else None
            ),
            saved_sha256=(
                str(previous_document.get("saved_sha256"))
                if previous_document.get("saved_sha256")
                else None
            ),
        )
        status = {
            **self.status_snapshot,
            "document": live_document,
        }
        previous_qa = (
            status.get("qa")
            if isinstance(status.get("qa"), dict)
            else {}
        )
        qa = dict(previous_qa)
        if qa.get("evidence") is not None:
            evidence_hash = qa.get("evidence_document_sha256")
            document_hash_current = bool(
                live_document.get("modified") is False
                and live_document.get("saved_sha256")
                and evidence_hash
                and live_document.get("saved_sha256") == evidence_hash
            )
            current_document = bool(
                document_hash_current
                and qa.get("exports_current") is True
            )
            qa_status, artifact_qa_current = _qa_display_status(
                artifact_status=str(
                    qa.get("artifact_status") or "not_run"
                ),
                ready=qa.get("ready_to_use") is True,
                current_document=current_document,
                exports_current=qa.get("exports_current") is True,
            )
            qa.update(
                {
                    "status": qa_status,
                    "current_document": current_document,
                    "document_hash_current": document_hash_current,
                    "artifact_qa_current": artifact_qa_current,
                }
            )
        status["qa"] = qa
        if status.get("mode") == "project":
            mapping = (
                status.get("mapping")
                if isinstance(status.get("mapping"), dict)
                else {}
            )
            mapping = _bind_mapping_to_artifact_qa(
                mapping,
                artifact_qa_current=qa.get("artifact_qa_current") is True,
            )
            status["mapping"] = mapping
            provenance = (
                dict(status.get("provenance"))
                if isinstance(status.get("provenance"), dict)
                else {}
            )
            mapping_current = mapping.get("status") in {
                "not_applied",
                "verified",
            }
            full_current = bool(
                provenance.get("run_evidence_complete") is True
                and provenance.get("source_current") is True
                and mapping_current
                and qa.get("artifact_qa_current") is True
            )
            source = (
                status.get("source")
                if isinstance(status.get("source"), dict)
                else {}
            )
            audit_pending = bool(
                source.get("audit_status") == "not_computed"
                or mapping.get("status") == "audit_pending"
            )
            current_result_awaiting_audit = bool(
                provenance.get("run_evidence_complete") is True
                and qa.get("artifact_qa_current") is True
                and audit_pending
            )
            provenance.update(
                {
                    "status": (
                        "current_full_project_evidence"
                        if full_current
                        else "audit_pending_for_current_project"
                        if current_result_awaiting_audit
                        else "incomplete_or_stale_project_evidence"
                    ),
                    "complete": full_current,
                    "full_project_evidence_current": full_current,
                    "audit_pending": current_result_awaiting_audit,
                    "artifact_qa_current": (
                        qa.get("artifact_qa_current") is True
                    ),
                    "mapping_current": mapping_current,
                }
            )
            status["provenance"] = provenance
        results = (
            dict(status.get("results"))
            if isinstance(status.get("results"), dict)
            else {}
        )
        pdf = (
            dict(results.get("pdf"))
            if isinstance(results.get("pdf"), dict)
            else {}
        )
        pdf["current"] = bool(
            pdf.get("path")
            and qa.get("artifact_qa_current") is True
        )
        results["pdf"] = pdf
        delivery = (
            dict(results.get("delivery"))
            if isinstance(results.get("delivery"), dict)
            else {}
        )
        delivery["current"] = bool(
            delivery.get("path")
            and qa.get("artifact_qa_current") is True
            and status.get("provenance", {}).get(
                "project_delivery_current"
            )
            is True
        )
        results["delivery"] = delivery
        status["results"] = results
        return self._publish_status(_finalize_status(status))

    @QtCore.pyqtSlot()
    def refresh_full(self) -> None:
        self.refresh(capture_render=True, audit_source=True)

    @QtCore.pyqtSlot(int)
    def _document_modified(self, _modified: int) -> None:
        if self._exporting:
            return
        try:
            self._refresh_document_state()
        except Exception as exc:
            self._audit_failure_status(exc)

    @QtCore.pyqtSlot(bool)
    def _dock_visibility_changed(self, visible: bool) -> None:
        if visible and not self._exporting:
            self._refresh_document_state()

    def _open_local_path(self, path: Path) -> bool:
        return bool(
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(path))
            )
        )

    def _open_result_target(
        self,
        key: str,
        *,
        reveal: bool = False,
    ) -> bool:
        results = (
            self.status_snapshot.get("results")
            if isinstance(self.status_snapshot.get("results"), dict)
            else {}
        )
        target = (
            results.get(key)
            if isinstance(results.get(key), dict)
            else {}
        )
        value = target.get("reveal_path") if reveal else target.get("path")
        if target.get("available") is not True or not isinstance(value, str):
            QtWidgets.QMessageBox.warning(
                self.window,
                "SciPlot result unavailable",
                "This result is not current and available yet.",
            )
            return False
        try:
            path = Path(value).expanduser().resolve()
            root_value = target.get("evidence_root")
            evidence_root = (
                Path(str(root_value)).expanduser().resolve()
                if isinstance(root_value, str) and root_value.strip()
                else None
            )
            within_root = bool(
                evidence_root is not None
                and _is_within(path, evidence_root)
            )
            exists = (
                path.is_dir()
                if reveal or key == "delivery"
                else path.is_file()
            )
            expected_sha256 = str(target.get("sha256") or "").strip()
            hash_current = bool(
                not expected_sha256
                or existing_file_sha256(path) == expected_sha256
            )
        except (OSError, RuntimeError, ValueError):
            exists = False
            within_root = False
            hash_current = False
            path = Path(value)
        if not (exists and within_root and hash_current):
            QtWidgets.QMessageBox.warning(
                self.window,
                "SciPlot result unavailable",
                "The result path is missing, changed, or outside its "
                f"validated root:\n{path}",
            )
            return False
        if self._open_local_path(path):
            return True
        QtWidgets.QMessageBox.warning(
            self.window,
            "SciPlot could not open the result",
            f"The operating system did not open:\n{path}",
        )
        return False

    @QtCore.pyqtSlot()
    def open_current_pdf(self) -> bool:
        return self._open_result_target("pdf")

    @QtCore.pyqtSlot()
    def show_current_delivery(self) -> bool:
        return self._open_result_target("delivery")

    @QtCore.pyqtSlot()
    def reveal_current_vsz(self) -> bool:
        return self._open_result_target("vsz", reveal=True)

    def _project_export(self) -> dict[str, Any]:
        assert self.project_dir is not None
        assert self.request_path is not None
        export_payload = export_studio_document(
            self.document_path,
            formats=["pdf", "tiff_300"],
        )
        exports = list(export_payload.get("exports") or [])
        export_document_sha256 = str(
            export_payload.get("document_sha256") or ""
        ).strip()
        run = publish_studio_export_run(
            project_dir=self.project_dir,
            request_path=self.request_path,
            document_path=self.document_path,
            exports=exports,
            export_document_sha256=export_document_sha256,
        )
        return {
            "kind": "sciplot_studio_menu_export",
            "version": 1,
            "scope": "project_delivery",
            "status": "passed" if run.get("ready_to_use") is True else "failed",
            "state": run.get("state"),
            "ready_to_use": run.get("ready_to_use") is True,
            "export_payload": json_safe(export_payload),
            "exports": json_safe(exports),
            "studio_run": json_safe(run),
        }

    def _standalone_export(self) -> dict[str, Any]:
        artifact_root = self.document_path.parent / "exports"
        export_payload = export_studio_document(
            self.document_path,
            formats=["pdf", "tiff_300"],
            output_dir=artifact_root / "figures",
        )
        exports = list(export_payload.get("exports") or [])
        export_document_sha256 = str(
            export_payload.get("document_sha256") or ""
        ).strip()
        receipt = publish_standalone_export_receipt(
            document_path=self.document_path,
            requested_formats=["pdf", "tiff_300"],
            exports=exports,
            artifact_root=artifact_root,
            export_document_sha256=export_document_sha256,
        )
        return {
            "kind": "sciplot_studio_menu_export",
            "version": 1,
            "scope": "standalone_exact_current_export",
            "status": receipt.get("status"),
            "state": receipt.get("state"),
            "ready_to_use": receipt.get("export_ready") is True,
            "export_payload": json_safe(export_payload),
            "exports": json_safe(exports),
            "standalone_export": json_safe(receipt),
        }

    def _assistant_export_blocker(self) -> str | None:
        assistant = getattr(
            self.window,
            "_sciplot_assistant_bridge",
            None,
        )
        if assistant is None:
            return None
        try:
            runner = getattr(assistant, "runner", None)
            if runner is not None and bool(getattr(runner, "active", False)):
                return (
                    "Wait for the active SciPlot AI request to finish or stop "
                    "it before exporting."
                )
            pending = getattr(assistant, "pending_batch", None)
            if pending is None:
                pending = getattr(assistant, "_pending_batch", None)
            if pending is not None:
                return (
                    "Accept or reject the pending SciPlot AI proposal before "
                    "exporting."
                )
        except Exception as exc:
            return (
                "SciPlot could not establish a safe AI transaction state: "
                f"{type(exc).__name__}: {exc}"
            )
        return None

    def _failed_export_payload(
        self,
        *,
        state: str,
        message: str,
        error_type: str = "RuntimeError",
        unaccepted_export: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "sciplot_studio_menu_export",
            "version": 1,
            "scope": (
                "project_delivery"
                if self.mode == "project"
                else "standalone_exact_current_export"
            ),
            "status": "failed",
            "state": state,
            "ready_to_use": False,
            "error": {
                "type": error_type,
                "message": message,
            },
        }
        if unaccepted_export is not None:
            payload["unaccepted_export"] = json_safe(unaccepted_export)
        return payload

    def _show_export_message(self, payload: dict[str, Any]) -> None:
        level, title, message = export_result_message(payload)
        if level == "information":
            QtWidgets.QMessageBox.information(self.window, title, message)
        else:
            QtWidgets.QMessageBox.warning(self.window, title, message)

    @QtCore.pyqtSlot()
    def export_current_document(
        self,
        *,
        show_dialog: bool = True,
    ) -> dict[str, Any]:
        blocker = self._assistant_export_blocker()
        if blocker is not None:
            payload = self._failed_export_payload(
                state="assistant_transaction_pending",
                message=blocker,
            )
            if show_dialog:
                self._show_export_message(payload)
        else:
            self._exporting = True
            self._publish_status(
                _finalize_status(
                    self.status_snapshot,
                    exporting=True,
                )
            )
            QtWidgets.QApplication.processEvents()
            try:
                pre_save_revision = int(self.document.changeset)
                pre_save_modified = bool(self.document.isModified())
                self.document.save(str(self.document_path))
                export_revision = int(self.document.changeset)
                if bool(self.document.isModified()):
                    raise RuntimeError(
                        "The Veusz document remained modified after save."
                    )
                export_document_sha256 = existing_file_sha256(
                    self.document_path
                )
                if not export_document_sha256:
                    raise RuntimeError(
                        "The saved Veusz document has no readable SHA-256."
                    )
                blocker = self._assistant_export_blocker()
                if blocker is not None:
                    raise RuntimeError(blocker)
                accepted_export = (
                    self._project_export()
                    if self.mode == "project"
                    else self._standalone_export()
                )
                post_revision = int(self.document.changeset)
                post_modified = bool(self.document.isModified())
                post_document_sha256 = existing_file_sha256(
                    self.document_path
                )
                post_blocker = self._assistant_export_blocker()
                changed_during_export = bool(
                    post_revision != export_revision
                    or post_modified
                    or post_document_sha256 != export_document_sha256
                    or post_blocker is not None
                )
                if changed_during_export:
                    details = (
                        "The Veusz document or AI transaction state changed "
                        "while SciPlot was exporting. The written artifacts "
                        "were not accepted as current GUI evidence."
                    )
                    payload = self._failed_export_payload(
                        state="document_changed_during_export",
                        message=details,
                        unaccepted_export=accepted_export,
                    )
                else:
                    payload = {
                        **accepted_export,
                        "export_guard": {
                            "pre_save_revision": pre_save_revision,
                            "pre_save_modified": pre_save_modified,
                            "export_revision": export_revision,
                            "post_export_revision": post_revision,
                            "post_export_modified": post_modified,
                            "document_sha256": export_document_sha256,
                        },
                    }
            except Exception as exc:
                payload = self._failed_export_payload(
                    state="export_exception",
                    message=str(exc),
                    error_type=type(exc).__name__,
                )
                if show_dialog:
                    QtWidgets.QMessageBox.critical(
                        self.window,
                        "SciPlot export failed",
                        str(exc),
                    )
            else:
                if show_dialog:
                    self._show_export_message(payload)
        self._exporting = False
        self.refresh(capture_render=False, audit_source=False)
        self.exportFinished.emit(payload)
        return payload


def attach_studio_project(
    window: Any,
    document_path: Path,
    *,
    project_dir: Path | None = None,
    request_path: Path | None = None,
) -> StudioProjectBridge:
    _validate_project_request_pair(project_dir, request_path)
    existing = getattr(window, "_sciplot_project_bridge", None)
    if isinstance(existing, StudioProjectBridge):
        return existing
    bridge = StudioProjectBridge(
        window,
        document_path,
        project_dir=project_dir,
        request_path=request_path,
    )
    window._sciplot_project_bridge = bridge
    return bridge


__all__ = [
    "StudioProjectBridge",
    "attach_studio_project",
    "build_studio_project_status",
    "export_result_message",
]
