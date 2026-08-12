from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence

import pytest

from sciplot_core.verification import (
    build_changed_verification_plan,
    collect_changed_paths,
    run_changed_verification,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _completed(
    command: Sequence[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        list(command),
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_changed_snapshot_merges_tracked_and_untracked_once() -> None:
    calls: list[list[str]] = []

    def runner(
        command: Sequence[str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == REPO_ROOT
        calls.append(list(command))
        if list(command[:2]) == ["git", "diff"]:
            return _completed(
                command,
                stdout=(
                    "README.md\0"
                    "src/sciplot_core/intake/session.py\0"
                    "docs/验证.md\0"
                    "docs/line\nbreak.md\0"
                ),
            )
        return _completed(
            command,
            stdout=(
                "tests/test_changed_verification.py\0"
                "README.md\0"
                "docs/ leading and trailing.md \0"
            ),
        )

    assert collect_changed_paths(REPO_ROOT, command_runner=runner) == [
        "README.md",
        "docs/ leading and trailing.md ",
        "docs/line\nbreak.md",
        "docs/验证.md",
        "src/sciplot_core/intake/session.py",
        "tests/test_changed_verification.py",
    ]
    assert calls == [
        ["git", "diff", "--name-only", "--no-renames", "-z", "HEAD", "--"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ]


def test_changed_owners_build_one_deduplicated_focused_pass() -> None:
    payload = build_changed_verification_plan(
        [
            "README.md",
            "src/sciplot_core/verification/changed.py",
            "src/sciplot_core/verification/owners.py",
            "src/sciplot_core/intake/session.py",
            "tests/test_changed_verification.py",
        ],
        repo_root=REPO_ROOT,
    )

    assert payload["status"] == "planned"
    assert payload["unowned_paths"] == []
    assert [owner["owner_id"] for owner in payload["owners"]] == [
        "documentation_contract",
        "changed_verification",
        "intake_project",
    ]
    checks = {check["check_id"]: check for check in payload["checks"]}
    pytest_command = checks["pytest_changed_owners"]["command"]
    assert pytest_command[:6] == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-m",
        "focused",
    ]
    assert pytest_command.count("tests/test_changed_verification.py") == 1
    assert set(checks) == {
        "ruff_changed_python",
        "pytest_changed_owners",
        "diff_whitespace",
    }
    assert payload["required_later"] == {
        "handoff": ["doctor"],
        "final_milestone": ["smoke"],
        "release": ["full_pytest"],
    }
    generated = " ".join(
        part for check in payload["checks"] for part in check["command"]
    )
    assert "smoke" not in generated
    assert "acceptance" not in generated
    assert "comprehensive" not in generated


def test_skill_wrapper_defers_runtime_gates_without_selecting_comprehensive() -> None:
    payload = build_changed_verification_plan(
        ["skill/scripts/sciplot"],
        repo_root=REPO_ROOT,
    )

    assert payload["status"] == "planned"
    assert payload["owners"] == [
        {
            "owner_id": "skill_wrapper",
            "changed_paths": ["skill/scripts/sciplot"],
            "pytest_targets": ["tests/test_skill_wrapper_contract.py"],
        }
    ]
    pytest_check = next(
        check
        for check in payload["checks"]
        if check["check_id"] == "pytest_changed_owners"
    )
    assert "tests/test_skill_wrapper_contract.py" in pytest_check["command"]
    assert "tests/test_skill_wrapper_cwd.py" not in pytest_check["command"]
    assert payload["required_later"] == {
        "handoff": ["doctor"],
        "final_milestone": ["smoke"],
        "release": ["full_pytest"],
    }


def test_typed_owner_adds_the_existing_mypy_scope_once() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/foundation/text_values.py"],
        repo_root=REPO_ROOT,
    )

    commands = [check["command"] for check in payload["checks"]]
    assert commands.count([sys.executable, "-m", "mypy"]) == 1


def test_deleted_owned_source_selects_owner_evidence_but_not_ruff() -> None:
    payload = build_changed_verification_plan(
        ["src/sciplot_core/intake/deleted_owner.py"],
        repo_root=REPO_ROOT,
    )

    assert payload["status"] == "planned"
    assert [owner["owner_id"] for owner in payload["owners"]] == ["intake_project"]
    assert [check["check_id"] for check in payload["checks"]] == [
        "pytest_changed_owners",
        "diff_whitespace",
    ]


def test_no_changes_passes_without_running_an_empty_focused_tier() -> None:
    calls: list[list[str]] = []

    result = run_changed_verification(
        repo_root=REPO_ROOT,
        changed_paths=[],
        command_runner=lambda command, _cwd: (
            calls.append(list(command)) or _completed(command)
        ),
    )

    assert result["status"] == "passed"
    assert result["checks"] == []
    assert calls == []


@pytest.mark.parametrize(
    "path",
    ["src/sciplot_core/unowned.py", "tests/test_deleted_owner.py"],
)
def test_unowned_or_deleted_path_fails_without_broad_fallback(path: str) -> None:
    calls: list[list[str]] = []

    result = run_changed_verification(
        repo_root=REPO_ROOT,
        changed_paths=[path],
        command_runner=lambda command, _cwd: (
            calls.append(list(command)) or _completed(command)
        ),
    )

    assert result["status"] == "failed"
    assert result["unowned_paths"] == [path]
    assert result["checks"] == []
    assert calls == []


def test_check_failure_is_projected_without_retry_or_gate_expansion() -> None:
    calls: list[list[str]] = []

    def runner(
        command: Sequence[str],
        _cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return _completed(
            command,
            returncode=1 if "pytest" in command else 0,
            stderr="focused failure" if "pytest" in command else "",
        )

    result = run_changed_verification(
        repo_root=REPO_ROOT,
        changed_paths=["tests/test_changed_verification.py"],
        command_runner=runner,
    )

    assert result["status"] == "failed"
    assert [check["status"] for check in result["checks"]] == [
        "passed",
        "failed",
        "passed",
    ]
    assert len(calls) == 3
    pytest_calls = [command for command in calls if "pytest" in command]
    assert len(pytest_calls) == 1
    assert pytest_calls[0].count("tests/test_changed_verification.py") == 1
    assert "tests/test_skill_wrapper_cwd.py" not in pytest_calls[0]
