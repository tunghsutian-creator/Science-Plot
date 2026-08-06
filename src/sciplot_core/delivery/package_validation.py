"""Revalidate a persisted visible delivery package."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from sciplot_core.figure_plan.manifest_gate import figure_plan_manifest_gate
from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload
from sciplot_core.launchers import (
    inspect_delivery_launcher_contract,
)
from sciplot_core.policy import (
    DELIVERY_DATA_DIR,
    DELIVERY_LAUNCHER,
    DELIVERY_PDF_DIR,
    DELIVERY_PROJECT_DIR,
    DELIVERY_TIFF_DIR,
)

from sciplot_core.delivery.contracts import (
    DELIVERY_BINDING_POLICY_LEGACY,
    DELIVERY_BINDING_POLICY_RESOLVED_PLAN,
    DELIVERY_PACKAGE_CONTRACT_VERSION,
)

from sciplot_core.delivery.figure_pairing import (
    _delivery_figure_pairing,
)

from sciplot_core.delivery.file_set_validation import (
    _recorded_file_set,
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
    root_ready = bool(recorded_root == expected and expected.is_dir())
    expected_top_level = {
        DELIVERY_DATA_DIR,
        DELIVERY_PDF_DIR,
        DELIVERY_TIFF_DIR,
        DELIVERY_PROJECT_DIR,
        DELIVERY_LAUNCHER,
    }
    actual_top_level = (
        {path.name for path in expected.iterdir()} if expected.is_dir() else set()
    )
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
    launcher = expected / DELIVERY_LAUNCHER
    live_launcher_contract = inspect_delivery_launcher_contract(expected)
    recorded_launcher_contract = (
        record.get("launcher_contract")
        if isinstance(record.get("launcher_contract"), dict)
        else {}
    )
    recorded_launcher_path = record.get("open_in_veusz")
    launcher_path_current = bool(
        isinstance(recorded_launcher_path, str)
        and recorded_launcher_path.strip()
        and Path(recorded_launcher_path).expanduser().resolve() == launcher.resolve()
    )
    recorded_launcher_sha256 = str(record.get("open_in_veusz_sha256") or "").strip()
    launcher_hash_current = bool(
        recorded_launcher_sha256
        and recorded_launcher_sha256 == live_launcher_contract.get("content_sha256")
    )
    launcher_structure_current = bool(
        live_launcher_contract.get("ready") is True
        and live_launcher_contract.get("canonical_structure") is True
        and live_launcher_contract.get("required_command_present") is True
    )
    launcher_contract_current = bool(
        recorded_launcher_contract
        and recorded_launcher_contract == live_launcher_contract
    )
    launcher_ready = bool(
        launcher_path_current
        and launcher_hash_current
        and launcher_structure_current
        and launcher_contract_current
    )
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
    try:
        expected_plan = resolved_figure_plan_from_payload(
            expected_manifest.get("resolved_figure_plan")
        )
    except (TypeError, ValueError):
        expected_plan = None
    expected_binding_policy = (
        DELIVERY_BINDING_POLICY_RESOLVED_PLAN
        if figure_plan_manifest_gate(expected_manifest) is not None
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
            and recorded_plan is not None
            and expected_plan is not None
            and recorded_plan.to_payload() == expected_plan.to_payload()
        )
        or (
            legacy_binding
            and binding_policy == expected_binding_policy
            and plan_artifact is None
            and record.get("resolved_figure_plan") is None
            and expected_plan is None
        )
    )
    if resolved_binding:
        plan_record_current = bool(
            recorded_plan is not None
            and expected_plan is not None
            and recorded_plan.to_payload() == expected_plan.to_payload()
            and recorded_plan.complete
            and isinstance(plan_details, dict)
            and plan_details.get("plan_id") == recorded_plan.plan_id
            and plan_details.get("plan_sha256") == recorded_plan.plan_sha256
            and plan_details.get("selected_figure_ids")
            == list(recorded_plan.selected_figure_ids)
        )
    elif legacy_binding:
        plan_record_current = bool(
            plan_artifact is None and record.get("resolved_figure_plan") is None
        )
    else:
        plan_record_current = False
    selected_values = (
        plan_details.get("selected_figure_ids")
        if isinstance(plan_details, dict)
        else None
    )
    selected_figure_ids = (
        {value for value in selected_values if isinstance(value, str) and value}
        if isinstance(selected_values, list)
        and all(isinstance(value, str) and value for value in selected_values)
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
    artifact_records_ready = bool(
        isinstance(artifacts, list)
        and artifacts
        and all(
            isinstance(item, dict)
            and item.get("exists") is True
            and isinstance(item.get("path"), str)
            and Path(str(item["path"])).expanduser().exists()
            for item in artifacts
        )
    )
    checks = {
        "record_kind_current": record.get("kind") == "sciplot_user_delivery_package"
        and record.get("version") == DELIVERY_PACKAGE_CONTRACT_VERSION,
        "recorded_complete": record.get("complete") is True,
        "binding_policy_current": binding_policy_current,
        "canonical_root": root_ready,
        "minimal_top_level": actual_top_level == expected_top_level,
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
        "launcher_path_current": launcher_path_current,
        "launcher_hash_current": launcher_hash_current,
        "launcher_structure_current": launcher_structure_current,
        "launcher_contract_current": launcher_contract_current,
        "launcher_current": launcher_ready,
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
        "top_level": {
            "expected": sorted(expected_top_level),
            "actual": sorted(actual_top_level),
        },
        "data": data_check,
        "pdf": pdf_check,
        "tiff": tiff_check,
        "project": project_check,
        "pairing": pairing,
        "resolved_figure_plan_binding": plan_record_binding,
        "launcher": live_launcher_contract,
    }
