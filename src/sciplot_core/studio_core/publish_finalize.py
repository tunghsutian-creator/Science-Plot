"""Finalize, verify, and register a Studio delivery package."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sciplot_core.automation_states import RULE_REPAIR_STATE
from sciplot_core.delivery import build_delivery_package
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.presentation_identity import (
    require_selected_presentation_payload,
    require_selected_template,
)
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
    _validate_presentation_projections(
        inventory=inventory,
        manifest=manifest,
    )
    canonical_rule_readiness = inventory.rule_readiness.to_payload()
    result_value = manifest.get("result")
    if not isinstance(result_value, dict):
        raise RuntimeError(
            "Studio manifest result is missing canonical rule readiness evidence."
        )
    if manifest.get("rule_readiness") != canonical_rule_readiness:
        raise RuntimeError(
            "Studio manifest rule readiness does not match the canonical "
            "publication inventory."
        )
    if result_value.get("rule_readiness") != canonical_rule_readiness:
        raise RuntimeError(
            "Studio result rule readiness does not match the canonical "
            "publication inventory."
        )
    semantic = (
        manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else None
    )
    if (
        semantic is None
        or semantic.get("studio_rule_publication_readiness") != canonical_rule_readiness
    ):
        raise RuntimeError(
            "Studio semantic rule readiness does not match the canonical "
            "publication inventory."
        )
    if semantic.get("publication_rule_ready") is not (
        not inventory.publication_rule_blocked
    ):
        raise RuntimeError(
            "Studio semantic publication-rule projection does not match the "
            "canonical publication inventory."
        )
    expected_projections = {
        "pending_rule_review": inventory.pending_rule_review,
        "publication_rule_blocked": inventory.publication_rule_blocked,
        "autonomous_rule_ready": not inventory.publication_rule_blocked,
    }
    for field, expected in expected_projections.items():
        if manifest.get(field) is not expected:
            raise RuntimeError(
                f"Studio manifest `{field}` does not match the canonical "
                "publication inventory."
            )
        if result_value.get(field) is not expected:
            raise RuntimeError(
                f"Studio result `{field}` does not match the canonical "
                "publication inventory."
            )
    manifest["rule_readiness"] = canonical_rule_readiness
    result_value["rule_readiness"] = canonical_rule_readiness
    manifest["revision_brief"] = _write_studio_revision_brief(
        output_dir,
        manifest=manifest,
    )
    _write_studio_review_html(output_dir, manifest=manifest)
    manifest["state"] = "publishing"
    manifest["ready_to_use"] = False
    manifest["publish_complete"] = False
    _write_json_atomic(output_dir / "manifest.json", manifest)
    _finalize_delivery_contracts(
        inventory=inventory,
        manifest=manifest,
        copied_exports=copied_exports,
    )
    prerequisite_state = (
        RULE_REPAIR_STATE if inventory.publication_rule_blocked else None
    )
    manifest.update(
        build_publish_state(
            qa=evidence.qa,
            package_contract=manifest["package_contract"],
            delivery_package=manifest["delivery_package"],
            delivery_verification=manifest["delivery_verification"],
            prerequisite_state=prerequisite_state,
            resolved_figure_plan=manifest.get("resolved_figure_plan"),
        )
    )
    ready_to_use = bool(manifest["ready_to_use"])
    manifest["publish_complete"] = True
    if ready_to_use:
        failure_stage = None
        failure_reason = None
    elif inventory.publication_rule_blocked:
        failure_stage = (
            "rule_readiness_gate"
            if inventory.pending_rule_review
            else "rule_contract_gate"
        )
        failure_reason = inventory.rule_readiness.failure_reason
        if failure_reason is None:
            raise RuntimeError(
                "Studio publication readiness is blocked without a failure reason."
            )
    else:
        failure_stage = "quality_or_delivery_gate"
        failure_reason = (
            "One or more QA, package, or delivery verification gates failed."
        )
    manifest["failure_stage"] = failure_stage
    manifest["failure_reason"] = failure_reason
    _write_json_atomic(output_dir / "manifest.json", manifest)
    durable_exports = (
        json_safe(result_value.get("exports"))
        if isinstance(result_value.get("exports"), list)
        else []
    )
    payload = {
        "kind": "sciplot_studio_export_run",
        "output": str(output_dir),
        "manifest": str(output_dir / "manifest.json"),
        "review_html": str(output_dir / "review.html"),
        "revision_brief": str(output_dir / "revision_brief.md"),
        "figures": figures,
        "exports": durable_exports,
        "qa": evidence.qa,
        "package_contract": manifest["package_contract"],
        "delivery_package": manifest["delivery_package"],
        "delivery_verification": manifest["delivery_verification"],
        "state": manifest["state"],
        "ready_to_use": ready_to_use,
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "template": inventory.presentation_identity.template,
        "presentation_identity": inventory.presentation_identity.to_payload(),
        "rule_readiness": canonical_rule_readiness,
        "pending_rule_review": inventory.pending_rule_review,
        "publication_rule_blocked": inventory.publication_rule_blocked,
        "autonomous_rule_ready": not inventory.publication_rule_blocked,
        "scope": manifest["scope"],
    }
    if inventory.figure_set_export_scope is not None:
        payload["figure_set_export_scope"] = json_safe(
            inventory.figure_set_export_scope
        )
    if isinstance(manifest.get("resolved_figure_plan"), dict):
        payload["resolved_figure_plan"] = json_safe(manifest["resolved_figure_plan"])
        payload["figure_outcomes"] = json_safe(manifest.get("figure_outcomes", []))
    _register_studio_run(
        inventory.project_dir,
        manifest,
        studio_run=payload,
    )
    return payload


def _validate_presentation_projections(
    *,
    inventory: StudioExportInventory,
    manifest: dict[str, Any],
) -> None:
    """Reject selected-presentation splits before the first publication write."""

    expected = inventory.presentation_identity
    require_selected_template(
        inventory.request.get("template"),
        expected=expected,
        source="canonical plot request",
    )
    require_selected_template(
        manifest.get("template"),
        expected=expected,
        source="Studio manifest",
    )
    require_selected_presentation_payload(
        manifest.get("presentation_identity"),
        expected=expected,
        source="Studio manifest",
    )
    result = manifest.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(
            "presentation_identity_mismatch: Studio manifest result is missing."
        )
    require_selected_template(
        result.get("template"),
        expected=expected,
        source="Studio result",
    )
    require_selected_presentation_payload(
        result.get("presentation_identity"),
        expected=expected,
        source="Studio result",
    )
    semantic = manifest.get("semantic")
    if not isinstance(semantic, dict):
        raise RuntimeError(
            "presentation_identity_mismatch: Studio semantic evidence is missing."
        )
    require_selected_presentation_payload(
        semantic.get("presentation_identity"),
        expected=expected,
        source="Studio semantic evidence",
    )
    studio = manifest.get("studio")
    if not isinstance(studio, dict):
        raise RuntimeError(
            "presentation_identity_mismatch: Studio manifest block is missing."
        )
    require_selected_presentation_payload(
        studio.get("presentation_identity"),
        expected=expected,
        source="Studio manifest block",
    )


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
            document_hashes=(
                manifest.get("veusz_document_hashes")
                if isinstance(manifest.get("veusz_document_hashes"), dict)
                else inventory.veusz_document_hashes
            ),
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
