"""Tiny synthetic subprocesses verify transport-independent gate completion."""
from __future__ import annotations

import errno
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
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(source), os.environ.get("PYTHONPATH", ""))),
               SCIPLOT_TEST_SECRET="not-to-persist")
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
    code = ("import json, os; from pathlib import Path; "
            "from sciplot_core.verification.durable_runner import start_run; "
            f"spec=json.loads(Path({str(spec_file)!r}).read_text()); "
            "spec['environment']=dict(os.environ); "
            f"start_run(directory=Path({str(directory)!r}), spec=spec)")
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
    run_spec["command"] = [sys.executable, "-m", "pytest", "--rootdir", str(root), "--confcutdir", str(root), "-q", "-p",
                           "sciplot_core.verification.pytest_finish", "test_synthetic.py"]
    run_spec["scope"]["kind"] = "pytest"
    run_spec["selected_tests"] = selected
    run_spec["inputs"]["tests"]["paths"].append(str(root / "test_synthetic.py"))
    directory = root / ".tmp_verify" / "pytest"
    start_run(directory=directory, spec=run_spec)
    result = await_completion(directory)
    assert result["status"] == status, (result, (directory / "command.log").read_text())
    assert result["reason"] == {"PASS": "completed", "BLOCKED": "execution_incomplete", "NO_TESTS": "empty_selection"}[status]
    finish = json.loads((directory / "finish.json").read_text())
    assert finish["selected_tests"] == selected
    assert finish["executed_tests"] == (selected if status == "PASS" else [])


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
    run_spec["command"] = [sys.executable, "-m", "pytest", "--rootdir", str(root), "--confcutdir", str(root), "-q", "-p",
                           "sciplot_core.verification.pytest_finish", "test_abrupt.py"]
    run_spec["scope"]["kind"] = "pytest"
    run_spec["selected_tests"] = ["test_abrupt.py::test_abrupt"]
    directory = root / ".tmp_verify" / "abrupt"
    start_run(directory=directory, spec=run_spec)
    assert await_completion(directory)["reason"] == "session_finish_missing"
    original_finish = (directory / "finish.json").read_bytes()
    progress = json.loads((directory / "pytest-progress.json").read_bytes())
    progress.update(latest_phase="session_finish", completed=1, passed=1, updated_at=time.time(), written_at=time.time(),
                    updated_monotonic=time.monotonic(), written_monotonic=time.monotonic())
    (directory / "pytest-progress.json").write_text(json.dumps(progress))
    forged = run_status(directory)
    assert forged["reason"] == "session_finish_missing" and forged["progress"]["pytest"]["available"]
    assert (directory / "finish.json").read_bytes() == original_finish


def test_artifact_recursion_and_nonlocal_destinations_refused(run_spec):
    root = Path(run_spec["repo_root"])
    with pytest.raises(ValueError, match="tmp_verify"):
        start_run(directory=root / "public-evidence", spec=run_spec)
    run_spec["inputs"]["implementation"] = {"paths": [str(root)]}
    with pytest.raises(ValueError, match="overlap"):
        start_run(directory=root / ".tmp_verify" / "circular", spec=run_spec)


