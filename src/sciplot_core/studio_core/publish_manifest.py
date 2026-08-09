"""Build Studio result and manifest payloads from verified run evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan import (
    finalize_figure_plan_result,
    outcomes_for_artifact_map,
)
from sciplot_core.foundation.file_hashing import existing_file_sha256
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
    veusz_documents, veusz_document_hashes = _studio_snapshot_documents(inventory)
    document_map = _studio_snapshot_document_map(
        inventory,
        snapshot_documents=veusz_documents,
    )
    primary_document = document_map[str(inventory.document_path.resolve())]
    snapshot_exports = _snapshot_bound_exports(
        copied_exports,
        document_map=document_map,
    )
    result = {
        "kind": "sciplot_studio_export_result",
        "engine": "veusz",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "document": str(primary_document),
        "veusz_document": str(primary_document),
        "veusz_spec": str(_veusz_spec_path(primary_document)),
        "document_authority": inventory.document_state["authority"],
        "exported_document_hash": inventory.export_document_sha256,
        "manual_edit_detected": inventory.document_state["manual_edit_detected"],
        "export_formats": [
            str(item.get("format")) for item in copied_exports if item.get("format")
        ],
        "exports": snapshot_exports,
        "outputs": figures,
        "processed": sources.processed_source is not None,
        "processed_source": (
            str(sources.processed_source)
            if sources.processed_source is not None
            else None
        ),
        "data_snapshot_sources": [str(path) for path in sources.snapshot_sources],
        "analysis_metrics": sources.analysis_metrics,
        "template": inventory.presentation_identity.template,
        "presentation_identity": inventory.presentation_identity.to_payload(),
        "operation_mode": normal_mode_payload(route="studio"),
        "rule_readiness": inventory.rule_readiness.to_payload(),
        "pending_rule_review": inventory.pending_rule_review,
        "publication_rule_blocked": inventory.publication_rule_blocked,
        "autonomous_rule_ready": not inventory.publication_rule_blocked,
        "data_mapping_application": json_safe(inventory.data_mapping_application),
        "data_mapping_coverage": json_safe(request.get("data_mapping_coverage")),
        "scope": (
            "full_figure_set_project_delivery"
            if _is_full_figure_set_export_scope(inventory.figure_set_export_scope)
            else "project_delivery"
        ),
        "veusz_documents": [str(path) for path in veusz_documents],
        "veusz_document_hashes": veusz_document_hashes,
    }
    if inventory.figure_set_export_scope is not None:
        result["figure_set_export_scope"] = json_safe(inventory.figure_set_export_scope)
    if inventory.resolved_figure_plan is not None:
        artifacts_by_id = _studio_plan_artifacts(
            inventory=inventory,
            copied_exports=copied_exports,
        )
        result["figure_outcomes"] = [
            outcome.to_payload()
            for outcome in outcomes_for_artifact_map(
                inventory.resolved_figure_plan,
                artifacts_by_id,
            )
        ]
        finalize_figure_plan_result(inventory.resolved_figure_plan, result)
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
    veusz_documents, veusz_document_hashes = _studio_snapshot_documents(inventory)
    document_map = _studio_snapshot_document_map(
        inventory,
        snapshot_documents=veusz_documents,
    )
    primary_document = document_map[str(inventory.document_path.resolve())]
    manifest = {
        "kind": "sciplot_run",
        "created_at": utc_now_iso(),
        "request_path": str(inventory.request_path),
        "request": json_safe(request),
        "route": "studio",
        "template": inventory.presentation_identity.template,
        "presentation_identity": inventory.presentation_identity.to_payload(),
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
        "veusz_document": str(primary_document),
        "veusz_documents": [str(path) for path in veusz_documents],
        "veusz_document_hashes": veusz_document_hashes,
        "veusz_spec": str(_veusz_spec_path(primary_document)),
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
        "rule_readiness": inventory.rule_readiness.to_payload(),
        "pending_rule_review": inventory.pending_rule_review,
        "publication_rule_blocked": inventory.publication_rule_blocked,
        "autonomous_rule_ready": not inventory.publication_rule_blocked,
        "data_mapping_application": json_safe(inventory.data_mapping_application),
        "data_mapping_coverage": json_safe(request.get("data_mapping_coverage")),
        "scope": result["scope"],
        "studio": _studio_manifest_block(inventory),
    }
    if inventory.figure_set_export_scope is not None:
        scope = json_safe(inventory.figure_set_export_scope)
        manifest["figure_set_export_scope"] = scope
        manifest["studio"]["figure_set_export_scope"] = scope
    if isinstance(result.get("resolved_figure_plan"), dict):
        manifest["resolved_figure_plan"] = json_safe(result["resolved_figure_plan"])
    return manifest


def _studio_plan_artifacts(
    *,
    inventory: StudioExportInventory,
    copied_exports: list[dict[str, Any]],
) -> dict[str, list[str]]:
    plan = inventory.resolved_figure_plan
    if plan is None:
        return {}
    snapshot_documents, _snapshot_hashes = _studio_snapshot_documents(inventory)
    snapshots_by_source = {
        str(source.expanduser().resolve()): snapshot
        for source, snapshot in zip(
            inventory.veusz_documents,
            snapshot_documents,
            strict=True,
        )
    }
    artifacts: dict[str, list[str]] = {task.figure_id: [] for task in plan.tasks}
    single_id = plan.tasks[0].figure_id if len(plan.tasks) == 1 else None
    for item in copied_exports:
        figure_id = str(item.get("figure_id") or "").strip()
        if single_id is not None and figure_id in {"", "primary"}:
            figure_id = single_id
        if figure_id not in artifacts:
            continue
        for key in ("path", "document"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                artifact_path = Path(value)
                if key == "document":
                    snapshot = snapshots_by_source.get(
                        str(artifact_path.expanduser().resolve())
                    )
                    if snapshot is None:
                        raise RuntimeError(
                            "Studio export references a VSZ outside the verified "
                            f"run snapshot: {artifact_path}"
                        )
                    artifact_path = snapshot
                artifacts[figure_id].append(str(artifact_path))
                if key == "document":
                    spec = _veusz_spec_path(artifact_path)
                    if spec.is_file():
                        artifacts[figure_id].append(str(spec))
    return {
        figure_id: list(dict.fromkeys(paths)) for figure_id, paths in artifacts.items()
    }


def _studio_manifest_block(inventory: StudioExportInventory) -> dict[str, Any]:
    veusz_documents, veusz_document_hashes = _studio_snapshot_documents(inventory)
    document_map = _studio_snapshot_document_map(
        inventory,
        snapshot_documents=veusz_documents,
    )
    primary_document = document_map[str(inventory.document_path.resolve())]
    block = {
        "engine": "veusz",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "document": str(primary_document),
        "veusz_documents": [str(path) for path in veusz_documents],
        "veusz_document_hashes": veusz_document_hashes,
        "spec": str(_veusz_spec_path(primary_document)),
        "manual_edit_hash": inventory.export_document_sha256,
        "document_authority": inventory.document_state["authority"],
        "exported_document_hash": inventory.export_document_sha256,
        "manual_edit_detected": inventory.document_state["manual_edit_detected"],
        "document_state": inventory.document_state,
        "upstream": upstream_status()["veusz"],
        "operation_mode": normal_mode_payload(route="studio"),
        "presentation_identity": inventory.presentation_identity.to_payload(),
    }
    binding = inventory.request.get("studio_rule_contract_binding")
    if isinstance(binding, dict):
        block["rule_contract_binding"] = json_safe(binding)
    return block


def _studio_snapshot_documents(
    inventory: StudioExportInventory,
) -> tuple[list[Path], dict[str, str]]:
    documents: list[Path] = []
    hashes: dict[str, str] = {}
    studio_root = (inventory.project_dir / "studio").resolve()
    for document in inventory.veusz_documents:
        resolved = document.expanduser().resolve()
        expected_hash = inventory.veusz_document_hashes.get(str(resolved))
        if not expected_hash:
            raise RuntimeError(f"Studio snapshot has no expected VSZ hash: {resolved}")
        try:
            relative = resolved.relative_to(studio_root)
        except ValueError as exc:
            raise RuntimeError(
                f"Studio VSZ is outside the canonical project studio tree: {resolved}"
            ) from exc
        snapshot = inventory.output_dir / "studio" / relative
        actual_hash = existing_file_sha256(snapshot)
        if actual_hash != expected_hash:
            raise RuntimeError(
                "Run-local Studio snapshot is missing or changed before manifest "
                f"binding: {snapshot}"
            )
        documents.append(snapshot)
        hashes[str(snapshot.resolve())] = expected_hash
    return documents, hashes


def _studio_snapshot_document_map(
    inventory: StudioExportInventory,
    *,
    snapshot_documents: list[Path] | None = None,
) -> dict[str, Path]:
    snapshots = (
        snapshot_documents
        if snapshot_documents is not None
        else _studio_snapshot_documents(inventory)[0]
    )
    return {
        str(source.expanduser().resolve()): snapshot
        for source, snapshot in zip(
            inventory.veusz_documents,
            snapshots,
            strict=True,
        )
    }


def _snapshot_bound_exports(
    copied_exports: list[dict[str, Any]],
    *,
    document_map: dict[str, Path],
) -> list[dict[str, Any]]:
    bound: list[dict[str, Any]] = []
    for item in copied_exports:
        current = dict(item)
        document_value = current.get("document")
        if isinstance(document_value, str) and document_value.strip():
            document = document_map.get(
                str(Path(document_value).expanduser().resolve())
            )
            if document is None:
                raise RuntimeError(
                    "Studio export references a VSZ outside the verified run "
                    f"snapshot: {document_value}"
                )
            current["document"] = str(document)
        bound.append(current)
    return bound
