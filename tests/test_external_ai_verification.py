from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from sciplot_core.verification import build_changed_verification_plan


REPO_ROOT = Path(__file__).resolve().parents[1]
TYPED_BEHAVIOR_PATHS = {
    "src/sciplot_core/plan_identity.py": "tests/test_plan_identity.py",
    "src/sciplot_core/plan_preview.py": "tests/test_plan_identity.py",
    "src/sciplot_core/autoplot/run.py": "tests/test_plan_identity.py",
    "src/sciplot_core/cli/dispatch/project.py": "tests/test_project_control_cli.py",
    "src/sciplot_core/cli/dispatch/project_create.py": "tests/test_project_create_cli.py",
    "src/sciplot_core/cli/parsers/project.py": "tests/test_project_control_cli.py",
    "src/sciplot_core/native_settings.py": "tests/test_native_document_edit.py",
    "src/sciplot_core/studio_core/document_edit.py": "tests/test_document_edit.py",
    "src/sciplot_core/studio_core/document_edit_commit.py": "tests/test_document_edit.py",
    "src/sciplot_core/studio_core/document_edit_policy.py": "tests/test_document_edit_policy.py",
    "src/sciplot_core/studio_core/document_edit_state.py": "tests/test_document_edit.py",
    "src/sciplot_core/studio_core/project_query.py": "tests/test_project_query.py",
    "src/sciplot_core/studio_core/project_query_evidence.py": "tests/test_project_query.py",
    "src/sciplot_core/studio_core/project_query_paths.py": "tests/test_project_query.py",
    "src/sciplot_core/studio_core/project_session.py": "tests/test_project_session.py",
    "src/sciplot_core/veusz_worker/document_edit.py": "tests/test_native_document_edit.py",
}

ASSISTANT_DISCLOSURE_TYPED_PATHS = (
    "src/sciplot_core/assistant_provider/facts.py",
    "src/sciplot_core/assistant_provider/disclosure.py",
    "src/sciplot_core/openai_provider/observations.py",
)
ASSISTANT_DISCLOSURE_TARGETS = {
    "tests/test_assistant_disclosure_facts.py",
    "tests/test_assistant_contract.py",
    "tests/test_ai_transport_lifecycle.py",
}
ASSISTANT_PROVIDER_TARGETS = ASSISTANT_DISCLOSURE_TARGETS | {
    "tests/test_compatibility_facades.py",
    "tests/test_automation_baseline.py::test_external_model_call_guard_counts_and_blocks_the_production_adapter",
}
ASSISTANT_HISTORY_TARGETS = ASSISTANT_DISCLOSURE_TARGETS | {
    "tests/test_assistant_history.py", "tests/test_iso_timestamps.py",
}
# Retain each old consumer's responsibility, without restoring its GUI writer.
# History builders/appenders are test fixtures; production history is read-only.
RETAINED_ASSISTANT_CONSUMERS = (
    ("src/sciplot_gui/assistant_runtime.py", "src/sciplot_core/assistant_provider/progress.py"),
    ("src/sciplot_gui/studio_assistant/dock.py", "src/sciplot_core/assistant_provider/provider.py"),
    ("src/sciplot_gui/studio_assistant/request_context.py", "src/sciplot_core/assistant_provider/context_documents.py"),
    ("src/sciplot_gui/studio_assistant/request_flow.py", "src/sciplot_core/assistant_provider/request.py"),
    ("src/sciplot_gui/studio_assistant/context_history.py", "src/sciplot_core/assistant_history/storage.py"),
    ("src/sciplot_gui/studio_assistant/rejection.py", "src/sciplot_core/assistant_provider/response.py"),
    ("src/sciplot_gui/studio_assistant_history/__init__.py", "src/sciplot_core/assistant_history/__init__.py"),
    ("src/sciplot_gui/studio_assistant_history/builder.py", "tests/assistant_history_fixtures/builder.py"),
    ("src/sciplot_gui/studio_assistant_history/contracts.py", "src/sciplot_core/assistant_history/contracts.py"),
    ("src/sciplot_gui/studio_assistant_history/operations.py", "tests/assistant_history_fixtures/operations.py"),
    ("src/sciplot_gui/studio_assistant_history/storage.py", "src/sciplot_core/assistant_history/storage.py"),
    ("src/sciplot_gui/studio_assistant_history/validation.py", "src/sciplot_core/assistant_history/validation.py"),
    ("src/sciplot_gui/studio_assistant_history/values.py", "src/sciplot_core/assistant_history/values.py"),
    ("tests/test_studio_assistant_disclosure.py", "tests/test_assistant_disclosure_facts.py"),
)


