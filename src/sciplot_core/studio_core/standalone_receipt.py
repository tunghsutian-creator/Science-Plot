"""Publish the receipt for an export outside a managed Studio project."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4
from sciplot_core.foundation.file_hashing import (
    existing_file_sha256,
)
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.qa import run_qa

from sciplot_core.studio_core.runtime import (
    _normalize_export_format,
)

from sciplot_core.studio_core.json_files import (
    _write_json_atomic,
)

from sciplot_core.studio_core.export_verification import (
    _verify_exact_current_export_binding,
    _verify_qa_artifact_hashes,
)

from sciplot_core.studio_core.registry_state import (
    _veusz_spec_reference,
)


def publish_standalone_export_receipt(
    *,
    document_path: Path,
    requested_formats: list[str],
    exports: list[dict[str, Any]],
    artifact_root: Path,
    export_document_sha256: str,
) -> dict[str, Any]:
    resolved_root = artifact_root.expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    _verify_exact_current_export_binding(
        document_path=document_path,
        export_document_sha256=export_document_sha256,
        exports=exports,
    )
    normalized_formats = list(
        dict.fromkeys(
            _normalize_export_format(item)
            for item in requested_formats
            if str(item).strip()
        )
    )
    if not normalized_formats:
        raise ValueError("A standalone export receipt requires at least one format.")
    successful_formats = {
        _normalize_export_format(str(item.get("format") or ""))
        for item in exports
        if isinstance(item, dict)
        and str(item.get("format") or "").strip()
        and item.get("exists") is True
        and int(item.get("size_bytes") or 0) > 0
    }
    requested_exports_complete = set(normalized_formats) <= successful_formats
    qa_covered_formats = (
        {item for item in normalized_formats if item in {"pdf", "tiff_300"}}
        if "pdf" in normalized_formats
        else set()
    )
    qa_uncovered_formats = sorted(set(normalized_formats) - qa_covered_formats)
    qa_required = bool(qa_covered_formats)
    if qa_required and requested_exports_complete:
        qa_input_dir = resolved_root / "qa_inputs" / uuid4().hex
        qa_input_dir.mkdir(parents=True, exist_ok=False)
        try:
            for item in exports:
                if (
                    not isinstance(item, dict)
                    or str(item.get("format") or "") not in qa_covered_formats
                ):
                    continue
                source = Path(str(item["path"])).expanduser().resolve()
                destination = qa_input_dir / source.name
                shutil.copy2(source, destination)
                if existing_file_sha256(destination) != item.get("sha256"):
                    raise RuntimeError(
                        "Standalone QA input hash does not match its export."
                    )
            qa = run_qa(qa_input_dir)
            _verify_qa_artifact_hashes(
                qa,
                exports=exports,
                covered_formats=qa_covered_formats,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            qa = {
                "kind": "sciplot_artifact_qa",
                "status": "failed",
                "reason": str(exc),
            }
    elif qa_required:
        qa = {
            "kind": "sciplot_artifact_qa",
            "status": "not_run",
            "reason": "Requested standalone exports were incomplete.",
        }
    else:
        qa = {
            "kind": "sciplot_artifact_qa",
            "status": "not_required",
            "reason": (
                "The requested format set has no PDF anchor for SciPlot's "
                "PDF/TIFF artifact-QA profile; every file's existence and "
                "hash were still verified."
            ),
        }
    binding_error: str | None = None
    try:
        _verify_exact_current_export_binding(
            document_path=document_path,
            export_document_sha256=export_document_sha256,
            exports=exports,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        binding_error = str(exc)
    qa_passed = qa.get("status") in {"passed", "not_required"}
    export_ready = bool(
        requested_exports_complete and qa_passed and binding_error is None
    )
    spec_reference = _veusz_spec_reference(document_path)
    receipt_path = resolved_root / "standalone_export_receipt.json"
    qa_path = resolved_root / "qa_report.json"
    _write_json_atomic(qa_path, qa)
    if binding_error is not None:
        failure_stage = "exact_current_binding"
        failure_reason = binding_error
    elif not requested_exports_complete:
        failure_stage = "export"
        failure_reason = "One or more requested export files were missing or empty."
    elif not qa_passed:
        failure_stage = "artifact_qa"
        failure_reason = str(
            qa.get("reason") or "The standalone PDF/TIFF artifact QA did not pass."
        )
    else:
        failure_stage = None
        failure_reason = None
    receipt = {
        "kind": "sciplot_standalone_vsz_export",
        "version": 1,
        "status": "passed" if export_ready else "failed",
        "state": (
            "exported_exact_current" if export_ready else "needs_artifact_review"
        ),
        "scope": "standalone_exact_current_export",
        "document": str(document_path),
        "document_sha256": export_document_sha256,
        "document_authority": "veusz_document",
        "spec_reference": spec_reference,
        "requested_formats": normalized_formats,
        "exports": json_safe(exports),
        "requested_exports_complete": requested_exports_complete,
        "exact_current_binding_current": binding_error is None,
        "artifact_qa": json_safe(qa),
        "artifact_qa_path": str(qa_path),
        "qa_covered_formats": sorted(qa_covered_formats),
        "qa_uncovered_formats": qa_uncovered_formats,
        "export_ready": export_ready,
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "project_delivery_complete": False,
        "provenance_complete": False,
        "journal_compliance_established": False,
        "receipt_path": str(receipt_path),
        "limitations": [
            "This receipt binds every requested export hash to the exact-current "
            "VSZ; artifact QA applies only to qa_covered_formats.",
            "This standalone receipt does not attest a SciPlot request, raw-data "
            "archive, transform ledger, or portable project delivery.",
            "An optional SciPlot spec sidecar is not required to reopen or export the exact current VSZ.",
        ],
    }
    _write_json_atomic(receipt_path, receipt)
    return receipt
