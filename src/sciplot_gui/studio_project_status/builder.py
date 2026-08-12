"""Build the complete pure Studio project status payload."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.scientific_review import (
    scientific_transform_review_from_ledger,
)

from sciplot_gui.studio_project_status.project_runs import (
    _read_json,
    _request_path_value,
    _validate_project_request_pair,
    _project_manifest_payload,
    _latest_project_run,
)

from sciplot_gui.studio_project_status.source_status import (
    _source_status,
)

from sciplot_gui.studio_project_status.mapping_status import (
    _mapping_status,
)

from sciplot_gui.studio_project_status.qa_status import (
    _qa_status,
)

from sciplot_gui.studio_project_status.workflow_status import (
    _result_targets,
    _finalize_status,
)

from sciplot_gui.studio_project_status.live_document import (
    _live_document_payload,
)

from sciplot_gui.studio_project_status.provenance_status import (
    _provenance_status,
)

from sciplot_gui.studio_project_status.figure_set_scope import (
    _resolve_figure_set_export_scope,
)


def build_studio_project_status(
    *,
    document_path: Path,
    document: Any,
    project_dir: Path | None,
    request_path: Path | None,
    render_sha256: str | None = None,
    audit_source: bool = False,
    _figure_set_scope_resolver: Any = None,
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
            resolved_document.parent / "exports" / "standalone_export_receipt.json"
        )
        try:
            receipt = _read_json(receipt_path) if receipt_path.is_file() else {}
        except (OSError, ValueError, json.JSONDecodeError):
            receipt = {}
        qa = _qa_status(
            evidence=receipt,
            evidence_path=receipt_path if receipt else None,
            saved_sha256=(str(saved_sha256) if isinstance(saved_sha256, str) else None),
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
            "scientific_transform_review": None,
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
    canonical_primary = (resolved_project / "studio" / "document.vsz").resolve()
    if resolved_document != canonical_primary:
        receipt_path = (
            resolved_document.parent
            / "exports"
            / resolved_document.stem
            / "standalone_export_receipt.json"
        )
        try:
            receipt = _read_json(receipt_path) if receipt_path.is_file() else {}
        except (OSError, ValueError, json.JSONDecodeError):
            receipt = {}
        qa = _qa_status(
            evidence=receipt,
            evidence_path=receipt_path if receipt else None,
            saved_sha256=(str(saved_sha256) if isinstance(saved_sha256, str) else None),
            modified=modified,
            standalone=True,
        )
        status = {
            "kind": "sciplot_studio_project_status",
            "version": 1,
            "mode": "project",
            "document_scope": "project_secondary_standalone_receipt",
            "project": {
                "name": (project_manifest.get("project_name") or resolved_project.name),
                "path": str(resolved_project),
                "request": str(resolved_request),
                "request_status": "invalid" if request_error else "loaded",
                "request_error": request_error,
                "request_snapshot_current": False,
                "evidence_run": None,
                "rule_id": request.get("rule_id"),
                "template": request.get("template"),
            },
            "document": live_document,
            "source": {
                "status": "not_established_for_secondary_receipt",
                "path": None,
                "exists": False,
                "audit_status": "not_available",
                "reason": (
                    "This secondary figure uses a standalone exact-current "
                    "receipt; it does not extend the primary project receipt's "
                    "raw-source or transform-lineage claim."
                ),
            },
            "mapping": {
                "status": "unavailable_for_secondary_receipt",
                "coverage_status": "unavailable",
            },
            "provenance": {
                "status": "secondary_standalone_receipt_only",
                "complete": False,
                "full_project_evidence_current": False,
                "primary_figure_evidence_current": False,
                "project_delivery_complete": False,
                "project_delivery_current": False,
                "standalone_receipt_current": (qa.get("artifact_qa_current") is True),
            },
            "qa": qa,
            "scientific_transform_review": None,
            "results": _result_targets(
                live_document=live_document,
                qa=qa,
                evidence_path=receipt_path if receipt else None,
            ),
        }
        return _finalize_status(status)
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
        saved_sha256=(str(saved_sha256) if isinstance(saved_sha256, str) else None),
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
                latest_path.parent if latest_path is not None else resolved_project
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
    figure_set_scope_resolver = (
        _figure_set_scope_resolver or _resolve_figure_set_export_scope
    )
    figure_set_export_scope, figure_set_scope_status = figure_set_scope_resolver(
        project_dir=resolved_project,
        request=request,
        latest_run=latest_run,
    )
    provenance = _provenance_status(
        latest_path=latest_path,
        latest_run=latest_run,
        transform_status=transform_status,
        raw_archive_path=raw_archive_path,
        package=package,
        delivery=delivery,
        mapping=mapping,
        qa=qa,
        source=source,
        figure_set_export_scope=figure_set_export_scope,
        figure_set_scope_status=figure_set_scope_status,
    )
    status = {
        "kind": "sciplot_studio_project_status",
        "version": 1,
        "mode": "project",
        "project": {
            "name": (project_manifest.get("project_name") or resolved_project.name),
            "path": str(resolved_project),
            "request": str(resolved_request),
            "request_status": "invalid" if request_error else "loaded",
            "request_error": request_error,
            "request_snapshot_current": latest_path is not None,
            "evidence_run": (str(latest_path) if latest_path is not None else None),
            "rule_id": request.get("rule_id"),
            "template": request.get("template"),
        },
        "document": live_document,
        "source": source,
        "mapping": mapping,
        "provenance": provenance,
        "qa": qa,
        "scientific_transform_review": scientific_transform_review_from_ledger(
            request.get("transform_ledger")
        ),
        "results": _result_targets(
            live_document=live_document,
            qa=qa,
            evidence_path=latest_path,
            delivery=delivery,
            delivery_current=bool(
                provenance.get("project_delivery_current") is True
                and provenance.get("delivery_scope_known") is True
            ),
        ),
    }
    return _finalize_status(status)
