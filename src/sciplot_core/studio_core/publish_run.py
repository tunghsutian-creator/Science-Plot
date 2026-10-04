"""Coordinate one complete Studio export publication run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.source_coverage.managed_documents import (
    verify_managed_document_sources,
)
from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
from sciplot_core.studio_core.registry_state import _veusz_spec_path

from sciplot_core.studio_core.publish_evidence import (
    build_studio_publication_evidence,
)
from sciplot_core.studio_core.publish_exports import copy_studio_run_exports
from sciplot_core.studio_core.publish_finalize import (
    _snapshot_studio_directory,
    finalize_studio_run,
)
from sciplot_core.studio_core.publish_inventory import (
    prepare_studio_export_inventory,
)
from sciplot_core.studio_core.publish_manifest import (
    _studio_snapshot_document_map,
    _studio_snapshot_documents,
    build_studio_export_result,
    build_studio_run_manifest,
)
from sciplot_core.studio_core.publish_sources import (
    prepare_studio_run_sources,
    verify_studio_run_source_binding,
)


def _snapshot_native_audit(
    document: Path, snapshot: Path, native_audit: dict[str, Any],
) -> dict[str, Any]:
    """Bind this export call's audit to its byte-identical archived document."""
    audit, _ = _audit_exact_document_data(
        document_path=document, spec_path=_veusz_spec_path(document),
        check_presentation=False, native_audit=native_audit,
    )
    rebound = {
        **audit,
        "document": {**audit["document"], "path": str(snapshot.resolve())},
        "spec": {**audit["spec"], "path": str(_veusz_spec_path(snapshot).resolve())},
    }
    verified, _ = _audit_exact_document_data(
        document_path=snapshot, spec_path=_veusz_spec_path(snapshot),
        check_presentation=False, native_audit=rebound,
    )
    return verified


def publish_studio_export_run(
    *,
    project_dir: Path,
    request_path: Path,
    document_path: Path,
    exports: list[dict[str, Any]],
    export_document_sha256: str,
    primary_native_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate, archive, assess, package, and register one Studio run."""

    inventory = prepare_studio_export_inventory(
        project_dir=project_dir,
        request_path=request_path,
        document_path=document_path,
        exports=exports,
        export_document_sha256=export_document_sha256,
    )
    copied_exports, figures = copy_studio_run_exports(
        exports=inventory.exports,
        output_dir=inventory.output_dir,
        figure_set_export_scope=inventory.figure_set_export_scope,
    )
    sources = prepare_studio_run_sources(
        request=inventory.request,
        rule_readiness=inventory.rule_readiness,
        presentation_identity=inventory.presentation_identity,
        effective_request=inventory.effective_request,
        data_mapping_application=inventory.data_mapping_application,
        request_path=inventory.request_path,
        project_dir=inventory.project_dir,
        document_path=inventory.document_path,
        output_dir=inventory.output_dir,
        veusz_documents=inventory.veusz_documents,
    )
    verify_studio_run_source_binding(inventory.resolved_figure_plan, sources)
    _snapshot_studio_directory(
        source=inventory.document_path.parent,
        destination=inventory.output_dir / "studio",
        figure_set=inventory.figure_set,
        verified_spec_hashes=inventory.figure_set_spec_hashes,
    )
    snapshot_documents, _snapshot_hashes = _studio_snapshot_documents(inventory)
    snapshot_map = _studio_snapshot_document_map(
        inventory,
        snapshot_documents=snapshot_documents,
    )
    snapshot_primary_document = snapshot_map[str(inventory.document_path.resolve())]
    result = build_studio_export_result(
        inventory=inventory,
        sources=sources,
        copied_exports=copied_exports,
        figures=figures,
    )
    native_audits = None
    if primary_native_audit is not None:
        # Recheck the live authority before rebinding this call's native evidence
        # to the byte-identical run snapshot. The receiving audit checks both
        # snapshot hashes again; no historical receipt is used as evidence.
        native_audits = {str(snapshot_primary_document.resolve()): _snapshot_native_audit(
            inventory.document_path, snapshot_primary_document, primary_native_audit,
        )}
    scientific = verify_managed_document_sources(
        result, mapping_application=inventory.data_mapping_application,
        **({"native_audits": native_audits} if native_audits is not None else {}),
    )
    result["scientific_data_verification"] = scientific
    if inventory.data_mapping_application is not None:
        result["rendered_source_coverage"] = scientific["mapping_source_coverage"]
    evidence = build_studio_publication_evidence(
        request=inventory.request,
        document_path=snapshot_primary_document,
        output_dir=inventory.output_dir,
        figures=figures,
        copied_exports=copied_exports,
        veusz_documents=snapshot_documents,
        figure_set_export_scope=inventory.figure_set_export_scope,
        sources=sources,
        resolved_figure_plan=(
            result.get("resolved_figure_plan")
            if isinstance(result.get("resolved_figure_plan"), dict)
            else None
        ),
    )
    manifest = build_studio_run_manifest(
        inventory=inventory,
        sources=sources,
        evidence=evidence,
        result=result,
        figures=figures,
    )
    return finalize_studio_run(
        inventory=inventory,
        evidence=evidence,
        manifest=manifest,
        copied_exports=copied_exports,
        figures=figures,
    )
