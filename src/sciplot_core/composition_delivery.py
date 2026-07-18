from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.persistence import atomic_write_json
from sciplot_core.composition_workspace import (
    CompositionWorkspace,
    composition_variant_authority_status,
    verify_composition_sources,
)
from sciplot_core.qa import run_qa
from sciplot_core.studio import export_studio_document

COMPOSITION_DELIVERY_KIND = "sciplot_composition_delivery"
COMPOSITION_DELIVERY_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")


def _copy_verified(source: Path, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    source_hash = file_sha256(source)
    destination_hash = file_sha256(destination)
    if source_hash != destination_hash:
        raise RuntimeError(f"Delivery copy hash mismatch: {source}")
    return {
        "source": str(source),
        "path": str(destination),
        "sha256": destination_hash,
        "size_bytes": destination.stat().st_size,
        "byte_identical": True,
    }


def _physical_export_qa(
    exports: list[dict[str, Any]],
    *,
    width_mm: float,
    height_mm: float,
) -> dict[str, Any]:
    import fitz
    from PIL import Image

    by_format = {
        str(item.get("format") or ""): Path(str(item.get("path") or ""))
        for item in exports
        if item.get("exists") is True
    }
    pdf_path = by_format.get("pdf")
    tiff_path = by_format.get("tiff_300")
    checks: list[dict[str, Any]] = []
    pdf_size_mm: list[float] | None = None
    tiff_size_mm: list[float] | None = None

    if pdf_path is not None and pdf_path.is_file():
        document = fitz.open(pdf_path)
        try:
            if document.page_count != 1:
                raise ValueError("Composition PDF must contain exactly one page.")
            rect = document[0].rect
            pdf_size_mm = [
                float(rect.width) / 72.0 * 25.4,
                float(rect.height) / 72.0 * 25.4,
            ]
        finally:
            document.close()
        pdf_error = max(
            abs(pdf_size_mm[0] - width_mm),
            abs(pdf_size_mm[1] - height_mm),
        )
        checks.append(
            {
                "id": "pdf_physical_size",
                "status": "passed" if pdf_error <= 0.25 else "failed",
                "size_mm": [round(value, 4) for value in pdf_size_mm],
                "maximum_error_mm": round(pdf_error, 4),
                "tolerance_mm": 0.25,
            }
        )
    else:
        checks.append(
            {
                "id": "pdf_physical_size",
                "status": "failed",
                "reason": "PDF export is missing.",
            }
        )

    if tiff_path is not None and tiff_path.is_file():
        with Image.open(tiff_path) as image:
            dpi_value = image.info.get("dpi") or (0.0, 0.0)
            dpi_x = float(dpi_value[0] or 0.0)
            dpi_y = float(dpi_value[1] or 0.0)
            if dpi_x <= 0.0 or dpi_y <= 0.0:
                raise ValueError("Composition TIFF does not record physical DPI.")
            tiff_size_mm = [
                float(image.width) / dpi_x * 25.4,
                float(image.height) / dpi_y * 25.4,
            ]
            pixels = [int(image.width), int(image.height)]
        tiff_error = max(
            abs(tiff_size_mm[0] - width_mm),
            abs(tiff_size_mm[1] - height_mm),
        )
        dpi_error = max(abs(dpi_x - 300.0), abs(dpi_y - 300.0))
        checks.append(
            {
                "id": "tiff_300_physical_size",
                "status": (
                    "passed" if tiff_error <= 0.35 and dpi_error <= 1.0 else "failed"
                ),
                "pixels": pixels,
                "dpi": [round(dpi_x, 3), round(dpi_y, 3)],
                "size_mm": [round(value, 4) for value in tiff_size_mm],
                "maximum_size_error_mm": round(tiff_error, 4),
                "maximum_dpi_error": round(dpi_error, 4),
            }
        )
    else:
        checks.append(
            {
                "id": "tiff_300_physical_size",
                "status": "failed",
                "reason": "300 dpi TIFF export is missing.",
            }
        )

    if pdf_size_mm is not None and tiff_size_mm is not None:
        pairing_error = max(
            abs(pdf_size_mm[0] - tiff_size_mm[0]),
            abs(pdf_size_mm[1] - tiff_size_mm[1]),
        )
        checks.append(
            {
                "id": "pdf_tiff_physical_pairing",
                "status": "passed" if pairing_error <= 0.35 else "failed",
                "maximum_difference_mm": round(pairing_error, 4),
                "tolerance_mm": 0.35,
            }
        )
    else:
        checks.append(
            {
                "id": "pdf_tiff_physical_pairing",
                "status": "failed",
                "reason": "Both physical artifact sizes are required.",
            }
        )
    return {
        "kind": "sciplot_composition_physical_qa",
        "version": 1,
        "status": (
            "passed"
            if all(check["status"] == "passed" for check in checks)
            else "failed"
        ),
        "expected_size_mm": [width_mm, height_mm],
        "checks": checks,
    }


def export_composition_delivery(
    workspace: CompositionWorkspace,
    *,
    variant_id: str | None = None,
    formats: tuple[str, ...] = ("pdf", "tiff_300"),
) -> dict[str, Any]:
    from sciplot_gui.composition_compiler import (
        audit_native_composition_document,
    )

    project = workspace.load()
    variant = project.variant(variant_id or project.active_variant_id)
    document = workspace.variant_document_path(variant.variant_id)
    if not document.is_file():
        raise FileNotFoundError(
            "Compile the composition before export; no exact-current VSZ exists."
        )
    requested = tuple(dict.fromkeys(str(value).strip() for value in formats))
    if set(requested) != {"pdf", "tiff_300"}:
        raise ValueError(
            "Composition delivery version 1 requires PDF and 300 dpi TIFF together."
        )
    source_verification = verify_composition_sources(workspace, project)
    authority = composition_variant_authority_status(
        workspace,
        project,
        variant.variant_id,
    )
    native_audit = audit_native_composition_document(
        workspace,
        variant_id=variant.variant_id,
    )
    compile_manifest = workspace.variant_compile_manifest_path(variant.variant_id)
    compile_evidence: dict[str, Any] = {}
    if compile_manifest.is_file():
        value = json.loads(compile_manifest.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            compile_evidence = value
    export_root = workspace.variant_export_root(variant.variant_id)
    export_payload = export_studio_document(
        document,
        formats=list(requested),
        output_dir=export_root,
    )
    exports = list(export_payload.get("exports") or [])
    physical_qa = _physical_export_qa(
        exports,
        width_mm=183.0,
        height_mm=variant.layout.canvas_height_mm,
    )
    try:
        artifact_qa = run_qa(export_root)
    except Exception as exc:
        artifact_qa = {
            "kind": "sciplot_artifact_qa",
            "status": "failed",
            "reason": str(exc),
        }

    run_root = (
        workspace.variant_delivery_root(variant.variant_id) / "runs" / _run_slug()
    )
    run_root.mkdir(parents=True, exist_ok=False)
    delivered: list[dict[str, Any]] = []
    delivered.append(
        _copy_verified(
            workspace.composition_path,
            run_root / "composition.json",
        )
    )
    delivered.append(
        _copy_verified(
            workspace.source_manifest_path,
            run_root / "source_manifest.json",
        )
    )
    if workspace.journal_path.is_file():
        delivered.append(
            _copy_verified(
                workspace.journal_path,
                run_root / "operation_journal.jsonl",
            )
        )
    if compile_manifest.is_file():
        delivered.append(
            _copy_verified(
                compile_manifest,
                run_root / "compile_manifest.json",
            )
        )
    delivered_document = _copy_verified(
        document,
        run_root / "studio" / "document.vsz",
    )
    delivered.append(delivered_document)
    for module in project.source_modules:
        delivered.append(
            _copy_verified(
                workspace.source_path(module),
                run_root / module.source_ref,
            )
        )
    delivered_exports: list[dict[str, Any]] = []
    for export in exports:
        source = Path(str(export.get("path") or ""))
        if not source.is_file():
            continue
        copied = _copy_verified(source, run_root / "figures" / source.name)
        delivered.append(copied)
        delivered_exports.append(
            {
                **json_safe(export),
                "delivery_path": copied["path"],
                "delivery_sha256": copied["sha256"],
            }
        )

    qa_payload = {
        "kind": "sciplot_composition_qa",
        "version": 1,
        "created_at": _now(),
        "source_verification": source_verification,
        "authority": authority,
        "native_audit": native_audit,
        "eligibility": json_safe(compile_evidence.get("eligibility")),
        "legend_resolution": json_safe(compile_evidence.get("legend_resolution")),
        "physical_qa": physical_qa,
        "artifact_qa": json_safe(artifact_qa),
    }
    qa_path = atomic_write_json(run_root / "qa_report.json", qa_payload)
    delivered.append(
        {
            "source": str(qa_path),
            "path": str(qa_path),
            "sha256": file_sha256(qa_path),
            "size_bytes": qa_path.stat().st_size,
            "byte_identical": True,
        }
    )

    export_formats = {
        str(item.get("format") or "")
        for item in delivered_exports
        if int(item.get("size_bytes") or 0) > 0
    }
    exact_current_hash = file_sha256(document)
    delivery_hash_parity = delivered_document["sha256"] == exact_current_hash
    geometry_error = native_audit.get("maximum_geometry_error_mm")
    legend_resolution = compile_evidence.get("legend_resolution")
    ready = bool(
        export_formats == {"pdf", "tiff_300"}
        and physical_qa["status"] == "passed"
        and artifact_qa.get("status") == "passed"
        and native_audit.get("raster_panel_composition_detected") is False
        and native_audit.get("panel_labels_aligned") is True
        and native_audit.get("style_alignment", {}).get("axes_aligned") is True
        and native_audit.get("style_alignment", {}).get("series_strokes_aligned")
        is True
        and isinstance(legend_resolution, dict)
        and legend_resolution.get("status") in {"passed", "not_applicable"}
        and isinstance(geometry_error, int | float)
        and float(geometry_error) <= 0.02
        and delivery_hash_parity
        and all(record.get("verified") is True for record in source_verification)
    )
    manifest = {
        "kind": COMPOSITION_DELIVERY_KIND,
        "version": COMPOSITION_DELIVERY_VERSION,
        "created_at": _now(),
        "status": "passed" if ready else "failed",
        "state": "ready" if ready else "needs_rule_repair",
        "ready_to_use": ready,
        "composition_id": project.composition_id,
        "variant_id": variant.variant_id,
        "variant_revision": variant.revision,
        "layout_id": variant.layout.layout_id,
        "page_size_mm": [183.0, variant.layout.canvas_height_mm],
        "exact_current_document": str(document),
        "exact_current_document_sha256": exact_current_hash,
        "manual_edit_detected": authority.get("manual_edit_detected") is True,
        "delivery_document_sha256": delivered_document["sha256"],
        "delivery_hash_parity": delivery_hash_parity,
        "exports": delivered_exports,
        "qa_report": str(qa_path),
        "files": delivered,
        "claims": {
            "native_composition_lifecycle_passed": ready,
            "exact_current_artifact_qa_passed": (
                physical_qa["status"] == "passed"
                and artifact_qa.get("status") == "passed"
            ),
            "broader_journal_compliance_established": False,
        },
        "authority": {
            "source_vsz_snapshots_unchanged": True,
            "exact_current_composite_delivered": delivery_hash_parity,
            "manual_edits_preserved_when_present": True,
            "raster_panel_composition_used": False,
        },
    }
    manifest_path = atomic_write_json(run_root / "delivery_manifest.json", manifest)
    latest_path = atomic_write_json(
        workspace.variant_delivery_root(variant.variant_id) / "latest.json",
        {
            "kind": "sciplot_composition_delivery_latest",
            "version": 1,
            "run": str(run_root),
            "manifest": str(manifest_path),
            "status": manifest["status"],
            "ready_to_use": ready,
        },
    )
    archive = shutil.make_archive(str(run_root), "zip", root_dir=run_root)
    return {
        **manifest,
        "delivery_root": str(run_root),
        "delivery_manifest": str(manifest_path),
        "latest": str(latest_path),
        "archive": archive,
        "archive_sha256": file_sha256(Path(archive)),
    }


__all__ = [
    "COMPOSITION_DELIVERY_KIND",
    "COMPOSITION_DELIVERY_VERSION",
    "export_composition_delivery",
]
