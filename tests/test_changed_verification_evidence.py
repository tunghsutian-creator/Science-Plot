"""CLI glue performs real tiny commands; reuse cannot silently repeat them."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from sciplot_core.verification import build_changed_verification_plan, run_changed_verification
from sciplot_core.verification import changed_evidence
from sciplot_core.verification.evidence_identity import DOMAINS


@pytest.fixture
def evidence_case(tmp_path, monkeypatch):
    inputs = {}
    for domain in DOMAINS:
        file = tmp_path / domain
        file.write_text(domain)
        inputs[domain] = {"paths": [str(file)]}
    counter = tmp_path / "invocations"
    command = [sys.executable, "-c", (
        "from pathlib import Path; "
        f"p=Path({str(counter)!r}); "
        "p.write_text((p.read_text() if p.exists() else '')+'once\\n')"
    )]
    plan = {"comparison": {"base": "HEAD"}, "status": "planned", "checks": [
        {"check_id": "synthetic_gate", "command": command, "status": "planned"},
    ]}

    def prepare(current_plan, root, directory):
        assert current_plan is plan and root == tmp_path
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [
                               str(Path(__file__).resolve().parents[1] / "src"), os.environ.get("PYTHONPATH", ""),
                           ])),
                           SCIPLOT_VERIFY_FINISH=str(directory / "synthetic_gate/finish.json"))
        return [{"repo_root": str(tmp_path), "command": list(command),
                 "scope": {"kind": "process", "closure_policy": "explicit glue synthetic negative controls"},
                 "selected_tests": ["synthetic_gate"], "inputs": inputs, "environment": environment,
                 "corpus": {"mode": "synthetic", "complete": True, "policy": "glue synthetic fixture"}}]

    monkeypatch.setattr(changed_evidence, "_prepare_specs", prepare)
    return tmp_path, plan, counter, inputs


def test_record_executes_once_and_matching_reuse_runs_no_command(evidence_case):
    root, plan, counter, _inputs = evidence_case
    directory = root / ".tmp_verify/recorded"
    recorded = changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=False)
    assert recorded["status"] == "passed" and recorded["checks_executed"] == 1
    assert recorded["reused"] is False and counter.read_text() == "once\n"
    assert recorded["evidence"]["scientific_acceptance"] is False
    reused = changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=True)
    assert reused["status"] == "passed" and reused["reused"] is True
    assert reused["checks_executed"] == 0 and reused["checks_reused"] == 1
    assert counter.read_text() == "once\n"
    blocked = changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=False)
    assert blocked["status"] == "BLOCKED" and blocked["checks_executed"] == 0
    assert counter.read_text() == "once\n"


@pytest.mark.parametrize("drift", ["input", "log", "missing_finish", "scope"])
def test_mismatched_reuse_is_blocked_without_automatic_retry(evidence_case, drift):
    root, plan, counter, inputs = evidence_case
    directory = root / ".tmp_verify/recorded"
    assert changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=False)["status"] == "passed"
    if drift == "input":
        Path(inputs["raw"]["paths"][0]).write_text("changed raw dependency")
    elif drift == "log":
        (directory / "synthetic_gate/command.log").write_text("artifact changed")
    elif drift == "missing_finish":
        (directory / "synthetic_gate/finish.json").unlink()
    else:
        plan["checks"][0]["command"].append("different selection contract")
    result = changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=True)
    assert result["status"] == "BLOCKED" and result["reused"] is False
    assert result["checks_executed"] == 0 and counter.read_text() == "once\n"


@pytest.mark.parametrize("outside", [True, False])
def test_evidence_path_alias_or_escape_is_rejected_before_discovery(tmp_path, monkeypatch, outside):
    external = tmp_path.parent / (tmp_path.name + "-external")
    external.mkdir()
    if outside:
        directory = external / "recorded"
    else:
        local = tmp_path / ".tmp_verify"
        local.mkdir()
        (local / "alias").symlink_to(external, target_is_directory=True)
        directory = local / "alias/recorded"
    monkeypatch.setattr(changed_evidence, "_prepare_specs", lambda *_: pytest.fail("Escaped path triggered discovery"))
    result = changed_evidence.run_evidence_checks({"checks": []}, repo_root=tmp_path, directory=directory, reuse=False)
    assert result["status"] == "BLOCKED" and result["checks_executed"] == 0
    assert list(external.iterdir()) == []


def test_unknown_corpus_closure_blocks_record_before_any_gate_or_directory(tmp_path, monkeypatch):
    def unknown(*_args):
        raise ValueError("Default corpus closure is unknown")

    monkeypatch.setattr(changed_evidence, "_prepare_specs", unknown)
    directory = tmp_path / ".tmp_verify/recorded"
    result = changed_evidence.run_evidence_checks({"checks": []}, repo_root=tmp_path, directory=directory, reuse=False)
    assert result["status"] == "BLOCKED" and result["checks_executed"] == 0
    assert not directory.exists()


def test_ordinary_verification_does_not_enter_fingerprint_or_reuse_paths(monkeypatch):
    monkeypatch.setattr(changed_evidence, "run_evidence_checks", lambda *_a, **_k: pytest.fail("Ordinary gate fingerprinted"))
    import subprocess

    result = run_changed_verification(
        repo_root=Path(__file__).resolve().parents[1], changed_paths=["README.md"],
        command_runner=lambda argv, _cwd: subprocess.CompletedProcess(argv, 0, "", ""),
    )
    assert result["status"] == "passed" and result["checks_executed"] == 2
    assert result["execution_target"] == "current_worktree"


@pytest.mark.parametrize("flag", ["--record", "--reuse"])
def test_verify_cli_passes_an_explicit_local_evidence_mode(flag, tmp_path, monkeypatch, capsys):
    from sciplot_core import cli, verification

    payload = build_changed_verification_plan([], repo_root=tmp_path)
    payload["status"] = "BLOCKED" if flag == "--reuse" else "passed"
    captured = []
    monkeypatch.setattr(verification, "run_changed_verification", lambda **kwargs: captured.append(kwargs) or payload)
    path = tmp_path / ".tmp_verify/recorded"
    assert cli.main(["verify", "--changed", flag, str(path), "--json"]) == (1 if flag == "--reuse" else 0)
    assert json.loads(capsys.readouterr().out) == payload
    assert captured == [{flag.removeprefix("--"): path}]


@pytest.mark.parametrize("arguments", [
    ["--record", ".tmp_verify/a", "--reuse", ".tmp_verify/a"],
    ["--plan-only", "--record", ".tmp_verify/a"],
    ["--plan-only", "--reuse", ".tmp_verify/a"],
])
def test_plan_record_and_reuse_are_exclusive_cli_modes(arguments):
    from sciplot_core import cli

    with pytest.raises(SystemExit) as error:
        cli._build_parser().parse_args(["verify", "--changed", *arguments])
    assert error.value.code == 2


def test_record_status_reads_original_completion_without_launch_or_reuse(evidence_case, monkeypatch):
    root, plan, counter, inputs = evidence_case
    directory = root / ".tmp_verify/recorded"
    assert changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=False)["status"] == "passed"
    Path(inputs["raw"]["paths"][0]).write_text("later input revision")
    monkeypatch.setattr(changed_evidence, "start_run", lambda **_k: pytest.fail("Status launched work"))
    monkeypatch.setattr(changed_evidence, "capture_identity", lambda **_k: pytest.fail("Status claimed fresh reuse"))
    status = changed_evidence.changed_record_status(directory, repo_root=root)
    assert status["status"] == "PASS" and status["claim"] == "original_execution_only"
    assert status["check_count"] == status["completed_check_count"] == 1
    assert status["checks_executed"] == status["checks_reused"] == 0
    assert status["reused"] is False and status["scientific_acceptance"] is False
    assert counter.read_text() == "once\n"


def test_disconnected_record_reports_unstarted_checks_without_replaying(evidence_case, monkeypatch, capsys):
    root, plan, counter, _ = evidence_case
    directory = root / ".tmp_verify/interrupted-client"
    plan["checks"].append({**plan["checks"][0], "check_id": "unstarted_gate"})
    prepare = changed_evidence._prepare_specs
    monkeypatch.setattr(changed_evidence, "_prepare_specs", lambda *args: prepare(*args) * 2)
    wait = changed_evidence._await_original

    def disconnect(*args):
        assert wait(*args)["status"] == "PASS"
        raise ConnectionError("record client disconnected after the original completed")

    monkeypatch.setattr(changed_evidence, "_await_original", disconnect)
    assert changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=False)["status"] == "BLOCKED"
    status = changed_evidence.changed_record_status(directory, repo_root=root)
    assert status["status"] == "BLOCKED" and status["completed_check_count"] == 1
    assert status["not_started_check_ids"] == ["unstarted_gate"]
    assert [check["status"] for check in status["checks"]] == ["PASS", "NOT_STARTED"]
    assert not (directory / "unstarted_gate").exists() and counter.read_text() == "once\n"
    from sciplot_core import cli

    monkeypatch.setenv("SCIPLOT_REPO", str(root))
    assert cli.main(["verify", "--status", str(directory)]) == 1
    display = capsys.readouterr().out
    assert "Checks completed: 1/2" in display and "unstarted_gate: NOT_STARTED" in display
    assert "record_incomplete_checks_not_started" in display
    import shutil

    shutil.copytree(directory / "synthetic_gate", directory / "unstarted_gate")
    copied = changed_evidence.changed_record_status(directory, repo_root=root)
    assert copied["status"] == "BLOCKED" and copied["checks"][1]["reason"] == "recorded_plan_mismatch"
    saved = json.loads((directory / "plan.json").read_text())
    saved["checks"].pop()
    (directory / "plan.json").write_text(json.dumps(saved))
    changed = changed_evidence.changed_record_status(directory, repo_root=root)
    assert changed["status"] == "BLOCKED" and changed["checks"][0]["reason"] == "recorded_plan_mismatch"
    assert counter.read_text() == "once\n"


def test_record_status_follows_running_original_after_client_disconnect(evidence_case, monkeypatch):
    root, plan, counter, _ = evidence_case
    directory = root / ".tmp_verify/running-original"
    plan["checks"][0]["command"][-1] += "; import time; time.sleep(.8)"
    wait = changed_evidence._await_original

    def disconnect(*_args):
        raise ConnectionError("client disconnected while the supervisor continues")

    monkeypatch.setattr(changed_evidence, "_await_original", disconnect)
    assert changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=False)["status"] == "BLOCKED"
    running = changed_evidence.changed_record_status(directory, repo_root=root)
    assert running["status"] == "RUNNING" and running["completed_check_count"] == 0
    assert wait(root, directory / "synthetic_gate")["status"] == "PASS"
    assert changed_evidence.changed_record_status(directory, repo_root=root)["status"] == "PASS"
    assert counter.read_text() == "once\n"


def test_record_status_preserves_actual_failed_original(evidence_case):
    root, plan, counter, _ = evidence_case
    plan["checks"][0]["command"][-1] += "; raise SystemExit(1)"
    directory = root / ".tmp_verify/failed-original"
    assert changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=False)["status"] == "failed"
    status = changed_evidence.changed_record_status(directory, repo_root=root)
    assert status["status"] == "FAIL" and status["completed_check_count"] == 1
    assert counter.read_text() == "once\n"


@pytest.mark.parametrize("drift", ["log", "finish", "command", "alias", "check_alias", "request_alias", "duplicate", "escape", "version", "unbound"])
def test_record_status_rejects_drift_and_aliases_without_running(evidence_case, drift):
    root, plan, counter, _ = evidence_case
    directory = root / ".tmp_verify/recorded"
    assert changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=False)["status"] == "passed"
    metadata = directory / "plan.json"
    saved = json.loads(metadata.read_text())
    if drift == "log":
        (directory / "synthetic_gate/command.log").write_text("drift")
    elif drift == "finish":
        (directory / "synthetic_gate/finish.json").unlink()
    elif drift == "alias":
        metadata.rename(root / "external-plan.json")
        metadata.symlink_to(root / "external-plan.json")
    elif drift == "check_alias":
        (directory / "synthetic_gate").rename(root / "external-check")
        (directory / "synthetic_gate").symlink_to(root / "external-check", target_is_directory=True)
    elif drift == "request_alias":
        request = directory / "synthetic_gate/request.json"
        request.rename(root / "external-request.json")
        request.symlink_to(root / "external-request.json")
    elif drift == "unbound":
        request = directory / "synthetic_gate/request.json"
        payload = json.loads(request.read_text())
        payload["scope"].pop("changed_record_checks_sha256")
        request.write_text(json.dumps(payload))
    else:
        if drift == "command":
            saved["checks"][0]["command"].append("another command")
        elif drift == "duplicate":
            saved["checks"].append(saved["checks"][0])
        elif drift == "version":
            saved["version"] = True
        else:
            saved["checks"][0]["check_id"] = "../external"
        metadata.write_text(json.dumps(saved))
    status = changed_evidence.changed_record_status(directory, repo_root=root)
    assert status["status"] == "BLOCKED" and status["checks_executed"] == 0
    assert counter.read_text() == "once\n"


def test_record_status_uses_the_existing_public_status_entry(evidence_case, monkeypatch, capsys):
    from sciplot_core import cli

    root, plan, counter, _ = evidence_case
    directory = root / ".tmp_verify/recorded"
    assert changed_evidence.run_evidence_checks(plan, repo_root=root, directory=directory, reuse=False)["status"] == "passed"
    monkeypatch.setenv("SCIPLOT_REPO", str(root))
    assert cli.main(["verify", "--status", str(directory), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["kind"] == "sciplot_changed_verification_status" and status["status"] == "PASS"
    assert status["checks_executed"] == 0 and counter.read_text() == "once\n"
    assert cli.main(["verify", "--status", str(directory)]) == 0
    display = capsys.readouterr().out
    assert "Checks completed: 1/1" in display and "synthetic_gate: PASS" in display
    assert "original_execution_only" in display and counter.read_text() == "once\n"


def test_empty_record_is_no_tests_with_nonzero_public_exit(tmp_path, monkeypatch, capsys):
    from sciplot_core import cli

    directory = tmp_path / ".tmp_verify/empty"
    directory.mkdir(parents=True)
    (directory / "plan.json").write_text(json.dumps({
        "kind": "sciplot_changed_verification_record", "version": 1,
        "claim": "selected_checks_only", "scientific_acceptance": False, "checks": [],
    }))
    monkeypatch.setenv("SCIPLOT_REPO", str(tmp_path))
    assert cli.main(["verify", "--status", str(directory), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NO_TESTS"