def test_missing_completion_and_dead_supervisor_fail_closed(tmp_path, monkeypatch):
    from sciplot_core.verification import durable_runner

    atomic_json(tmp_path / "state.json", {"phase": "running", "supervisor_pid": 2147483647})

    def no_launch_or_write(*_args, **_kwargs):
        pytest.fail("Status cannot relaunch a command or write its original evidence")

    def absent(pid, signal):
        assert (pid, signal) == (2147483647, 0)
        raise ProcessLookupError(errno.ESRCH, "synthetic missing supervisor")

    monkeypatch.setattr(durable_runner.subprocess, "Popen", no_launch_or_write)
    monkeypatch.setattr(durable_runner, "atomic_json", no_launch_or_write)
    monkeypatch.setattr(durable_runner.os, "kill", absent)
    assert run_status(tmp_path)["reason"] == "supervisor_interrupted"
    original = (tmp_path / "state.json").read_bytes()
    for error in (PermissionError(errno.EPERM, "synthetic denied observation"),
                  PermissionError(errno.EACCES, "synthetic denied observation"),
                  OSError(errno.EINTR, "synthetic interrupted observation"),
                  OSError(errno.EIO, "synthetic unavailable observation")):
        def unavailable(pid, signal, failure=error):
            assert (pid, signal) == (2147483647, 0)
            raise failure
        monkeypatch.setattr(durable_runner.os, "kill", unavailable)
        result = run_status(tmp_path)
        assert result == {"status": "BLOCKED", "reused": False, "reason": "supervisor_observation_unavailable",
                          "supervisor_pid": 2147483647, "directory": str(tmp_path)}
        assert (tmp_path / "state.json").read_bytes() == original
        assert sorted(path.name for path in tmp_path.iterdir()) == ["state.json"]
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


def test_public_prepare_and_reuse_bind_the_same_actual_environment(run_spec, monkeypatch):
    from types import SimpleNamespace
    from sciplot_core.verification import changed_evidence, private_exclusion_boundary as boundary, private_observer
    from sciplot_core.verification.durable_runner import _capture, artifact_hashes, prepare_run
    from sciplot_core.verification.evidence import make_receipt

    root = Path(run_spec["repo_root"])
    directory = root / ".tmp_verify" / "pure-environment-contract"
    roots = json.dumps(boundary.watch_roots(boundary.REPO, {}))
    observer = SimpleNamespace(directory=root / "generated-audit", run="generated-run",
        wrapper_environment={private_observer.ROOTS: roots},
        root_scope=boundary.root_scope(boundary.watch_roots(boundary.REPO, {})),
        _exclusion_phase={"sha256": "generated-source-bound-phase"}, epoch="generated-parent", reserved={})
    environment = run_spec["environment"]
    environment.update({key: "generated-routing" for key in private_observer.AUDIT_KEYS})
    environment.pop(private_observer.CONTINUATION)
    environment.update({private_observer.DIRECTORY: str(observer.directory), private_observer.RUN: observer.run,
                        private_observer.ROOTS: roots,
                        "SCIPLOT_VERIFY_FINISH": str(directory / "finish.json")})
    monkeypatch.setattr(private_observer, "current_observer", lambda: observer)
    _, effective, _ = prepare_run(directory=directory, spec=run_spec)
    request = load_receipt(directory / "request.json")
    assert request["environment_sha256"] == digest(effective)
    assert not set(private_observer.AUDIT_KEYS) & effective.keys() and observer.reserved == {}
    before = _capture(request, effective)
    # Generated receipt inputs test comparison only; no process execution is claimed.
    finish = {"complete": True, "exit_code": 0, "selected_tests": run_spec["selected_tests"]}
    (directory / "command.log").write_text("generated comparison fixture, no command executed\n")
    atomic_json(directory / "finish.json", finish)
    atomic_json(directory / "completion.json", {"generated_comparison_only": True})
    receipt = make_receipt(before=before, after=before, exit_code=0, session_finish=finish,
                           wall_seconds=0, artifacts=artifact_hashes(directory))
    atomic_json(directory / "receipt.json", receipt)
    assert changed_evidence._reuse_check(root, directory, run_spec)["status"] == "PASS"
    assert observer.reserved == {}
    environment["SCIPLOT_TEST_SECRET"] += "-drift"
    assert changed_evidence._reuse_check(root, directory, run_spec)["status"] == "BLOCKED"
    environment["SCIPLOT_TEST_SECRET"] = effective["SCIPLOT_TEST_SECRET"]
    for changed_roots in (roots + " ", None):
        if changed_roots is None:
            environment.pop(private_observer.ROOTS)
        else:
            environment[private_observer.ROOTS] = changed_roots
        with pytest.raises(ValueError, match="requested audit roots differ"):
            changed_evidence._reuse_check(root, directory, run_spec)
        refused = root / ".tmp_verify" / ("missing-roots" if changed_roots is None else "changed-roots")
        with pytest.raises(ValueError, match="requested audit roots differ"):
            prepare_run(directory=refused, spec=run_spec)
        assert not refused.exists() and observer.reserved == {}
    environment[private_observer.ROOTS] = roots
    environment[private_observer.CONTINUATION] = "generated-exec-predecessor"
    with pytest.raises(ValueError, match="exec continuation"):
        changed_evidence._reuse_check(root, directory, run_spec)
    refused = root / ".tmp_verify" / "stale-continuation"
    with pytest.raises(ValueError, match="exec continuation"):
        prepare_run(directory=refused, spec=run_spec)
    assert not refused.exists() and observer.reserved == {}


