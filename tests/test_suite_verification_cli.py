"""Known suite entry points start once; status never replays execution."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import types

import pytest

from sciplot_core.verification import suite_evidence
from sciplot_core.verification.evidence_identity import DOMAINS


@pytest.fixture
def suite_case(tmp_path, monkeypatch):
    inputs = {}
    for domain in DOMAINS:
        path = tmp_path / domain
        path.write_text(domain)
        inputs[domain] = {"paths": [str(path)]}
    counter = tmp_path / "invocations"
    commands = []

    def builder(plan, check, root, *, environment, finish_path):
        assert root == tmp_path and finish_path.name == "finish.json"
        assert check in plan["checks"] and check["check_id"] == f"pytest_{plan['suite']}"
        commands.append(check["command"])
        environment = {**environment, "PYTHONPATH": os.pathsep.join(filter(None, [
            str(Path(__file__).resolve().parents[1] / "src"), environment.get("PYTHONPATH", ""),
        ]))}
        command = [sys.executable, "-c", (
            "from pathlib import Path; import time; "
            f"p=Path({str(counter)!r}); "
            "p.write_text((p.read_text() if p.exists() else '')+'once\\n'); time.sleep(.1)"
        )]
        return {"repo_root": str(root), "command": command,
                "scope": {"kind": "process", "closure_policy": "explicit isolated CLI test fixture",
                          "check_id": check["check_id"]},
                "selected_tests": ["isolated_tiny_process"], "inputs": inputs,
                "environment": environment,
                "corpus": {"mode": "synthetic", "complete": True, "policy": "test-only fixture"}}

    module = types.ModuleType("sciplot_core.verification.evidence_scope")
    module.build_check_spec = builder
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return tmp_path, counter, commands


def test_suite_starts_once_and_status_reads_original_proof_without_replay(suite_case):
    root, counter, commands = suite_case
    directory = root / ".tmp_verify/one-original-run"
    started = suite_evidence.start_suite_verification("focused", directory=directory, repo_root=root)
    assert started["status"] == "RUNNING" and started["claim"] == "execution_started_only"
    assert started["selected_test_count"] == 1 and started["scientific_acceptance"] is False
    assert commands == [[sys.executable, "-m", "pytest", "-q", "-m", "focused"]]
    assert suite_evidence.start_suite_verification("focused", directory=directory, repo_root=root)["status"] == "BLOCKED"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = suite_evidence.suite_verification_status(directory, repo_root=root)
        if status["status"] == "PASS":
            break
        time.sleep(.02)
    assert status["status"] == "PASS" and status["claim"] == "original_execution_only"
    assert status["selected_test_count"] == 1 and status["reused"] is False
    assert status["scientific_acceptance"] is False and "selected_tests" not in status
    assert counter.read_text() == "once\n" and len(commands) == 1
    (directory / "command.log").write_text("drifted original evidence")
    assert suite_evidence.suite_verification_status(directory, repo_root=root)["status"] == "BLOCKED"
    assert counter.read_text() == "once\n" and len(commands) == 1


@pytest.mark.parametrize("suite,marker", [("focused", "focused"), ("comprehensive", "comprehensive"), ("full", None)])
def test_suite_profile_selects_only_the_known_command(suite_case, monkeypatch, suite, marker):
    root, _counter, commands = suite_case
    monkeypatch.setattr(suite_evidence, "start_run", lambda **_kwargs: {"status": "RUNNING"})
    result = suite_evidence.start_suite_verification(suite, directory=Path(".tmp_verify/profile"), repo_root=root)
    assert result["status"] == "RUNNING"
    assert commands == [[sys.executable, "-m", "pytest", "-q", *(["-m", marker] if marker else [])]]


@pytest.mark.parametrize("configured_raw", [None, "~/sciplot-test-private-data", "relative-private-data"])
def test_frozen_audit_attachment_binds_plugins_and_separate_outputs(suite_case, monkeypatch, configured_raw):
    root, _counter, _commands = suite_case
    plugin = root / ".tmp_verify/frozen-audit-plugin"
    plugin.mkdir(parents=True)
    for name in ("sitecustomize.py", "sciplot_closure_audit.py"):
        (plugin / name).write_text("# read-only test fixture\n")
    captured = []
    if configured_raw is None:
        monkeypatch.delenv("SCIPLOT_REFERENCE_DATA", raising=False)
    else:
        monkeypatch.setenv("SCIPLOT_REFERENCE_DATA", configured_raw)
    monkeypatch.setattr(suite_evidence, "start_run", lambda **kwargs: captured.append(kwargs) or {"status": "RUNNING"})
    audit = root / ".tmp_verify/observations"
    result = suite_evidence.start_suite_verification("full", directory=Path(".tmp_verify/full"), repo_root=root,
                                                      audit_plugin_dir=plugin, audit_out=audit)
    assert result["status"] == "RUNNING" and audit.is_dir()
    environment = captured[0]["spec"]["environment"]
    assert str(plugin) in environment["PYTHONPATH"].split(os.pathsep)
    assert "sciplot_closure_audit" in environment["PYTEST_PLUGINS"].split(",")
    assert environment["SCIPLOT_PRIVATE_AUDIT_DIR"] == str(audit)
    raw = Path(configured_raw).expanduser() if configured_raw else root / ".local/reference_data"
    raw = (raw if raw.is_absolute() else root / raw).resolve()
    assert json.loads(environment["SCIPLOT_PRIVATE_AUDIT_ROOTS"]) == [str(root / "tests/fixtures"), str(raw)]
    assert result["scientific_acceptance"] is False


@pytest.mark.parametrize("invalid", ["unknown_suite", "outside", "same_audit_output", "unpaired_audit", "input_audit_output"])
def test_invalid_suite_or_output_is_blocked_before_start(suite_case, monkeypatch, invalid):
    root, counter, commands = suite_case
    monkeypatch.setattr(suite_evidence, "start_run", lambda **_kwargs: pytest.fail("Invalid scope started a child"))
    kwargs = {"directory": root / ".tmp_verify/run", "repo_root": root}
    suite = "full"
    if invalid == "unknown_suite":
        suite = "unchecked_custom_command"
    elif invalid == "outside":
        kwargs["directory"] = root.parent / "outside"
    else:
        plugin = root / ".tmp_verify/plugin"
        plugin.mkdir(parents=True)
        for name in ("sitecustomize.py", "sciplot_closure_audit.py"):
            (plugin / name).write_text("# frozen plugin\n")
        kwargs["audit_plugin_dir"] = plugin
        if invalid == "same_audit_output":
            kwargs["audit_out"] = kwargs["directory"]
        elif invalid == "input_audit_output":
            kwargs["audit_out"] = plugin / "output"
    result = suite_evidence.start_suite_verification(suite, **kwargs)
    assert result["status"] == "BLOCKED" and result["scientific_acceptance"] is False
    assert not commands and not counter.exists()


@pytest.mark.parametrize("addopts", ["-k only_one_case", "-m focused", "--ignore=tests/test_private.py"])
def test_fixed_suite_rejects_inherited_filter_without_clearing_it(suite_case, monkeypatch, addopts):
    root, counter, commands = suite_case
    monkeypatch.setenv("PYTEST_ADDOPTS", addopts)
    monkeypatch.setattr(suite_evidence, "start_run", lambda **_kwargs: pytest.fail("Filtered suite started"))
    result = suite_evidence.start_suite_verification("full", directory=Path(".tmp_verify/full"), repo_root=root)
    assert result["status"] == "BLOCKED" and "PYTEST_ADDOPTS" in result["error"]["message"]
    assert os.environ["PYTEST_ADDOPTS"] == addopts
    assert not commands and not counter.exists()


@pytest.mark.parametrize("arguments", [
    ["--changed", "--start", "full"], ["--status", ".tmp_verify/run", "--start", "full"],
])
def test_suite_scope_and_changed_are_exclusive_parser_modes(arguments):
    from sciplot_core import cli

    with pytest.raises(SystemExit) as error:
        cli._build_parser().parse_args(["verify", *arguments])
    assert error.value.code == 2


@pytest.mark.parametrize("arguments", [
    ["--start", "full"], ["--status", ".tmp_verify/run", "--out", ".tmp_verify/other"],
    ["--start", "full", "--out", ".tmp_verify/run", "--reuse", ".tmp_verify/old"],
    ["--changed", "--out", ".tmp_verify/run"],
])
def test_foreign_mode_options_are_blocked_without_any_execution(arguments, monkeypatch, capsys):
    from sciplot_core import cli, verification

    monkeypatch.setattr(suite_evidence, "start_suite_verification", lambda *_a, **_k: pytest.fail("Invalid mode started"))
    monkeypatch.setattr(suite_evidence, "suite_verification_status", lambda *_a, **_k: pytest.fail("Invalid mode inspected"))
    monkeypatch.setattr(verification, "run_changed_verification", lambda **_k: pytest.fail("Invalid mode ran checks"))
    assert cli.main(["verify", *arguments, "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["reason_code"] == "invalid_verification_mode"


@pytest.mark.parametrize("status,code", [("RUNNING", 0), ("PASS", 0), ("FAIL", 1), ("BLOCKED", 1), ("NO_TESTS", 2)])
def test_status_cli_returns_only_original_completion_projection(status, code, monkeypatch, capsys):
    from sciplot_core import cli

    captured = []
    monkeypatch.setattr(suite_evidence, "suite_verification_status", lambda directory: captured.append(directory) or {
        "status": status, "claim": "original_execution_only", "scientific_acceptance": False,
    })
    assert cli.main(["verify", "--status", ".tmp_verify/run", "--json"]) == code
    assert captured == [Path(".tmp_verify/run")]
    assert json.loads(capsys.readouterr().out)["claim"] == "original_execution_only"
