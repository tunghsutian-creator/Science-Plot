from __future__ import annotations

from sciplot_core.doctor import (
    _publication_foundation_available,
    _vsz_lifecycle_available,
    doctor_payload,
)


def test_doctor_finds_lifecycle_symbols_through_package_facades() -> None:
    assert _vsz_lifecycle_available()


def test_doctor_finds_publication_symbols_through_package_facades() -> None:
    assert _publication_foundation_available()


def test_doctor_lists_changed_owner_verification_before_broad_gates() -> None:
    routes = doctor_payload()["command_surface"]["developer_validation_routes"]

    assert routes == ["verify", "smoke", "acceptance", "batch"]


def test_doctor_prefers_external_tasks_and_retains_native_compatibility() -> None:
    payload = doctor_payload()
    normal = payload["normal_mode"]
    routes = payload["command_surface"]

    assert normal["task_interface"] == "external_ai"
    assert normal["daily_entrypoint"] == "sciplot task start --request REQUEST_JSON --json"
    assert normal["daily_entrypoint"] == routes["task_family"]["start"]
    assert normal["capabilities_entrypoint"] == "sciplot task capabilities --json"
    assert normal["capabilities_entrypoint"] == routes["task_family"]["capabilities"]
    assert routes["task_family"]["command"] == "task"
    assert routes["task_family"]["preferred_for"] == "external_ai_create_edit_export_and_continuation"
    assert routes["task_family"]["internal_model_required"] is False
    assert routes["project_control"]["command"] == "project"
    assert routes["mcp_transport"]["command"] == "mcp"
    assert routes["mcp_transport"]["internal_model_required"] is False
    assert normal["interactive_entrypoint"] == routes["interactive_family"]["interactive"]
    assert normal["frontend_default"] == "veusz_mainwindow"
    assert normal["frontend_default_scope"] == "compatible_native_editor"
    assert routes["interactive_family"]["command"] == "studio"
    assert routes["automation_family"]["command"] == "autoplot"
    assert routes["automation_family"]["separate_renderer"] is False
    assert "not directly resumable" in routes["automation_family"]["role"]


def test_doctor_exposes_readiness_evidence_scope() -> None:
    envelopes = doctor_payload()["validated_envelopes"]

    assert envelopes["evidence_scope"] == {
        "contract_freshness": "rule_declarations_and_render_request_policy",
        "implementation_freshness": "not_tracked_by_this_registry",
        "human_validation": "historical_owner_confirmation_without_build_binding",
    }
    assert envelopes["claims"]["current_implementation_certified"] is False
    assert envelopes["claims"]["human_validation_bound_to_current_build"] is False