def test_status_between_launch_and_first_state_is_running_only(tmp_path, monkeypatch):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.verification.evidence import atomic_json
    from sciplot_core.verification import durable_runner
    request = tmp_path / "request.json"
    request.write_text("{}")
    atomic_json(tmp_path / "launch.json", {"supervisor_pid": 123, "request_sha256": file_sha256(request)})

    def no_launch_or_write(*_args, **_kwargs):
        pytest.fail("Status cannot relaunch a command or write its original evidence")

    monkeypatch.setattr(durable_runner.subprocess, "Popen", no_launch_or_write)
    monkeypatch.setattr(durable_runner, "atomic_json", no_launch_or_write)
    monkeypatch.setattr(durable_runner.os, "kill", lambda *args: None)
    result = durable_runner.run_status(tmp_path)
    assert result["status"] == "RUNNING" and result["reused"] is False
    original = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    for error in (PermissionError(errno.EPERM, "synthetic denied startup observation"),
                  PermissionError(errno.EACCES, "synthetic denied startup observation"),
                  OSError(errno.EINTR, "synthetic interrupted startup observation"),
                  ProcessLookupError(errno.ESRCH, "synthetic absent startup supervisor")):
        def unavailable(pid, signal, failure=error):
            assert (pid, signal) == (123, 0)
            raise failure
        monkeypatch.setattr(durable_runner.os, "kill", unavailable)
        result = durable_runner.run_status(tmp_path)
        if isinstance(error, ProcessLookupError):
            assert result["reason"] == "completion_unavailable"
        else:
            assert result == {"status": "BLOCKED", "reused": False, "reason": "supervisor_observation_unavailable",
                              "supervisor_pid": 123, "directory": str(tmp_path)}
        assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == original
    request.write_text("changed")
    assert durable_runner.run_status(tmp_path)["status"] == "BLOCKED"


@pytest.mark.parametrize("field", ["child_pid", "supervisor_pid"])
def test_progress_pid_cannot_replace_sealed_original_wait(run_spec, field):
    directory = Path(run_spec["repo_root"]) / ".tmp_verify/sealed-wait"
    launched = start_run(directory=directory, spec=run_spec)
    assert await_completion(directory)["status"] == "PASS"
    original = (directory / "completion.json").read_bytes()
    completion = json.loads(original)
    assert completion["supervisor_pid"] == launched["supervisor_pid"]
    state = json.loads((directory / "state.json").read_bytes())
    assert all(state[key] == completion[key] for key in ("child_pid", "supervisor_pid"))
    state[field] += 1
    (directory / "state.json").write_text(json.dumps(state))
    assert (directory / "completion.json").read_bytes() == original
    assert run_status(directory)["status"] == "BLOCKED"


def _pytest_spec(run_spec, body):
    root = Path(run_spec["repo_root"])
    source = root / "test_progress.py"
    source.write_text(body)
    run_spec["command"] = [sys.executable, "-m", "pytest", "--rootdir", str(root), "--confcutdir", str(root),
                           "-q", "-s", "-p", "sciplot_core.verification.pytest_finish", source.name]
    run_spec["scope"]["kind"] = "pytest"
    run_spec["selected_tests"] = [source.name + "::test_live"]
    run_spec["inputs"]["tests"]["paths"].append(str(source))
    return root / ".tmp_verify/progress"


