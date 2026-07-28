"""Finalize, verify, and register a Studio delivery package."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sciplot_core.delivery import build_delivery_package
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.publish_state import build_publish_state
from sciplot_core.study_model import build_output_package_contract

from sciplot_core.studio_core.export_verification import (
    _verify_exact_current_export_binding,
    _verify_studio_delivery_binding,
)
from sciplot_core.studio_core.figure_set_state import (
    _figure_set_export_review_note,
)
from sciplot_core.studio_core.json_files import _write_json_atomic
from sciplot_core.studio_core.publish_evidence import StudioPublicationEvidence
from sciplot_core.studio_core.publish_inventory import StudioExportInventory
from sciplot_core.studio_core.registry_writes import _register_studio_run
from sciplot_core.studio_core.review_artifacts import (
    _write_studio_review_html,
    _write_studio_revision_brief,
)


def finalize_studio_run(
    *,
    inventory: StudioExportInventory,
    evidence: StudioPublicationEvidence,
    manifest: dict[str, Any],
    copied_exports: list[dict[str, Any]],
    figures: list[str],
) -> dict[str, Any]:
    """Write review artifacts, delivery contracts, publish state, and registry."""

    output_dir = inventory.output_dir
    manifest["revision_brief"] = _write_studio_revision_brief(
        output_dir,
        manifest=manifest,
    )
    _write_studio_review_html(output_dir, manifest=manifest)
    _snapshot_studio_directory(
        source=inventory.document_path.parent,
        destination=output_dir / "studio",
    )
    manifest["state"] = "publishing"
    manifest["ready_to_use"] = False
    manifest["publish_complete"] = False
    _write_json_atomic(output_dir / "manifest.json", manifest)
    _finalize_delivery_contracts(
        inventory=inventory,
        manifest=manifest,
        copied_exports=copied_exports,
    )
    manifest.update(
        build_publish_state(
            qa=evidence.qa,
            package_contract=manifest["package_contract"],
            delivery_package=manifest["delivery_package"],
            delivery_verification=manifest["delivery_verification"],
        )
    )
    ready_to_use = bool(manifest["ready_to_use"])
    manifest["publish_complete"] = True
    manifest["failure_stage"] = None if ready_to_use else "quality_or_delivery_gate"
    manifest["failure_reason"] = (
        None
        if ready_to_use
        else "One or more QA, package, or delivery verification gates failed."
    )
    _write_json_atomic(output_dir / "manifest.json", manifest)
    _register_studio_run(inventory.project_dir, manifest)
    payload = {
        "kind": "sciplot_studio_export_run",
        "output": str(output_dir),
        "manifest": str(output_dir / "manifest.json"),
        "review_html": str(output_dir / "review.html"),
        "revision_brief": str(output_dir / "revision_brief.md"),
        "figures": figures,
        "exports": copied_exports,
        "qa": evidence.qa,
        "package_contract": manifest["package_contract"],
        "delivery_package": manifest["delivery_package"],
        "delivery_verification": manifest["delivery_verification"],
        "state": manifest["state"],
        "ready_to_use": ready_to_use,
        "pending_rule_review": inventory.pending_rule_review,
        "autonomous_rule_ready": not inventory.pending_rule_review,
        "scope": manifest["scope"],
    }
    if inventory.figure_set_export_scope is not None:
        payload["figure_set_export_scope"] = json_safe(
            inventory.figure_set_export_scope
        )
    return payload


def _snapshot_studio_directory(*, source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    if source.exists():
        shutil.copytree(source, destination)


def _finalize_delivery_contracts(
    *,
    inventory: StudioExportInventory,
    manifest: dict[str, Any],
    copied_exports: list[dict[str, Any]],
) -> None:
    failure_stage = "package_delivery_finalization"
    try:
        manifest["package_contract"] = build_output_package_contract(
            inventory.output_dir,
            manifest=manifest,
        )
        _attach_complete_figure_set_contracts(
            inventory.figure_set_export_scope,
            package_contract=manifest["package_contract"],
        )
        manifest["delivery_package"] = build_delivery_package(
            inventory.output_dir,
            manifest=manifest,
        )
        _attach_complete_figure_set_delivery(
            inventory.figure_set_export_scope,
            delivery_package=manifest["delivery_package"],
        )
        manifest["delivery_verification"] = _verify_studio_delivery_binding(
            manifest["delivery_package"],
            exports=copied_exports,
            export_document_sha256=inventory.export_document_sha256,
            document_hashes=inventory.veusz_document_hashes,
        )
        failure_stage = "exact_current_binding"
        primary_exports = [
            item
            for item in copied_exports
            if Path(str(item.get("document") or "")).expanduser().resolve()
            == inventory.document_path
        ]
        _verify_exact_current_export_binding(
            document_path=inventory.document_path,
            export_document_sha256=inventory.export_document_sha256,
            exports=primary_exports,
        )
    except Exception as exc:
        manifest["state"] = "failed"
        manifest["ready_to_use"] = False
        manifest["publish_complete"] = False
        manifest["failure_stage"] = failure_stage
        manifest["failure_reason"] = str(exc)
        _write_json_atomic(inventory.output_dir / "manifest.json", manifest)
        raise


def _attach_complete_figure_set_contracts(
    scope: dict[str, Any] | None,
    *,
    package_contract: dict[str, Any],
) -> None:
    if scope is None:
        return
    package_contract["figure_set_export_scope"] = json_safe(scope)
    package_contract["full_figure_set_complete"] = True
    package_contract["complete_scope"] = "full_figure_set_exact_current_delivery"


def _attach_complete_figure_set_delivery(
    scope: dict[str, Any] | None,
    *,
    delivery_package: dict[str, Any],
) -> None:
    if scope is None:
        return
    delivery_package["scope"] = "full_figure_set_project_delivery"
    delivery_package["complete_scope"] = "full_figure_set_exact_current_delivery"
    delivery_package["full_figure_set_complete"] = True
    delivery_package["figure_set_export_scope"] = json_safe(scope)
    delivery_package["limitations"] = [_figure_set_export_review_note(scope)]