def _assert_retired_assistant_responsibility(path: str) -> None:
    renamed_history = {
        f"src/sciplot_gui/studio_assistant_history/{name}.py"
        for name in ("builder", "contracts", "operations", "storage", "validation", "values")
    }
    history = path in renamed_history
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["status"] == "planned" and plan["unowned_paths"] == []
    assert {owner["owner_id"] for owner in plan["owners"]} == {
        "assistant_history" if history else "automation_baseline_evidence"
    }
    command = next(check["command"] for check in plan["checks"]
                   if check["check_id"] == "pytest_changed_owners")
    expected = ASSISTANT_HISTORY_TARGETS if history else {
        "tests/test_frontend_topology.py", "tests/test_headless_native_probe.py",
    }
    assert expected <= set(command)
    assert "tests/test_studio_assistant_disclosure.py" not in command
    assert "full_pytest" in plan["required_later"]["release"]
    assert "smoke" in plan["required_later"]["final_milestone"]


@pytest.mark.parametrize("path", [
    *ASSISTANT_DISCLOSURE_TYPED_PATHS,
    "src/sciplot_core/assistant_provider/__init__.py",
    "src/sciplot_core/assistant_provider/provider.py",
    "src/sciplot_core/assistant_provider/request.py",
    "src/sciplot_core/assistant_provider/response.py",
    "src/sciplot_core/openai_provider/__init__.py",
    "src/sciplot_core/openai_provider/errors.py",
    "src/sciplot_core/openai_provider/provider.py",
    "src/sciplot_core/openai_provider/sse_client.py",
    "src/sciplot_core/openai_provider/transport_helpers.py",
    "tests/test_assistant_disclosure_facts.py",
    "tests/test_assistant_contract.py",
    "tests/test_ai_transport_lifecycle.py",
])
def test_assistant_provider_changes_select_core_disclosure_consumers(path):
    if path.startswith("src/"):
        assert (REPO_ROOT / path).is_file()
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    assert "openai_assistant_provider" in {owner["owner_id"] for owner in plan["owners"]}
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert ASSISTANT_PROVIDER_TARGETS <= set(command)
    assert "tests/test_studio_assistant_disclosure.py" not in command
    assert "full_pytest" in plan["required_later"]["release"]


@pytest.mark.parametrize("retired,path", RETAINED_ASSISTANT_CONSUMERS,
    ids=[retired for retired, _path in RETAINED_ASSISTANT_CONSUMERS])
def test_retired_assistant_consumers_keep_their_core_fact_and_history_evidence(retired, path):
    assert not (REPO_ROOT / retired).exists()
    _assert_retired_assistant_responsibility(retired)
    assert (REPO_ROOT / path).is_file()
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    owners = {owner["owner_id"] for owner in plan["owners"]}
    history = "/assistant_history/" in path or "/assistant_history_fixtures/" in path
    assert ("assistant_history" if history else "openai_assistant_provider") in owners
    assert "native_assistant_dock" not in owners
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert (ASSISTANT_HISTORY_TARGETS if history else ASSISTANT_PROVIDER_TARGETS) <= set(command)
    assert "tests/test_studio_assistant_disclosure.py" not in command
    assert "full_pytest" in plan["required_later"]["release"]
    if history:
        assert {p.relative_to(REPO_ROOT).as_posix()
                for p in (REPO_ROOT / "src/sciplot_core/assistant_history").glob("*.py")} == {
            f"src/sciplot_core/assistant_history/{name}.py"
            for name in ("__init__", "contracts", "storage", "validation", "values")}