def test_running_progress_exposes_actual_node_and_log_growth(run_spec):
    from sciplot_core.verification.changed_evidence import changed_record_status

    _pytest_spec(run_spec, "def test_live():\n import time\n print('actual body started',flush=True)\n time.sleep(1.5)\n")
    record = Path(run_spec["repo_root"]) / ".tmp_verify/live-record"
    directory = record / "pytest_live"
    checks = [{"check_id": "pytest_live", "command": run_spec["command"]}]
    run_spec["scope"].update(check_id="pytest_live", changed_record_checks_sha256=digest(checks))
    record.mkdir(parents=True)
    atomic_json(record / "plan.json", {"kind": "sciplot_changed_verification_record", "version": 1,
        "claim": "selected_checks_only", "scientific_acceptance": False, "checks": checks})
    start_run(directory=directory, spec=run_spec)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = run_status(directory)
        progress = result.get("progress", {})
        if (progress.get("pytest", {}).get("latest_phase") == "call"
                and progress.get("log", {}).get("growth_since_checkpoint_bytes", 0) > 0):
            break
        time.sleep(.01)
    else:
        pytest.fail(f"actual running node was not visible: {result}")
    assert result["status"] == "RUNNING"
    actual = progress["pytest"]
    assert actual["latest_node"] == run_spec["selected_tests"][0]
    assert actual["pid"] == load_receipt(directory / "state.json")["child_pid"]
    assert actual["completed"] == actual["passed"] == actual["failed"] == 0
    assert actual["request_sha256"] == file_sha256(directory / "request.json")
    assert actual["update_age_seconds"] >= 0
    projected = changed_record_status(record, repo_root=Path(run_spec["repo_root"]))
    assert projected["status"] == "RUNNING"
    assert projected["checks"][0]["progress"]["pytest"]["latest_node"] == actual["latest_node"]
    done = await_completion(directory)
    assert done["status"] == "PASS"
    assert {key: done["progress"]["pytest"][key] for key in ("completed", "passed", "failed")} == {
        "completed": 1, "passed": 1, "failed": 0}
    assert set(load_receipt(directory / "finish.json")) == {"complete", "exit_code", "selected_tests", "executed_tests"}


def test_progress_report_counts_are_duplicate_safe_constant_time_and_without_fsync(tmp_path, monkeypatch):
    from sciplot_core.verification import run_progress

    class NoScan(dict):
        def values(self):
            pytest.fail("A report must not rescan all previous nodes")

    monkeypatch.setattr(run_progress.os, "fsync", lambda *_: pytest.fail("diagnostic writes must not fsync"))
    monkeypatch.setattr(run_progress, "WRITE_INTERVAL", 1000)
    writer = run_progress.PytestProgress(tmp_path, ["passed", "failed", "skipped"])
    writer.rows = NoScan()
    writer.event("passed", "call")
    assert load_receipt(tmp_path / run_progress.PYTEST_PROGRESS)["latest_phase"] == "call"
    for _ in range(3):
        writer.event("passed", "call", "passed")
        writer.event("passed", "teardown", "passed")
        writer.event("failed", "setup", "failed")
        writer.event("failed", "teardown", "passed")
        writer.event("skipped", "setup", "skipped")
        writer.event("skipped", "teardown", "passed")
    assert writer.value["passed"] == 1
    writer.event("passed", "teardown", "failed")
    writer.finish()
    actual = load_receipt(tmp_path / run_progress.PYTEST_PROGRESS)
    assert {key: actual[key] for key in ("completed", "passed", "failed", "skipped")} == {
        "completed": 3, "passed": 0, "failed": 2, "skipped": 1}
    original = (tmp_path / run_progress.PYTEST_PROGRESS).read_bytes()
    writer.event("unknown", "call")
    assert (tmp_path / run_progress.PYTEST_PROGRESS).read_bytes() == original


