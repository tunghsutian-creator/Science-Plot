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


def test_default_cold_runner_observes_subprocess_patch_after_import(tmp_path, monkeypatch):
    script = tmp_path / "generated.py"
    script.write_text('print("generated cold response")\n')
    argv = [sys.executable, str(script)]
    calls = []
    actual_run = subprocess.run

    def measured_run(*args, **kwargs):
        calls.append((args, kwargs))
        return actual_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", measured_run)
    kwargs = {"text": True, "capture_output": True, "check": True, "timeout": 10}
    result = run_worker(argv, **kwargs)
    assert result.returncode == 0 and result.stdout == "generated cold response\n"
    assert calls == [((argv,), kwargs)]


def test_fresh_service_import_keeps_popen_tracking_and_unresolved_annotations():
    script = '''
import inspect
import json
import subprocess
import sys

original = subprocess.Popen
calls = []
def tracked(*args, **kwargs):
    process = original(*args, **kwargs)
    calls.append(process.pid)
    return process

subprocess.Popen = tracked
assert "sciplot_core.native_process.session" not in sys.modules
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.native_process.session import PersistentWorker
assert callable(PlotService)
annotations = inspect.get_annotations(PersistentWorker._start, eval_str=False)
assert annotations == {"return": "subprocess.Popen[bytes]"}, annotations
with subprocess.Popen([sys.executable, "-c", "print('tracked child')"],
                      stdout=subprocess.PIPE, text=True) as child:
    stdout, _ = child.communicate(timeout=10)
assert child.returncode == 0 and stdout == "tracked child\\n"
assert calls == [child.pid]
print(json.dumps({"return_annotation": annotations["return"], "tracked_processes": len(calls)}))
'''
    result = subprocess.run([sys.executable, "-c", script], env=session.veusz_worker_environment(),
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"return_annotation": "subprocess.Popen[bytes]", "tracked_processes": 1}


def test_explicit_cold_runner_remains_authoritative_after_subprocess_patch(monkeypatch):
    calls = []

    def unexpected(*args, **kwargs):
        pytest.fail("The explicit cold runner must own this dispatch.")

    def explicit(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 7, "explicit output", "explicit error")

    monkeypatch.setattr(subprocess, "run", unexpected)
    kwargs = {"text": True, "capture_output": True, "check": False, "timeout": 3}
    result = run_worker(command(), cold_runner=explicit, **kwargs)
    assert (result.returncode, result.stdout, result.stderr) == (7, "explicit output", "explicit error")
    assert calls == [((command(),), kwargs)]


def test_active_worker_never_dispatches_to_default_or_explicit_cold_runner(worker, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("An active worker must own this dispatch.")

    monkeypatch.setattr(subprocess, "run", unexpected)
    with worker.activate():
        first = run_worker(command("default"), check=True, timeout=10)
        second = run_worker(command("explicit"), cold_runner=unexpected, check=True, timeout=10)
    assert json.loads(first.stdout)["mode"] == "default"
    assert json.loads(second.stdout)["mode"] == "explicit"
    assert json.loads(first.stdout)["pid"] == json.loads(second.stdout)["pid"] == worker.last_pid
    assert worker.starts == 1


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
