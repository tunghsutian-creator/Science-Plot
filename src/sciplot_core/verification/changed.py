"""Run one focused verification pass for the current changed owners."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
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
    base: str | None = None,
    command_runner: CommandRunner | None = None,
) -> list[str]:
    """Collect the worktree and optionally committed changes from one base."""

    runner = command_runner or _run_command
    paths, _comparison = _collect_scope(repo_root, base, runner)
    return paths


def _resolve_commit(repo_root: Path, revision: str, runner: CommandRunner) -> str:
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("The verification base must name a Git commit.")
    result = runner(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
        repo_root,
    )
    commit = result.stdout.strip()
    if result.returncode or len(commit) not in (40, 64) or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise ValueError(f"Cannot resolve verification revision `{revision}` to a commit.")
    return commit


def _collect_scope(
    repo_root: Path, base: str | None, runner: CommandRunner,
) -> tuple[list[str], dict[str, Any]]:
    head = _resolve_commit(repo_root, "HEAD", runner)
    resolved_base = head if base is None or base == "HEAD" else _resolve_commit(repo_root, base, runner)
    commands = [
        ["git", "diff", "--name-only", "--no-renames", "-z", "--cached", head, "--"],
        ["git", "diff", "--name-only", "--no-renames", "-z", "--"],
    ]
    if base is not None:
        commands.insert(0, ["git", "diff", "--name-only", "--no-renames", "-z", resolved_base, head, "--"])
    commands.append(["git", "ls-files", "--others", "--exclude-standard", "-z"])
    paths: set[str] = set()
    for command in commands:
        result = runner(command, repo_root)
        if result.returncode:
            raise RuntimeError(f"Git verification scope collection failed ({command[1]}).")
        paths.update(_normalize_path(path) for path in result.stdout.split("\0") if path)
    return sorted(paths), {
        "base": "HEAD" if base is None else base,
        "resolved_base": resolved_base,
        "resolved_head": head,
        "includes": (["committed"] if base is not None else []) + ["staged", "unstaged", "untracked"],
        "source": "git",
    }


def build_changed_verification_plan(
    changed_paths: Iterable[str],
    *,
    repo_root: Path,
    comparison: Mapping[str, Any] | None = None,
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
        has_changes=bool(matched_owners),
        diff_base=str(comparison["resolved_base"]) if comparison else "HEAD",
    )
    return {
        "kind": "sciplot_changed_verification",
        "version": 1,
        "status": "failed" if unowned_paths else "planned" if checks else "NO_TESTS",
        "comparison": dict(comparison) if comparison else {
            "base": "HEAD",
            "includes": ["staged", "unstaged", "untracked"],
            "source": "explicit_paths",
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
    base: str | None = None,
    plan_only: bool = False,
) -> dict[str, Any]:
    """Run every planned focused check once, without broad-gate fallback."""

    root = (repo_root or _default_repo_root()).expanduser().resolve()
    runner = command_runner or _run_command
    try:
        if changed_paths is not None:
            if base is not None:
                raise ValueError("An explicit path list cannot also claim a Git base comparison.")
            selected_paths, comparison = list(changed_paths), None
        else:
            selected_paths, comparison = _collect_scope(root, base, runner)
    except (OSError, RuntimeError, ValueError) as exc:
        payload = build_changed_verification_plan([], repo_root=root)
        payload.update(
            status="failed", comparison={"base": "HEAD" if base is None else base},
            error={"reason_code": "invalid_verification_scope", "message": str(exc)},
            plan_only=plan_only, checks_executed=0,
        )
        return payload
    payload = build_changed_verification_plan(selected_paths, repo_root=root, comparison=comparison)
    payload.update(plan_only=plan_only, checks_executed=0)
    if payload["unowned_paths"] or payload["status"] == "NO_TESTS" or plan_only:
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
    payload["checks_executed"] = len(results)
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
    diff_base: str = "HEAD",
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
                "command": ["git", "diff", "--check", diff_base, "--"],
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
