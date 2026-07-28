"""Coordinate one complete Studio export publication run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.studio_core.publish_evidence import (
    build_studio_publication_evidence,
)
from sciplot_core.studio_core.publish_exports import copy_studio_run_exports
from sciplot_core.studio_core.publish_finalize import finalize_studio_run
from sciplot_core.studio_core.publish_inventory import (
    prepare_studio_export_inventory,
)
from sciplot_core.studio_core.publish_manifest import (
    build_studio_export_result,
    build_studio_run_manifest,
)
from sciplot_core.studio_core.publish_sources import prepare_studio_run_sources


def publish_studio_export_run(
    *,
    project_dir: Path,
    request_path: Path,
    document_path: Path,
    exports: list[dict[str, Any]],
    export_document_sha256: str,
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
        effective_request=inventory.effective_request,
        data_mapping_application=inventory.data_mapping_application,
        request_path=inventory.request_path,
        project_dir=inventory.project_dir,
        document_path=inventory.document_path,
        output_dir=inventory.output_dir,
    )
    evidence = build_studio_publication_evidence(
        request=inventory.request,
        document_path=inventory.document_path,
        output_dir=inventory.output_dir,
        figures=figures,
        copied_exports=copied_exports,
        veusz_documents=inventory.veusz_documents,
        figure_set_export_scope=inventory.figure_set_export_scope,
        sources=sources,
    )
    result = build_studio_export_result(
        inventory=inventory,
        sources=sources,
        copied_exports=copied_exports,
        figures=figures,
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
