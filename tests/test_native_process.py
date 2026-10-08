"""Persistent native transport owns process lifetime, framing and timeout recovery."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from sciplot_core.native_process import NativeRuntimeChanged, NativeWorkerDisconnected, PersistentWorker, active_worker, run_worker
from sciplot_core.native_process import protocol, session


@pytest.fixture
def worker(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text('''import json, os, sys, time
for line in sys.stdin:
    request = json.loads(line)
    mode = request['argv'][-1]
    if mode == 'disconnect': os._exit(7)
    if mode == 'timeout': time.sleep(2)
    if mode == 'bad-json':
        print('not-json', flush=True)
        continue
    result = {'id': request['id'], 'returncode': 0, 'stdout': json.dumps({'pid':os.getpid(), 'mode':mode}), 'stderr':'', 'pid':os.getpid()}
    if mode == 'bad-id': result['id']='unrelated'
    if mode == 'big': result['stdout']='x'*10000
    if mode == 'failure': result.update(returncode=1, stderr='native validation failed')
    print(json.dumps(result), flush=True)
''')
    value = PersistentWorker(worker_command=[sys.executable, str(script)])
    yield value
    value.close()


def command(mode="ordinary"):
    return [sys.executable, "-m", "sciplot_core.veusz_worker", "audit-documents", mode]


def test_reuses_pid_but_sends_each_command_and_keeps_context_local(worker):
    assert active_worker() is None
    with worker.activate():
        first = run_worker(command("one"), text=True, capture_output=True, check=True)
        second = run_worker(command("two"), text=True, capture_output=True, check=True)
        assert active_worker() is worker
    assert active_worker() is None
    assert json.loads(first.stdout)["pid"] == json.loads(second.stdout)["pid"] == worker.last_pid
    assert json.loads(first.stdout)["mode"] == "one" and json.loads(second.stdout)["mode"] == "two"
    assert worker.starts == 1


@pytest.mark.parametrize("mode", ["disconnect", "bad-id", "bad-json"])
def test_disconnect_and_invalid_frames_do_not_retry_the_failed_command(worker, mode):
    with pytest.raises(NativeWorkerDisconnected):
        worker.run(command(mode))
    assert worker.starts == 1 and worker._process is None
    assert worker.run(command()).returncode == 0 and worker.starts == 2


def test_timeout_reaps_process_before_a_later_explicit_retry(worker):
    with pytest.raises(subprocess.TimeoutExpired):
        worker.run(command("timeout"), timeout=0.05)
    old_pid = worker.last_pid
    assert worker._process is None and worker.starts == 1
    with pytest.raises(ProcessLookupError):
        os.kill(old_pid, 0)
    assert worker.run(command()).returncode == 0 and worker.starts == 2 and worker.last_pid != old_pid


def test_ordinary_native_failure_preserves_stderr_and_process(worker):
    result = worker.run(command("failure"))
    assert result.returncode == 1 and result.stderr == "native validation failed"
    with pytest.raises(subprocess.CalledProcessError) as exc:
        worker.run(command("failure"), check=True)
    assert exc.value.stderr == "native validation failed"
    assert worker.run(command()).returncode == 0 and worker.starts == 1


def test_response_size_limit_kills_process(worker, monkeypatch):
    monkeypatch.setattr(session, "MAX_RESPONSE_BYTES", 4096)
    with pytest.raises(NativeWorkerDisconnected):
        worker.run(command("big"))
    assert worker._process is None and worker.starts == 1


def test_request_budget_and_unsafe_commands_fail_without_starting_a_process(worker):
    for argv in (["migrate-unit-labels", "/canonical.vsz"], ["save-spec", "/canonical.vsz", "/spec"],
                 ["audit-documents", "x" * 9000]):
        with pytest.raises(ValueError):
            worker.run([*command()[:3], *argv])
    assert worker.starts == 0


def test_serial_requests_cannot_mix_responses_from_concurrent_callers(worker):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda index: worker.run(command(str(index))), range(12)))
    assert [json.loads(result.stdout)["mode"] for result in results] == [str(index) for index in range(12)]
    assert len({json.loads(result.stdout)["pid"] for result in results}) == 1


def test_recycling_bounds_process_lifetime(worker):
    worker.max_requests = 2
    first = worker.run(command())
    worker.run(command())
    third = worker.run(command())
    assert json.loads(first.stdout)["pid"] != json.loads(third.stdout)["pid"] and worker.starts == 2


def test_close_reaps_child_and_prevents_new_work(worker):
    worker.run(command())
    pid = worker.last_pid
    worker.close()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    with pytest.raises(NativeWorkerDisconnected):
        worker.run(command())


def test_legacy_path_preserves_exact_subprocess_arguments_without_a_session():
    calls = []

    def cold(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, "{}", "")

    kwargs = {"text": True, "capture_output": True, "check": False, "timeout": 120, "env": {"custom": "value"}}
    run_worker(command(), cold_runner=cold, **kwargs)
    assert calls == [((command(),), kwargs)]


@pytest.mark.parametrize("raw", [b'{"id":"a","id":"b","argv":[]}', b'{"id":NaN,"argv":[]}', b'[]'])
def test_duplicate_and_nonfinite_protocol_values_are_rejected(raw):
    with pytest.raises(ValueError):
        protocol.decode(raw)


def test_request_identity_and_shape_are_closed():
    for value in ({"id": True, "argv": ["audit-documents"]}, {"id": "x", "argv": ["audit-documents"], "extra": 1}):
        with pytest.raises(ValueError):
            protocol.validate_request(value)


def test_loaded_runtime_change_stops_before_dispatch_and_cannot_bless_cache(worker, monkeypatch):
    monkeypatch.setattr(session, "current_identity", lambda: "runtime-one")
    worker.run(command())
    pid = worker.last_pid
    monkeypatch.setattr(session, "current_identity", lambda: "runtime-two")
    with pytest.raises(NativeRuntimeChanged) as exc:
        session.verified_runtime_identity()
    assert exc.value.reason_code == "native_runtime_changed"
    with pytest.raises(NativeRuntimeChanged):
        worker.run(command())
    assert worker.starts == 1 and worker._process is None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    with pytest.raises(NativeRuntimeChanged):
        worker.run(command())
    assert worker.starts == 1


def test_source_identity_hashes_bytes_even_when_size_and_mtime_are_preserved(tmp_path, monkeypatch):
    from sciplot_core.native_process import identity

    source = tmp_path / "renderer.py"
    source.write_text("value = 1")
    stamp = source.stat()
    monkeypatch.setattr(identity, "PACKAGE_ROOT", tmp_path)
    monkeypatch.setattr(identity, "VEUSZ_ROOT", tmp_path)
    first = identity.current_identity()
    source.write_text("value = 2")
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert source.stat().st_size == stamp.st_size
    assert identity.current_identity() != first


def test_change_during_native_execution_invalidates_successful_response(worker, monkeypatch):
    identities = iter(["first", "first", "changed"])
    monkeypatch.setattr(session, "current_identity", lambda: next(identities))
    with pytest.raises(NativeRuntimeChanged):
        worker.run(command())
    assert worker.starts == 1 and worker._process is None


def test_artifact_qa_uses_active_worker_and_keeps_legacy_cold_route(worker, monkeypatch, tmp_path):
    from sciplot_core.qa import audit_support

    calls = []

    def warm(command, **kwargs):
        calls.append(("warm", command, kwargs))
        return subprocess.CompletedProcess(command, 0, '{"documents":[]}', "")

    def cold(command, **kwargs):
        calls.append(("cold", command, kwargs))
        return subprocess.CompletedProcess(command, 0, '{"documents":[]}', "")

    monkeypatch.setattr(worker, "run", warm)
    monkeypatch.setattr(audit_support.subprocess, "run", cold)
    path = tmp_path / "document.vsz"
    with worker.activate():
        assert audit_support._run_veusz_audit([path]) == ({"documents": []}, None)
    assert audit_support._run_veusz_audit([path]) == ({"documents": []}, None)
    assert [call[0] for call in calls] == ["warm", "cold"]
    assert calls[0][1] == calls[1][1] == [*command()[:3], "audit-documents", str(path)]
    assert calls[0][2] == {"timeout": 120, "check": True}
