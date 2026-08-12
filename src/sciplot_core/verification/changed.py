"""Run one focused verification pass for the current changed owners."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from sciplot_core.verification.owners import (
    CHANGED_OWNERS,
    IGNORED_CHANGED_PATHS,
    ChangedOwner,
)


CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def collect_changed_paths(
    repo_root: Path,
    *,
    command_runner: CommandRunner | None = None,
) -> list[str]:
    """Collect staged, unstaged, and untracked paths against HEAD once."""

    runner = command_runner or _run_command
    tracked = runner(
        ["git", "diff", "--name-only", "--no-renames", "-z", "HEAD", "--"],
        repo_root,
    )
    if tracked.returncode != 0:
        raise RuntimeError(tracked.stderr.strip() or "git diff HEAD failed")
    untracked = runner(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        repo_root,
    )
    if untracked.returncode != 0:
        raise RuntimeError(untracked.stderr.strip() or "git ls-files failed")
    return sorted(
        {
            normalized
            for line in [*tracked.stdout.split("\0"), *untracked.stdout.split("\0")]
            if (normalized := _normalize_path(line))
        }
    )


def build_changed_verification_plan(
    changed_paths: Iterable[str],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Map one changed snapshot to explicit focused checks and later gates."""

    paths = sorted({_normalize_path(path) for path in changed_paths if path})
    owner_paths: dict[str, list[str]] = {}
    pytest_targets: set[str] = set()
    unowned_paths: list[str] = []
    matched_owners: list[ChangedOwner] = []

    for path in paths:
        if path in IGNORED_CHANGED_PATHS:
            continue
        matches = [owner for owner in CHANGED_OWNERS if owner.matches(path)]
        if not matches:
            unowned_paths.append(path)
            continue
        for owner in matches:
            if owner not in matched_owners:
                matched_owners.append(owner)
            owner_paths.setdefault(owner.owner_id, []).append(path)
            pytest_targets.update(owner.pytest_targets)
    matched_owners.sort(key=CHANGED_OWNERS.index)

    python_paths = [
        path for path in paths if path.endswith(".py") and (repo_root / path).is_file()
    ]
    checks = [] if unowned_paths else _planned_checks(
        python_paths=python_paths,
        pytest_targets=sorted(pytest_targets),
        mypy_required=any(owner.mypy_required for owner in matched_owners),
        has_changes=bool(paths),
    )
    return {
        "kind": "sciplot_changed_verification",
        "version": 1,
        "status": "failed" if unowned_paths else "planned",
        "comparison": {
            "base": "HEAD",
            "includes": ["staged", "unstaged", "untracked"],
        },
        "changed_paths": paths,
        "owners": [
            {
                "owner_id": owner.owner_id,
                "changed_paths": sorted(owner_paths.get(owner.owner_id, [])),
                "pytest_targets": list(owner.pytest_targets),
            }
            for owner in matched_owners
        ],
        "unowned_paths": sorted(unowned_paths),
        "checks": checks,
        "required_later": {
            "handoff": _unique_gates(owner.handoff_gates for owner in matched_owners),
            "final_milestone": _unique_gates(
                owner.final_milestone_gates for owner in matched_owners
            ),
            "release": _unique_gates(owner.release_gates for owner in matched_owners),
        },
    }


def run_changed_verification(
    *,
    repo_root: Path | None = None,
    changed_paths: Iterable[str] | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Run every planned focused check once, without broad-gate fallback."""

    root = (repo_root or _default_repo_root()).expanduser().resolve()
    runner = command_runner or _run_command
    selected_paths = (
        collect_changed_paths(root, command_runner=runner)
        if changed_paths is None
        else list(changed_paths)
    )
    payload = build_changed_verification_plan(selected_paths, repo_root=root)
    if payload["unowned_paths"]:
        return payload

    results: list[dict[str, Any]] = []
    for check in payload["checks"]:
        completed = runner(check["command"], root)
        results.append(
            {
                **check,
                "status": "passed" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
    payload["checks"] = results
    payload["status"] = (
        "passed"
        if all(result["status"] == "passed" for result in results)
        else "failed"
    )
    return payload


def _planned_checks(
    *,
    python_paths: list[str],
    pytest_targets: list[str],
    mypy_required: bool,
    has_changes: bool,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if python_paths:
        checks.append(
            {
                "check_id": "ruff_changed_python",
                "command": [sys.executable, "-m", "ruff", "check", *python_paths],
                "status": "planned",
            }
        )
    if pytest_targets:
        checks.append(
            {
                "check_id": "pytest_changed_owners",
                "command": [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-m",
                    "focused",
                    *pytest_targets,
                ],
                "status": "planned",
            }
        )
    if mypy_required:
        checks.append(
            {
                "check_id": "mypy_owned_scope",
                "command": [sys.executable, "-m", "mypy"],
                "status": "planned",
            }
        )
    if has_changes:
        checks.append(
            {
                "check_id": "diff_whitespace",
                "command": ["git", "diff", "--check", "HEAD", "--"],
                "status": "planned",
            }
        )
    return checks


def _unique_gates(groups: Iterable[tuple[str, ...]]) -> list[str]:
    return sorted({gate for group in groups for gate in group})


def _normalize_path(path: str) -> str:
    return str(path).removeprefix("./")


def _default_repo_root() -> Path:
    configured = os.environ.get("SCIPLOT_REPO")
    return Path(configured) if configured else Path.cwd()


def _run_command(
    command: Sequence[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


__all__ = [
    "build_changed_verification_plan",
    "collect_changed_paths",
    "run_changed_verification",
]
