"""Tiny synthetic subprocesses verify transport-independent gate completion."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.verification.durable_runner import run_status, start_run, supervise
from sciplot_core.verification.evidence import atomic_json, load_receipt
from sciplot_core.verification.evidence_identity import DOMAINS, digest


@pytest.fixture
def run_spec(tmp_path):
    inputs = {}
    for domain in DOMAINS:
        path = tmp_path / domain
        path.write_text(domain)
        inputs[domain] = {"paths": [str(path)]}
    source = Path(__file__).resolve().parents[1] / "src"
    env = dict(os.environ, PYTHONPATH=str(source), SCIPLOT_TEST_SECRET="not-to-persist")
    return dict(repo_root=str(tmp_path), command=[sys.executable, "-c", "print('completed gate')"],
                scope={"kind": "process", "closure_policy": "synthetic runner self-test"},
                selected_tests=["synthetic:process-completion"], inputs=inputs, environment=env,
                corpus={"mode": "synthetic", "complete": True, "policy": "runner synthetic test"})


def await_completion(directory):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = load_receipt(directory / "state.json")
        if isinstance(state, dict) and state.get("phase") in {"completed", "blocked"}:
            return run_status(directory)
        time.sleep(0.05)
    pytest.fail("synthetic supervisor did not finish within 20 seconds")


def test_detached_completion_survives_launch_process_exit(run_spec):
    root = Path(run_spec["repo_root"])
    directory = root / ".tmp_verify" / "detached"
    # The temporary launching client exits immediately, emulating tool transport
    # loss. Only the independently sessioned supervisor waits for the command.
    spec_file = root / "launch-spec.json"
    run_spec["command"] = [sys.executable, "-c", "import time; time.sleep(.2); print('one execution')"]
    spec_file.write_text(json.dumps(run_spec))
    code = ("import json; from pathlib import Path; "
            "from sciplot_core.verification.durable_runner import start_run; "
            f"start_run(directory=Path({str(directory)!r}), spec=json.loads(Path({str(spec_file)!r}).read_text()))")
    completed = subprocess.run([sys.executable, "-c", code], env=run_spec["environment"], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    result = await_completion(directory)
    assert result["status"] == "PASS", (result, (directory / "supervisor.log").read_text())
    assert result["reused"] is False and result["wall_seconds"] >= 0.2
    assert (directory / "command.log").read_text().count("one execution") == 1
    with pytest.raises(FileExistsError):
        start_run(directory=directory, spec=run_spec)
    assert run_status(directory)["status"] == "PASS"
    assert "not-to-persist" not in (directory / "request.json").read_text()
    assert "SCIPLOT_TEST_SECRET" not in (directory / "receipt.json").read_text()
    (directory / "command.log").write_text("tampered")
    assert run_status(directory)["status"] == "BLOCKED"


def test_command_failure_is_not_pass(run_spec):
    run_spec["command"] = [sys.executable, "-c", "raise SystemExit(7)"]
    directory = Path(run_spec["repo_root"]) / ".tmp_verify" / "failed"
    start_run(directory=directory, spec=run_spec)
    assert await_completion(directory)["status"] == "FAIL"


@pytest.mark.parametrize("body,selected,status", [
    ("def test_ok(): assert True", ["test_synthetic.py::test_ok"], "PASS"),
    ("import pytest\ndef test_ok(): pytest.skip('test negative control')", ["test_synthetic.py::test_ok"], "BLOCKED"),
    ("# no tests", [], "NO_TESTS"),
])
def test_real_pytest_sessionfinish_and_exact_body_completion(run_spec, body, selected, status):
    root = Path(run_spec["repo_root"])
    (root / "test_synthetic.py").write_text(body)
    run_spec["command"] = [sys.executable, "-m", "pytest", "-q", "-p",
                           "sciplot_core.verification.pytest_finish", "test_synthetic.py"]
    run_spec["scope"]["kind"] = "pytest"
    run_spec["selected_tests"] = selected
    run_spec["inputs"]["tests"]["paths"].append(str(root / "test_synthetic.py"))
    directory = root / ".tmp_verify" / "pytest"
    start_run(directory=directory, spec=run_spec)
    result = await_completion(directory)
    assert result["status"] == status, (result, (directory / "command.log").read_text())


def test_missing_finish_cannot_be_promoted(run_spec):
    # A command can exit 0 without actually starting pytest; the declared plugin
    # argv alone must not suffice to mint session completion.
    run_spec["command"] = [sys.executable, "-c", "pass", "-p", "sciplot_core.verification.pytest_finish"]
    run_spec["scope"]["kind"] = "pytest"
    directory = Path(run_spec["repo_root"]) / ".tmp_verify" / "unfinished"
    start_run(directory=directory, spec=run_spec)
    assert await_completion(directory)["reason"] == "session_finish_missing"


def test_input_drift_during_process_is_blocked(run_spec):
    target = run_spec["inputs"]["raw"]["paths"][0]
    run_spec["command"] = [sys.executable, "-c", f"from pathlib import Path; Path({target!r}).write_text('changed')"]
    directory = Path(run_spec["repo_root"]) / ".tmp_verify" / "drift"
    start_run(directory=directory, spec=run_spec)
    assert await_completion(directory)["reason"] == "input_drift"


def test_abrupt_pytest_process_exit_has_no_session_finish(run_spec):
    root = Path(run_spec["repo_root"])
    (root / "test_abrupt.py").write_text("def test_abrupt():\n    import os\n    os._exit(0)\n")
    run_spec["command"] = [sys.executable, "-m", "pytest", "-q", "-p",
                           "sciplot_core.verification.pytest_finish", "test_abrupt.py"]
    run_spec["scope"]["kind"] = "pytest"
    run_spec["selected_tests"] = ["test_abrupt.py::test_abrupt"]
    directory = root / ".tmp_verify" / "abrupt"
    start_run(directory=directory, spec=run_spec)
    assert await_completion(directory)["reason"] == "session_finish_missing"


def test_artifact_recursion_and_nonlocal_destinations_refused(run_spec):
    root = Path(run_spec["repo_root"])
    with pytest.raises(ValueError, match="tmp_verify"):
        start_run(directory=root / "public-evidence", spec=run_spec)
    run_spec["inputs"]["implementation"] = {"paths": [str(root)]}
    with pytest.raises(ValueError, match="overlap"):
        start_run(directory=root / ".tmp_verify" / "circular", spec=run_spec)


def test_missing_completion_and_dead_supervisor_fail_closed(tmp_path):
    atomic_json(tmp_path / "state.json", {"phase": "running", "supervisor_pid": 2147483647})
    assert run_status(tmp_path)["reason"] == "supervisor_interrupted"
    atomic_json(tmp_path / "state.json", {"phase": "completed", "receipt_digest": digest({})})
    assert run_status(tmp_path)["reason"] == "receipt_drift"


def test_supervisor_environment_drift_blocks_before_command(run_spec, monkeypatch):
    directory = Path(run_spec["repo_root"]) / ".tmp_verify" / "env-drift"
    directory.mkdir(parents=True)
    environment = run_spec.pop("environment")
    run_spec["environment_sha256"] = digest(environment)
    atomic_json(directory / "request.json", run_spec)
    monkeypatch.setenv("SCIPLOT_TEST_SECRET", "different")
    assert supervise(directory, file_sha256(directory / "request.json")) == 1
    assert run_status(directory)["status"] == "BLOCKED"
    assert not (directory / "command.log").exists()


def test_status_between_launch_and_first_state_is_running_only(tmp_path, monkeypatch):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.verification.evidence import atomic_json
    from sciplot_core.verification import durable_runner
    request = tmp_path / "request.json"
    request.write_text("{}")
    atomic_json(tmp_path / "launch.json", {"supervisor_pid": 123, "request_sha256": file_sha256(request)})
    monkeypatch.setattr(durable_runner.os, "kill", lambda *args: None)
    result = durable_runner.run_status(tmp_path)
    assert result["status"] == "RUNNING" and result["reused"] is False
    request.write_text("changed")
    assert durable_runner.run_status(tmp_path)["status"] == "BLOCKED"
