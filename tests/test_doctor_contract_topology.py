from __future__ import annotations

from pathlib import Path

import pytest

from sciplot_core.doctor import (
    _next_actions,
    _publication_foundation_available,
    _vsz_lifecycle_available,
    doctor_payload,
)
from sciplot_core.doctor import payload as doctor_module


@pytest.mark.parametrize(
    ("wrapper_kind", "expected_status"),
    [("missing", "failed"), ("directory", "failed"),
     ("non_executable", "failed"), ("executable", "passed")],
)
def test_doctor_requires_a_regular_executable_skill_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    wrapper_kind: str, expected_status: str,
) -> None:
    wrapper = tmp_path / "skill" / "scripts" / "sciplot"
    wrapper.parent.mkdir(parents=True)
    if wrapper_kind == "directory":
        wrapper.mkdir()
    elif wrapper_kind != "missing":
        wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        wrapper.chmod(0o755 if wrapper_kind == "executable" else 0o644)
    (tmp_path / "pyproject.toml").touch()
    monkeypatch.setattr(doctor_module, "REPO_ROOT", tmp_path)
    original_mode = wrapper.stat().st_mode if wrapper.exists() else None

    payload = doctor_payload()

    check = next(item for item in payload["checks"] if item["id"] == "skill_wrapper")
    assert check["status"] == expected_status
    assert check["required"] is True
    assert check["detail"] == str(wrapper)
    if expected_status == "failed":
        assert payload["status"] == "blocked"
    assert (wrapper.stat().st_mode if wrapper.exists() else None) == original_mode


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
    assert normal["interactive_entrypoint"] == "sciplot edit PROJECT_OR_DELIVERY"
    assert normal["frontend_default"] == "live_editor"
    assert normal["frontend_default_scope"] == "saved_project_visual_adjustments"
    assert routes["interactive_family"]["command"] == "edit"
    assert routes["interactive_family"]["document_authority"] == "saved_vsz"
    assert normal["native_editor_entrypoint"] == routes["native_compatibility"]["interactive"]
    assert routes["native_compatibility"]["command"] == "studio"
    assert payload["vsz_lifecycle"]["editor"] == "live_editor"
    assert payload["vsz_lifecycle"]["native_editor"] == "veusz_mainwindow"
    assert any("Open_in_SciPlot.command" in item for item in _next_actions([]))
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