def test_assistant_disclosure_adds_only_its_three_reviewed_strict_files():
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["tool"]["mypy"]
    assert config["strict"] is True and config["warn_unreachable"] is True
    for path in ASSISTANT_DISCLOSURE_TYPED_PATHS:
        assert config["files"].count(path) == 1
        plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
        assert [check["command"] for check in plan["checks"]].count([sys.executable, "-m", "mypy"]) == 1
    _assert_retired_assistant_responsibility(
        "src/sciplot_gui/studio_assistant/unreviewed_provider_flow.py",
    )
    unknown = "src/sciplot_core/unreviewed_provider_flow.py"
    plan = build_changed_verification_plan([unknown], repo_root=REPO_ROOT)
    assert plan["status"] == "failed"
    assert plan["unowned_paths"] == [unknown]
    assert plan["owners"] == [] and plan["checks"] == []


@pytest.mark.parametrize("source,target", TYPED_BEHAVIOR_PATHS.items())
def test_external_control_sources_select_behavior_and_existing_strict_scope(
    source: str,
    target: str,
) -> None:
    plan = build_changed_verification_plan([source], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    commands = {item["check_id"]: item["command"] for item in plan["checks"]}
    assert target in commands["pytest_changed_owners"]
    assert commands["pytest_changed_owners"][:6] == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-m",
        "focused",
    ]
    assert commands["mypy_owned_scope"] == [sys.executable, "-m", "mypy"]
    assert "full_pytest" in plan["required_later"]["release"]


def test_external_control_sources_are_in_the_single_configured_type_scope() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scope = config["tool"]["mypy"]["files"]
    assert all(scope.count(path) == 1 for path in TYPED_BEHAVIOR_PATHS)
    assert scope.count("src/sciplot_core/verification/external_ai_owners.py") == 1


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_plan_identity.py",
        "tests/test_document_edit.py",
        "tests/test_document_edit_native.py",
        "tests/test_document_edit_policy.py",
        "tests/test_native_document_edit.py",
        "tests/test_project_query.py",
        "tests/test_project_query_native.py",
        "tests/test_project_session.py",
        "tests/test_project_control_cli.py",
        "tests/test_project_create_cli.py",
        "tests/test_external_ai_verification.py",
    ],
)
def test_external_control_regressions_select_their_behavior_owner(path: str) -> None:
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    commands = {item["check_id"]: item["command"] for item in plan["checks"]}
    assert path in commands["pytest_changed_owners"]
    assert commands["pytest_changed_owners"].count("focused") == 1


@pytest.mark.parametrize(
    "path",
    [
        "src/sciplot_core/assistant_operations.py",
        "src/sciplot_core/assistant_selection.py",
        "src/sciplot_core/veusz_worker/cli.py",
        "src/sciplot_core/veusz_worker/operations.py",
    ],
)
def test_shared_native_edit_boundaries_select_native_and_core_contract_regressions(
    path: str,
) -> None:
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    commands = {item["check_id"]: item["command"] for item in plan["checks"]}
    assert "tests/test_native_document_edit.py" in commands["pytest_changed_owners"]
    assert "tests/test_assistant_contract.py" in commands["pytest_changed_owners"]
    assert "native_document_edit" in {owner["owner_id"] for owner in plan["owners"]}
    retired = {
        "src/sciplot_core/assistant_operations.py": "src/sciplot_gui/studio_assistant/proposal_application.py",
        "src/sciplot_core/assistant_selection.py": "src/sciplot_gui/studio_assistant/selection.py",
    }.get(path)
    if retired is not None:
        assert not (REPO_ROOT / retired).exists()
        _assert_retired_assistant_responsibility(retired)


def test_external_control_batch_keeps_one_focused_pass_and_defers_full_gate() -> None:
    plan = build_changed_verification_plan(
        list(TYPED_BEHAVIOR_PATHS), repo_root=REPO_ROOT
    )
    assert plan["unowned_paths"] == []
    commands = [item["command"] for item in plan["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1
    pytest_command = next(item for item in commands if "pytest" in item)
    targets = pytest_command[6:]
    assert len(targets) == len(set(targets))
    assert "comprehensive" not in pytest_command
    assert plan["required_later"] == {
        "handoff": ["doctor"],
        "final_milestone": ["smoke"],
        "release": ["acceptance_rules", "full_pytest"],
    }
