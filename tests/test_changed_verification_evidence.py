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
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
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
