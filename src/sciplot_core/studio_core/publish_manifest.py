"""Build Studio result and manifest payloads from verified run evidence."""

from __future__ import annotations

from typing import Any

from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.source_coverage import verify_rendered_mapping_source_coverage
from sciplot_core.studio_figure_set_contract import (
    is_full_figure_set_export_scope as _is_full_figure_set_export_scope,
)

from sciplot_core.studio_core.publish_evidence import StudioPublicationEvidence
from sciplot_core.studio_core.publish_inventory import StudioExportInventory
from sciplot_core.studio_core.publish_sources import StudioRunSources
from sciplot_core.studio_core.registry_state import _veusz_spec_path
from sciplot_core.studio_core.runtime import upstream_status


def build_studio_export_result(
    *,
    inventory: StudioExportInventory,
    sources: StudioRunSources,
    copied_exports: list[dict[str, Any]],
    figures: list[str],
) -> dict[str, Any]:
    """Describe exact-current exported artifacts and their source coverage."""

    request = inventory.request
    result = {
        "kind": "sciplot_studio_export_result",
        "engine": "veusz",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "document": str(inventory.document_path),
        "veusz_document": str(inventory.document_path),
        "veusz_spec": str(_veusz_spec_path(inventory.document_path)),
        "document_authority": inventory.document_state["authority"],
        "exported_document_hash": inventory.export_document_sha256,
        "manual_edit_detected": inventory.document_state["manual_edit_detected"],
        "export_formats": [
            str(item.get("format")) for item in copied_exports if item.get("format")
        ],
        "exports": copied_exports,
        "outputs": figures,
        "processed": sources.processed_source is not None,
        "processed_source": (
            str(sources.processed_source)
            if sources.processed_source is not None
            else None
        ),
        "data_snapshot_sources": [str(path) for path in sources.snapshot_sources],
        "analysis_metrics": sources.analysis_metrics,
        "template": request.get("template")
        or request.get("recipe")
        or "veusz_document",
        "operation_mode": normal_mode_payload(route="studio"),
        "pending_rule_review": inventory.pending_rule_review,
        "autonomous_rule_ready": not inventory.pending_rule_review,
        "data_mapping_application": json_safe(inventory.data_mapping_application),
        "data_mapping_coverage": json_safe(request.get("data_mapping_coverage")),
        "scope": (
            "full_figure_set_project_delivery"
            if _is_full_figure_set_export_scope(inventory.figure_set_export_scope)
            else "project_delivery"
        ),
        "veusz_documents": [str(path) for path in inventory.veusz_documents],
        "veusz_document_hashes": inventory.veusz_document_hashes,
    }
    if inventory.figure_set_export_scope is not None:
        result["figure_set_export_scope"] = json_safe(inventory.figure_set_export_scope)
    if len(sources.snapshot_sources) == 1:
        result["data_snapshot_source"] = str(sources.snapshot_sources[0])
    if inventory.data_mapping_application is not None:
        result["rendered_source_coverage"] = verify_rendered_mapping_source_coverage(
            result,
            mapping_application=inventory.data_mapping_application,
            request=request,
        )
    return result


def build_studio_run_manifest(
    *,
    inventory: StudioExportInventory,
    sources: StudioRunSources,
    evidence: StudioPublicationEvidence,
    result: dict[str, Any],
    figures: list[str],
) -> dict[str, Any]:
    """Assemble the durable run manifest before package finalization."""

    request = inventory.request
    manifest = {
        "kind": "sciplot_run",
        "created_at": utc_now_iso(),
        "request_path": str(inventory.request_path),
        "request": json_safe(request),
        "route": "studio",
        "semantic": evidence.semantic,
        "final_recipe": None,
        "input": str(sources.input_path) if sources.input_path is not None else "",
        "raw_archive": json_safe(sources.raw_archive),
        "output": str(inventory.output_dir),
        "figures": figures,
        "result": json_safe(result),
        "study_model": json_safe(evidence.study_model),
        "publication_intent": json_safe(evidence.publication_intent),
        "transform_ledger": json_safe(evidence.transform_ledger),
        "journal_profile": json_safe(evidence.publication_profile),
        "publication_qa": json_safe(evidence.publication_qa),
        "publication_artifacts": json_safe(evidence.publication_artifacts),
        "qa": evidence.qa,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "veusz_document": str(inventory.document_path),
        "veusz_documents": [str(path) for path in inventory.veusz_documents],
        "veusz_document_hashes": inventory.veusz_document_hashes,
        "veusz_spec": str(_veusz_spec_path(inventory.document_path)),
        "manual_edit_hash": inventory.export_document_sha256,
        "document_authority": inventory.document_state["authority"],
        "exported_document_hash": inventory.export_document_sha256,
        "manual_edit_detected": inventory.document_state["manual_edit_detected"],
        "document_state": inventory.document_state,
        "layout_policy": {
            "kind": "sciplot_layout_policy",
            "policy_id": "veusz_native_document",
            "review_mode": "native_veusz_mainwindow",
        },
        "layout_quality": evidence.layout_quality,
        "operation_mode": normal_mode_payload(route="studio"),
        "pending_rule_review": inventory.pending_rule_review,
        "autonomous_rule_ready": not inventory.pending_rule_review,
        "data_mapping_application": json_safe(inventory.data_mapping_application),
        "data_mapping_coverage": json_safe(request.get("data_mapping_coverage")),
        "scope": result["scope"],
        "studio": _studio_manifest_block(inventory),
    }
    if inventory.figure_set_export_scope is not None:
        scope = json_safe(inventory.figure_set_export_scope)
        manifest["figure_set_export_scope"] = scope
        manifest["studio"]["figure_set_export_scope"] = scope
    return manifest


def _studio_manifest_block(inventory: StudioExportInventory) -> dict[str, Any]:
    return {
        "engine": "veusz",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "document": str(inventory.document_path),
        "veusz_documents": [str(path) for path in inventory.veusz_documents],
        "veusz_document_hashes": inventory.veusz_document_hashes,
        "spec": str(_veusz_spec_path(inventory.document_path)),
        "manual_edit_hash": inventory.export_document_sha256,
        "document_authority": inventory.document_state["authority"],
        "exported_document_hash": inventory.export_document_sha256,
        "manual_edit_detected": inventory.document_state["manual_edit_detected"],
        "document_state": inventory.document_state,
        "upstream": upstream_status()["veusz"],
        "operation_mode": normal_mode_payload(route="studio"),
    }
