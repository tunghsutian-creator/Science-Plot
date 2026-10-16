"""Execute or reuse only the fresh changed plan's independently sealed checks.

Receipt paths never select commands or expand the current owner scope. Normal
changed verification does not import this optional fingerprinting path.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import time
from typing import Any

from sciplot_core.verification.durable_runner import artifact_hashes, run_status, start_run
from sciplot_core.verification.evidence import atomic_json, check_reuse, load_receipt
from sciplot_core.verification.evidence_identity import capture_identity, digest


def _closed_directory(repo_root: Path, directory: Path) -> Path:
    root = repo_root.resolve()
    path = directory.expanduser()
    path = path if path.is_absolute() else root / path
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise ValueError("Verification evidence must remain under repository .tmp_verify.") from exc
    if len(parts) < 2 or parts[0] != ".tmp_verify" or ".." in parts:
        raise ValueError("Use a named verification directory under repository .tmp_verify.")
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Verification evidence directories cannot follow symlinks.")
    return path


def _prepare_specs(plan: dict[str, Any], repo_root: Path, directory: Path) -> list[dict[str, Any]]:
    from sciplot_core.verification.evidence_scope import build_check_spec

    specs = []
    seen: set[str] = set()
    for check in plan["checks"]:
        check_id = check["check_id"]
        if not isinstance(check_id, str) or not re.fullmatch("[a-z][a-z0-9_]*", check_id) or check_id in seen:
            raise ValueError("Invalid or repeated verification check identity.")
        seen.add(check_id)
        check_dir = _closed_directory(repo_root, directory / check_id)
        environment = dict(os.environ, SCIPLOT_VERIFY_FINISH=str(check_dir / "finish.json"))
        specs.append(build_check_spec(plan, check, repo_root, environment=environment,
                                      finish_path=check_dir / "finish.json"))
    return specs


def _await_original(repo_root: Path, directory: Path) -> dict[str, Any]:
    startup_deadline = time.monotonic() + 30
    while True:
        _closed_directory(repo_root, directory)
        result = run_status(directory)
        if result["status"] == "RUNNING":
            time.sleep(0.05)
        elif (result.get("reason") == "completion_unavailable"
              and not (directory / "state.json").exists()
              and time.monotonic() < startup_deadline):
            time.sleep(0.05)
        else:
            return result


def _reuse_check(repo_root: Path, directory: Path, spec: dict[str, Any]) -> dict[str, Any]:
    _closed_directory(repo_root, directory)
    # Paths and argv come from the current trusted plan/builder, never a receipt.
    current = capture_identity(**{**spec, "repo_root": repo_root})
    receipt = load_receipt(directory / "receipt.json")
    return check_reuse(receipt, current, artifacts=artifact_hashes(directory))


def run_evidence_checks(
    plan: dict[str, Any], *, repo_root: Path, directory: Path, reuse: bool,
) -> dict[str, Any]:
    """Run the exact current gates once, or validate all matching per-check proof.