def test_malformed_unbound_and_stale_progress_never_upgrade_failed_execution(run_spec, monkeypatch):
    from sciplot_core.verification import run_progress

    directory = _pytest_spec(run_spec, "def test_live(): assert False\n")
    start_run(directory=directory, spec=run_spec)
    assert await_completion(directory)["status"] == "FAIL"
    path = directory / run_progress.PYTEST_PROGRESS
    original = path.read_text()
    for field, value in (("version", 99), ("source", {}), ("pid", 1), ("request_sha256", "0" * 64),
                         ("selected_tests_sha256", "0" * 64), ("latest_node", "unknown::test"),
                         ("updated_monotonic", 0), ("status", "PASS")):
        changed = json.loads(original)
        changed[field] = value
        path.write_text(json.dumps(changed))
        result = run_status(directory)
        assert result["status"] == "FAIL"
        assert result["progress"]["pytest"]["available"] is False
    path.write_text("malformed")
    assert run_status(directory)["status"] == "FAIL"
    path.write_text(original)
    future = time.monotonic() + 60
    monkeypatch.setattr(run_progress.time, "monotonic", lambda: future)
    result = run_status(directory)
    assert result["status"] == "FAIL" and result["progress"]["pytest"]["stale"] is True


def test_wall_clock_jumps_preserve_monotonic_ages_and_invalid_relation_only_hides_progress(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from sciplot_core.verification import run_progress

    clock = {"utc": 10000.0, "monotonic": 100.0}
    monkeypatch.setattr(run_progress, "time", SimpleNamespace(time=lambda: clock["utc"], monotonic=lambda: clock["monotonic"]))
    atomic_json(tmp_path / "request.json", {"scope": {"kind": "pytest"}, "selected_tests": ["test_live"]})
    writer = run_progress.PytestProgress(tmp_path, ["test_live"])
    for index, jump in enumerate((897.93, -897.93)):
        clock.update(utc=10000 + jump, monotonic=101.0 + index * 10)
        writer.event("test_live", "call" if index == 0 else "teardown")
        stage = run_progress.stage_progress(tmp_path, file_sha256(tmp_path / "request.json"), "command", {},
                                           10000.0, clock["utc"], 100.0, clock["monotonic"])
        atomic_json(tmp_path / "state.json", {"phase": "blocked", "reason": "synthetic", "child_pid": os.getpid(), "diagnostic": stage})
        (tmp_path / "command.log").write_text("actual log growth")
        clock.update(utc=10000 - jump, monotonic=clock["monotonic"] + 2)
        result = run_status(tmp_path)
        assert result["status"] == "BLOCKED" and result["reason"] == "synthetic"
        for channel in ("pytest", "runner"):
            actual = result["progress"][channel]
            assert actual["available"] and actual["update_age_seconds"] == 2 and not actual["stale"]
            assert actual["updated_at"] == 10000 + jump
        assert result["progress"]["runner"]["stage_elapsed_seconds"] == 2
        assert result["progress"]["log"]["observation_age_seconds"] == 2
        clock["monotonic"] -= 3
        invalid = run_status(tmp_path)
        assert invalid["status"] == "BLOCKED" and invalid["reason"] == "synthetic"
        assert not invalid["progress"]["pytest"]["available"] and not invalid["progress"]["runner"]["available"]


def test_progress_failure_does_not_mask_canonical_session_finish(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from sciplot_core.verification import pytest_finish, run_progress

    destination = tmp_path / "finish.json"
    def unavailable(*_args):
        raise OSError("generated unavailable diagnostic output")
    session = SimpleNamespace(items=[SimpleNamespace(nodeid="generated::test")])
    original_passed, original_progress = pytest_finish._passed, pytest_finish._progress
    original_contents = list(original_passed)
    with monkeypatch.context() as hooks:
        hooks.setenv("SCIPLOT_VERIFY_FINISH", str(destination))
        hooks.delenv("SCIPLOT_VERIFY_QT_MODULES", raising=False)
        hooks.setattr(run_progress, "write_diagnostic", unavailable)
        hooks.setattr(pytest_finish, "_passed", [])
        hooks.setattr(pytest_finish, "_progress", None)
        pytest_finish.pytest_sessionstart(session)
        pytest_finish.pytest_collection_finish(session)
        pytest_finish.pytest_runtest_logreport(SimpleNamespace(when="call", passed=True, nodeid="generated::test"))
        pytest_finish.pytest_sessionfinish(session, 0)
    assert pytest_finish._passed is original_passed and original_passed == original_contents
    assert pytest_finish._progress is original_progress
    assert load_receipt(destination) == {"complete": True, "exit_code": 0,
                                         "selected_tests": ["generated::test"], "executed_tests": ["generated::test"]}


def test_standalone_finish_plugin_needs_no_request_and_cannot_mint_durable_completion(run_spec):
    directory = _pytest_spec(run_spec, "def test_live(): pass\n").parent
    directory.mkdir(parents=True)
    environment = {**run_spec["environment"], "SCIPLOT_VERIFY_FINISH": str(directory / "finish.json")}
    completed = subprocess.run(run_spec["command"], cwd=run_spec["repo_root"], env=environment,
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = run_status(directory)
    assert result["status"] == "BLOCKED" and result["reason"] == "completion_unavailable"
    assert result["progress"]["pytest"]["available"] is True
    assert result["progress"]["pytest"]["request_sha256"] is None
    assert result["progress"]["pytest"]["completed"] == result["progress"]["pytest"]["passed"] == 1
    assert not (directory / "state.json").exists()


def test_preparation_diagnostic_does_not_create_authoritative_state(run_spec):
    from sciplot_core.verification.durable_runner import prepare_run

    directory = Path(run_spec["repo_root"]) / ".tmp_verify/prepared"
    prepare_run(directory=directory, spec=run_spec)
    assert not (directory / "state.json").exists() and not (directory / "launch.json").exists()
    assert run_status(directory) == {"status": "BLOCKED", "reused": False, "reason": "completion_unavailable"}


def test_real_capture_stages_and_timings_are_visible_without_changing_completion_schema(run_spec):
    root = Path(run_spec["repo_root"])
    run_spec["command"] = [sys.executable, "-c", "import time;print('actual command',flush=True);time.sleep(.2)"]
    spec_path = root / "driver-spec.json"
    spec_path.write_text(json.dumps({key: value for key, value in run_spec.items() if key != "environment"}))
    directory = root / ".tmp_verify/timed"
    code = ("import json,os,time;from pathlib import Path;"
            "from sciplot_core.verification import durable_runner as runner;"
            f"root=Path({str(root)!r});directory=Path({str(directory)!r});"
            f"spec=json.loads(Path({str(spec_path)!r}).read_text());spec['environment']=dict(os.environ);"
            "directory,environment,request_hash=runner.prepare_run(directory=directory,spec=spec);"
            "os.environ.clear();os.environ.update(environment);original=runner._capture;calls=0\n"
            "def capture(spec,environment):\n global calls\n calls+=1\n"
            " (root/('before' if calls==1 else 'after')).write_text('entered actual capture')\n"
            " time.sleep(.25)\n return original(spec,environment)\n"
            "runner._capture=capture\nraise SystemExit(runner.supervise(directory,request_hash))")
    with subprocess.Popen([sys.executable, "-c", code], cwd=root, env=run_spec["environment"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        for marker, stage in (("before", "capture_before"), ("after", "capture_after")):
            deadline = time.monotonic() + 5
            while not (root / marker).exists() and time.monotonic() < deadline:
                time.sleep(.01)
            assert (root / marker).exists()
            result = run_status(directory)
            assert result["status"] == "RUNNING" and result["progress"]["runner"]["stage"] == stage
        stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stdout + stderr
    result = run_status(directory)
    assert result["status"] == "PASS"
    timings = result["progress"]["runner"]["timings"]
    assert timings["preparation_seconds"] >= 0
    assert timings["capture_before_seconds"] >= .25 and timings["capture_after_seconds"] >= .25
    assert timings["command_seconds"] >= .2
    assert set(load_receipt(directory / "completion.json")["timings"]) == {
        "capture_before_seconds", "command_seconds", "capture_after_seconds"}
