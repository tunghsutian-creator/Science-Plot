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
        "src/sciplot_gui/studio_assistant/proposal_application.py",
        "src/sciplot_gui/studio_assistant/selection.py",
        "src/sciplot_core/veusz_worker/cli.py",
        "src/sciplot_core/veusz_worker/operations.py",
    ],
)
def test_shared_native_edit_boundaries_select_native_and_gui_regressions(
    path: str,
) -> None:
    plan = build_changed_verification_plan([path], repo_root=REPO_ROOT)
    assert plan["unowned_paths"] == []
    commands = {item["check_id"]: item["command"] for item in plan["checks"]}
    assert "tests/test_native_document_edit.py" in commands["pytest_changed_owners"]
    assert "tests/test_assistant_contract.py" in commands["pytest_changed_owners"]


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