The record client waits for independently supervised commands. If this client
disconnects, launched commands continue; reuse inspects their completed proof
without restarting missing or interrupted checks.
"""
    results: list[dict[str, Any]] = []
    executed = 0
    try:
        output = _closed_directory(repo_root, directory)
        if reuse:
            if not output.is_dir():
                raise ValueError("The requested verification record is unavailable.")
        elif output.exists():
            raise ValueError("The record directory already exists; inspect or reuse its evidence.")
        specs = _prepare_specs(plan, repo_root, output)
        recorded_checks = [{"check_id": check["check_id"], "command": spec["command"]}
                           for check, spec in zip(plan["checks"], specs, strict=True)]
        specs = [{**spec, "scope": {**spec["scope"], "check_id": check["check_id"],
                                   "changed_record_checks_sha256": digest(recorded_checks)}}
                 for check, spec in zip(plan["checks"], specs, strict=True)]
        if not reuse:
            output.mkdir(parents=True, exist_ok=False, mode=0o700)
            atomic_json(output / "plan.json", {
                "kind": "sciplot_changed_verification_record", "version": 1,
                "claim": "selected_checks_only", "scientific_acceptance": False,
                "comparison_provenance": plan["comparison"],
                "checks": recorded_checks,
            })
        for check, spec in zip(plan["checks"], specs, strict=True):
            check_dir = _closed_directory(repo_root, output / check["check_id"])
            if reuse:
                result = _reuse_check(repo_root, check_dir, spec)
            else:
                start_run(directory=check_dir, spec=spec)
                result = _await_original(repo_root, check_dir)
            receipt = load_receipt(check_dir / "receipt.json")
            exit_code = receipt.get("exit_code") if isinstance(receipt, dict) else None
            if not reuse and type(exit_code) is int:
                executed += 1
            results.append({
                **check, "command": spec["command"],
                "status": {"PASS": "passed", "FAIL": "failed"}.get(result["status"], result["status"]),
                "evidence_status": result["status"], "reused": result.get("reused", False),
                "reason": result.get("reason"), "exit_code": exit_code,
                "stdout": "", "stderr": "", "evidence_directory": str(check_dir),
                "receipt": str(check_dir / "receipt.json"),
                "wall_seconds": result.get("wall_seconds", result.get("original_wall_seconds")),
            })
    except (ImportError, OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        return {**plan, "status": "BLOCKED", "checks": results,
                "checks_executed": executed, "reused": False,
                "error": {"reason_code": "verification_evidence_unavailable", "message": str(exc)}}
    status = ("passed" if results and all(check["status"] == "passed" for check in results)
              else "BLOCKED" if any(check["status"] == "BLOCKED" for check in results)
              else "NO_TESTS" if any(check["status"] == "NO_TESTS" for check in results)
              else "failed")
    return {**plan, "status": status, "checks": results, "checks_executed": executed,
            "checks_reused": sum(check["reused"] for check in results),
            "reused": reuse and status == "passed",
            "evidence": {"mode": "reuse" if reuse else "record", "directory": str(output),
                         "claim": "selected_checks_only", "scientific_acceptance": False}}


def changed_record_status(directory: Path, *, repo_root: Path) -> dict[str, Any]:
    """Inspect each original recorded check; never collect, launch or claim reuse."""
    result: dict[str, Any] = {
        "kind": "sciplot_changed_verification_status", "status": "BLOCKED",
        "claim": "original_execution_only", "scientific_acceptance": False,
        "reused": False, "checks_executed": 0, "checks_reused": 0, "checks": [],
    }
    try:
        output = _closed_directory(repo_root, directory)
        result["directory"] = str(output)
        if (output / "plan.json").is_symlink():
            raise ValueError("The recorded plan cannot be a symlink.")
        plan = load_receipt(output / "plan.json")
        if (not isinstance(plan, dict) or plan.get("kind") != "sciplot_changed_verification_record"
                or type(plan.get("version")) is not int or plan["version"] != 1
                or plan.get("claim") != "selected_checks_only"
                or plan.get("scientific_acceptance") is not False or not isinstance(plan.get("checks"), list)):
            raise ValueError("A supported changed-verification record is required.")
        checks, seen = [], set()
        for check in plan["checks"]:
            if (not isinstance(check, dict) or set(check) != {"check_id", "command"}
                    or not isinstance(check["check_id"], str)
                    or not re.fullmatch("[a-z][a-z0-9_]*", check["check_id"])
                    or check["check_id"] in seen
                    or not isinstance(check["command"], list) or not check["command"]
                    or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in check["command"])):
                raise ValueError("The recorded check identity or command is malformed.")
            seen.add(check["check_id"])
            check_dir = _closed_directory(repo_root, output / check["check_id"])
            if not check_dir.exists():
                current = {"status": "NOT_STARTED", "reason": "check_not_started"}
            else:
                if (check_dir / "request.json").is_symlink():
                    raise ValueError("A recorded request cannot be a symlink.")
                request = load_receipt(check_dir / "request.json")
                if not isinstance(request, dict) or request.get("command") != check["command"]:
                    current = {"status": "BLOCKED", "reason": "recorded_command_mismatch"}
                elif (not isinstance(request.get("scope"), dict)
                      or request["scope"].get("check_id") != check["check_id"]
                      or request["scope"].get("changed_record_checks_sha256") != digest(plan["checks"])):
                    current = {"status": "BLOCKED", "reason": "recorded_plan_mismatch"}
                else:
                    current = run_status(check_dir)
            selected = current.get("selected_tests", [])
            checks.append({"check_id": check["check_id"], "status": current["status"],
                           "reason": current.get("reason"), "evidence_directory": str(check_dir),
                           "selected_test_count": len(selected), "wall_seconds": current.get("wall_seconds")})
        statuses = {check["status"] for check in checks}
        result.update(checks=checks, check_count=len(checks),
                      completed_check_count=sum(check["status"] in {"PASS", "FAIL", "NO_TESTS"} for check in checks),
                      not_started_check_ids=[check["check_id"] for check in checks if check["status"] == "NOT_STARTED"])
        if "FAIL" in statuses:
            result["status"] = "FAIL"
        elif "BLOCKED" in statuses:
            result["status"] = "BLOCKED"
        elif not statuses or "NO_TESTS" in statuses:
            result["status"] = "NO_TESTS"
        elif "RUNNING" in statuses:
            result["status"] = "RUNNING"
        elif statuses == {"PASS"}:
            result["status"] = "PASS"
        if result["not_started_check_ids"] and result["status"] == "BLOCKED":
            result["reason"] = "record_incomplete_checks_not_started"
        result["status_semantics"] = (
            "Original per-check completion only; current-snapshot reuse still requires --changed --reuse. "
            "Unstarted checks are not passed and status never resumes or repeats them.")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        result.update(status="BLOCKED", error={"reason_code": "verification_record_status_unavailable",
                                               "message": str(exc)})
    return result
