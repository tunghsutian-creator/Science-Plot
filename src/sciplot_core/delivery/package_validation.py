"""Revalidate a persisted visible delivery package."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict
from sciplot_core.delivery.runtime_evidence import (
    path_identity, recorded_artifacts_ready, recorded_editor_launcher_current, recorded_delivery_identity, recorded_legacy_veusz_current,
)

from sciplot_core.figure_plan.manifest_gate import figure_plan_manifest_gate
from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.launchers import (
    inspect_delivery_editor_launcher_contract,
    inspect_delivery_launcher_contract,
)
from sciplot_core.policy import (
    DELIVERY_DATA_DIR,
    DELIVERY_EDITOR_LAUNCHER,
    DELIVERY_LAUNCHER,
    DELIVERY_PDF_DIR,
    DELIVERY_PROJECT_DIR,
    DELIVERY_TIFF_DIR,
)

from sciplot_core.delivery.contracts import (
    DELIVERY_BINDING_POLICY_LEGACY,
    DELIVERY_BINDING_POLICY_RESOLVED_PLAN,
    DELIVERY_PACKAGE_CONTRACT_VERSION, LEGACY_DELIVERY_PACKAGE_CONTRACT_VERSION,
)

from sciplot_core.delivery.figure_pairing import (
    _delivery_figure_pairing,
)

from sciplot_core.delivery.file_set_validation import (
    _recorded_file_set,
)
from sciplot_core.delivery.filesystem_metadata import (
    inspect_delivery_metadata,
)
from sciplot_core.delivery.plan_binding import (
    DeliveryRecordsMatchPlanPayload,
    delivery_records_match_plan,
    figure_artifact_hashes_current,
    project_document_hashes_current,
)


class _DeliveryVerificationBindingStatusPayload(TypedDict):
    passed: bool
    reason: Literal[
        "resolved_plan_missing_or_invalid",
        "explicit_legacy_without_resolved_plan",
        "delivery_binding_policy_missing_or_invalid",
    ]


_DeliveryVerificationBindingPayload = (
    DeliveryRecordsMatchPlanPayload | _DeliveryVerificationBindingStatusPayload
)




def verify_delivery_package(
    delivery_package: object,
    *,
    expected_root: Path,
    expected_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Revalidate the persisted minimal delivery against live files and hashes."""

    record = delivery_package if isinstance(delivery_package, dict) else {}
    expected = expected_root.expanduser().resolve()
    path_value = record.get("path")
    recorded_root = (
        Path(path_value).expanduser().resolve()
        if isinstance(path_value, str) and path_value.strip()
        else None
    )
    root_ready = bool(recorded_root is not None and path_identity(recorded_root) == path_identity(expected) and expected.is_dir())
    # Fresh deliveries have no browser entry. Recorded historical evidence still
    # requires the complete v1 contract and remains part of the exact file set.
    editor_recorded = any(
        key in record
        for key in ("open_in_sciplot", "open_in_sciplot_sha256", "editor_launcher_contract")
    )
    identity_checks, live_identity, identity_name = recorded_delivery_identity(record, expected)
    expected_top_level = {
        DELIVERY_DATA_DIR,
        DELIVERY_PDF_DIR,
        DELIVERY_TIFF_DIR,
        DELIVERY_PROJECT_DIR,
        identity_name,
    }
    if editor_recorded:
        expected_top_level.add(DELIVERY_EDITOR_LAUNCHER)
    native_legacy_recorded = record.get("version") == DELIVERY_PACKAGE_CONTRACT_VERSION and "legacy_veusz_launcher" in record
    if native_legacy_recorded:
        expected_top_level.add(DELIVERY_LAUNCHER)
    metadata = inspect_delivery_metadata(expected, expected_top_level=expected_top_level)
    data_check = _recorded_file_set(
        record.get("data_csvs"),
        directory=expected / DELIVERY_DATA_DIR,
        suffixes={".csv"},
        hash_field="sha256",
    )
    figure_records = record.get("figures")
    pdf_records = (
        [
            item
            for item in figure_records
            if isinstance(item, dict)
            and Path(str(item.get("path") or "")).suffix.casefold() == ".pdf"
        ]
        if isinstance(figure_records, list)
        else None
    )
    tiff_records = (
        [
            item
            for item in figure_records
            if isinstance(item, dict)
            and Path(str(item.get("path") or "")).suffix.casefold() in {".tif", ".tiff"}
        ]
        if isinstance(figure_records, list)
        else None
    )
    pdf_check = _recorded_file_set(
        pdf_records,
        directory=expected / DELIVERY_PDF_DIR,
        suffixes={".pdf"},
        hash_field="delivery_sha256",
    )
    tiff_check = _recorded_file_set(
        tiff_records,
        directory=expected / DELIVERY_TIFF_DIR,
        suffixes={".tif", ".tiff"},
        hash_field="delivery_sha256",
    )
    recorded_pairing = (
        _delivery_figure_pairing(
            [item for item in figure_records if isinstance(item, dict)]
        )
        if isinstance(figure_records, list)
        else {}
    )
    project_check = _recorded_file_set(
        record.get("project_documents"),
        directory=expected / DELIVERY_PROJECT_DIR,
        suffixes={".vsz"},
        hash_field="delivery_sha256",
    )
    live_figure_records = [
        {"path": path}
        for directory, suffixes in (
            (expected / DELIVERY_PDF_DIR, {".pdf"}),
            (expected / DELIVERY_TIFF_DIR, {".tif", ".tiff"}),
        )
        if directory.is_dir()
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in suffixes
    ]
    pairing = _delivery_figure_pairing(live_figure_records)
    live_editor_contract = (
        inspect_delivery_editor_launcher_contract(expected) if editor_recorded else {}
    )
    editor_launcher_current = not editor_recorded or recorded_editor_launcher_current(
        record, expected_root=expected, contract=live_editor_contract,
    )
    native_legacy_contract = inspect_delivery_launcher_contract(expected) if native_legacy_recorded else {}
    native_legacy_current = not native_legacy_recorded or recorded_legacy_veusz_current(
        record, expected_root=expected, contract=native_legacy_contract)
    artifacts = record.get("artifacts")
    plan_artifact = (
        next(
            (
                item
                for item in artifacts
                if isinstance(item, dict)
                and item.get("id") == "resolved_figure_plan_complete"
            ),
            None,
        )
        if isinstance(artifacts, list)
        else None
    )
    plan_details = (
        plan_artifact.get("details")
        if isinstance(plan_artifact, dict)
        and isinstance(plan_artifact.get("details"), dict)
        else None
    )
    try:
        recorded_plan = resolved_figure_plan_from_payload(
            record.get("resolved_figure_plan")
        )
    except (TypeError, ValueError):
        recorded_plan = None
    expected_plan_gate = figure_plan_manifest_gate(expected_manifest)
    expected_plan_payload = (
        expected_manifest.get("resolved_figure_plan")
        if expected_plan_gate is not None
        and expected_plan_gate["valid"] is True
        and isinstance(expected_manifest.get("resolved_figure_plan"), dict)
        else None
    )
    plans_match = bool(
        recorded_plan is not None
        and expected_plan_payload is not None
        and recorded_plan.to_payload() == expected_plan_payload
    )
    expected_binding_policy = (
        DELIVERY_BINDING_POLICY_RESOLVED_PLAN
        if expected_plan_gate is not None
        else DELIVERY_BINDING_POLICY_LEGACY
    )
    binding_policy = record.get("binding_policy")
    resolved_binding = binding_policy == DELIVERY_BINDING_POLICY_RESOLVED_PLAN
    legacy_binding = binding_policy == DELIVERY_BINDING_POLICY_LEGACY
    binding_policy_current = bool(
        (
            resolved_binding
            and binding_policy == expected_binding_policy
            and plan_artifact is not None
            and plans_match
        )
        or (
            legacy_binding
            and binding_policy == expected_binding_policy
            and plan_artifact is None
            and record.get("resolved_figure_plan") is None
            and expected_plan_gate is None
        )
    )
    if resolved_binding:
        plan_record_current = bool(
            recorded_plan is not None
            and plans_match
            and recorded_plan.complete
        )
    elif legacy_binding:
        plan_record_current = bool(
            plan_artifact is None and record.get("resolved_figure_plan") is None
        )
    else:
        plan_record_current = False
    selected_figure_ids = (
        set(recorded_plan.selected_figure_ids)
        if recorded_plan is not None
        else set()
    )
    if resolved_binding:
        plan_coverage_current = bool(
            isinstance(plan_artifact, dict)
            and plan_artifact.get("exists") is True
            and isinstance(plan_details, dict)
            and plan_details.get("valid") is True
            and plan_details.get("complete") is True
            and plan_record_current
            and recorded_pairing.get("passed") is True
            and selected_figure_ids
            == set(recorded_pairing.get("complete_figure_ids", []))
            and not recorded_pairing.get("unidentified_paths")
        )
    elif legacy_binding:
        plan_coverage_current = binding_policy_current
    else:
        plan_coverage_current = False
    project_records = record.get("project_documents")
    project_figure_ids = (
        [
            str(item.get("figure_id") or "").strip()
            for item in project_records
            if isinstance(item, dict)
        ]
        if isinstance(project_records, list)
        else []
    )
    plan_record_binding: _DeliveryVerificationBindingPayload
    if resolved_binding:
        plan_project_coverage_current = bool(
            len(project_figure_ids) == len(selected_figure_ids)
            and all(project_figure_ids)
            and set(project_figure_ids) == selected_figure_ids
        )
        plan_project_hashes_current = project_document_hashes_current(project_records)
        plan_record_binding = (
            delivery_records_match_plan(
                recorded_plan,
                figure_records=figure_records,
                project_records=project_records,
            )
            if recorded_plan is not None
            else {"passed": False, "reason": "resolved_plan_missing_or_invalid"}
        )
        plan_figure_hashes_current = figure_artifact_hashes_current(figure_records)
    elif legacy_binding:
        plan_project_coverage_current = binding_policy_current
        plan_project_hashes_current = binding_policy_current
        plan_record_binding = {
            "passed": binding_policy_current,
            "reason": "explicit_legacy_without_resolved_plan",
        }
        plan_figure_hashes_current = binding_policy_current
    else:
        plan_project_coverage_current = False
        plan_project_hashes_current = False
        plan_record_binding = {
            "passed": False,
            "reason": "delivery_binding_policy_missing_or_invalid",
        }
        plan_figure_hashes_current = False
    artifact_records_ready = recorded_artifacts_ready(artifacts)
    checks = {
        "record_kind_current": record.get("kind") == "sciplot_user_delivery_package"
        and type(record.get("version")) is int
        and record.get("version") in {DELIVERY_PACKAGE_CONTRACT_VERSION, LEGACY_DELIVERY_PACKAGE_CONTRACT_VERSION},
        "recorded_complete": record.get("complete") is True,
        "binding_policy_current": binding_policy_current,
        "canonical_root": root_ready,
        "minimal_top_level": metadata["minimal_top_level"],
        "filesystem_metadata_safe": metadata["filesystem_metadata_safe"],
        "data_files_current": data_check["passed"],
        "pdf_files_current": pdf_check["passed"],
        "tiff_files_current": tiff_check["passed"],
        "project_files_current": project_check["passed"],
        "canonical_pdf_tiff_pairs": pairing["passed"],
        "resolved_figure_plan_record_current": plan_record_current,
        "resolved_figure_plan_coverage": plan_coverage_current,
        "resolved_figure_plan_project_document_coverage": (
            plan_project_coverage_current
        ),
        "resolved_figure_plan_project_document_hashes": (plan_project_hashes_current),
        "resolved_figure_plan_record_bindings": plan_record_binding["passed"],
        "resolved_figure_plan_figure_hashes": plan_figure_hashes_current,
        **identity_checks,
        "editor_launcher_current": editor_launcher_current,
        "legacy_veusz_launcher_current": native_legacy_current,
        "artifact_records_current": artifact_records_ready,
    }
    return {
        "kind": "sciplot_delivery_verification",
        "version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": [key for key, passed in checks.items() if not passed],
        "expected_root": str(expected),
        "recorded_root": str(recorded_root) if recorded_root is not None else None,
        "top_level": metadata["top_level"],
        "invalid_finder_metadata": metadata["invalid_finder_metadata"],
        "data": data_check,
        "pdf": pdf_check,
        "tiff": tiff_check,
        "project": project_check,
        "pairing": pairing,
        "resolved_figure_plan_binding": plan_record_binding,
        ("identity" if record.get("version") == DELIVERY_PACKAGE_CONTRACT_VERSION else "launcher"): live_identity,
        "editor_launcher": live_editor_contract if editor_recorded else None,
        "legacy_veusz_launcher": native_legacy_contract if native_legacy_recorded else None,
    }
