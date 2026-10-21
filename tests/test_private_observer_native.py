"""Small real native/Qt paths need genuine worker and exec epoch endings."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from sciplot_core.verification.private_observer import CHILD, CONTINUATION, PARENT, RUN, frame_digest, write_bootstrap
from private_observer_support import execute_observed

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.comprehensive
def test_native_normal_close_and_budget_recycle_have_genuine_terminal_streams(tmp_path: Path) -> None:
    plugin = tmp_path / "bootstrap"
    write_bootstrap(plugin)
    output = tmp_path / "raw"
    output.mkdir()
    watch = tmp_path / "watched"
    watch.mkdir()
    environment = dict(os.environ)
    for key in (PARENT, CHILD, CONTINUATION, "PYTEST_CURRENT_TEST"):
        environment.pop(key, None)
    environment.update(PYTHONPATH=os.pathsep.join((str(plugin), str(ROOT / "src"), environment.get("PYTHONPATH", ""))),
                       SCIPLOT_PRIVATE_AUDIT_DIR=str(output), SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps([str(watch)]))
    environment[RUN] = uuid4().hex
    code = """import json,sys
from sciplot_core.native_process.session import PersistentWorker
worker=PersistentWorker(max_requests=2)
command=[sys.executable,'-m','sciplot_core.veusz_worker','font-families']
try:
    first=worker.run(command,check=True);pid=worker.last_pid
    worker.run(command,check=True)
    assert worker.last_pid==pid
    worker.run(command,check=True)
    assert worker.last_pid!=pid and worker.starts==2
finally:
    worker.close()
print(json.dumps({'starts':worker.starts,'closed':worker._closed}))
"""
    _, result = execute_observed(tmp_path, [sys.executable, "-c", code], environment, output, [str(watch)])
    assert result["actual_returncode"] == 0, result["stdout"]
    assert json.loads(result["stdout"]) == {"starts": 2, "closed": True}
    assert result["status"] == "COMPLETE", result["issues"]
    assert result["genuine_finish_count"] == result["epoch_count"] == 4


@pytest.mark.comprehensive
def test_actual_mac_qt_reexec_is_sealed_and_continued(tmp_path: Path) -> None:
    if sys.platform != "darwin":
        pytest.skip("The actual Qt framework reexec path belongs to macOS.")
    plugin = tmp_path / "bootstrap"
    write_bootstrap(plugin)
    output = tmp_path / "raw"
    output.mkdir()
    environment = dict(os.environ)
    for key in (PARENT, CHILD, CONTINUATION, "PYTEST_CURRENT_TEST", "SCIPLOT_STUDIO_QT_RUNTIME"):
        environment.pop(key, None)
    environment.update(PYTHONPATH=os.pathsep.join((str(plugin), str(ROOT / "src"), environment.get("PYTHONPATH", ""))),
                       SCIPLOT_PRIVATE_AUDIT_DIR=str(output), SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps([str(tmp_path / "watched")]))
    environment[RUN] = uuid4().hex
    code = "from sciplot_core.studio_core.runtime import maybe_reexec_with_qt_runtime;maybe_reexec_with_qt_runtime(['--help'])"
    _, result = execute_observed(tmp_path, [sys.executable, "-c", code], environment, output,
                                 [str(tmp_path / "watched")])
    assert result["actual_returncode"] == 0, result["stdout"]
    assert "usage:" in result["stdout"]
    assert result["status"] == "COMPLETE", result["issues"]
    assert result["exec_seal_count"] == 1 and result["genuine_finish_count"] == 2


@pytest.mark.comprehensive
@pytest.mark.parametrize("termination", ["SIGTERM", "SIGKILL"])
def test_daemon_normal_termination_closes_native_worker_and_hardkill_stays_unsealed(
    tmp_path: Path, termination: str,
) -> None:
    from managed_plot_helpers import request_for_source

    plugin = tmp_path / "bootstrap"
    write_bootstrap(plugin)
    output = tmp_path / "raw"
    output.mkdir()
    watch = tmp_path / "watched"
    watch.mkdir()
    request = request_for_source(watch)
    environment = dict(os.environ)
    for key in (PARENT, CHILD, CONTINUATION, "PYTEST_CURRENT_TEST"):
        environment.pop(key, None)
    environment.update(PYTHONPATH=os.pathsep.join((str(plugin), str(ROOT / "src"), environment.get("PYTHONPATH", ""))),
                       SCIPLOT_PRIVATE_AUDIT_DIR=str(output), SCIPLOT_PRIVATE_AUDIT_ROOTS=json.dumps([str(watch)]))
    environment[RUN] = uuid4().hex
    code = f"""import json,signal,subprocess,sys,tempfile,time
from pathlib import Path
from sciplot_core.plot_protocol.client import _ping,call
with tempfile.TemporaryDirectory(prefix='spterm-',dir='/tmp') as temporary:
    path=Path(temporary)/'engine.sock'
    entry=('import signal;from sciplot_core.plot_protocol.server import main;'
           'previous=signal.getsignal(signal.SIGTERM);main();'
           'assert signal.getsignal(signal.SIGTERM) is previous')
    child=subprocess.Popen([sys.executable,'-c',entry,'--socket',str(path)],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+15
        while True:
            assert child.poll() is None,child.communicate()
            try:
                _ping(path,1)
                break
            except (FileNotFoundError,ConnectionRefusedError):
                assert time.monotonic()<deadline
                time.sleep(.02)
        created=call('plot.create',{{'request':{request!r}}},socket_path=path)
        assert created['ready_to_use'],created
        child.send_signal(signal.{termination})
        stdout,stderr=child.communicate(timeout=15)
        assert child.returncode=={0 if termination == 'SIGTERM' else -9},(stdout,stderr)
        assert path.exists() is {termination == 'SIGKILL'}
        assert path.with_name(path.name+'.owner.json').exists() is {termination == 'SIGKILL'}
        print(json.dumps({{'daemon_pid':child.pid,'returncode':child.returncode}}))
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=15)
"""
    proof, result = execute_observed(tmp_path, [sys.executable, "-c", code], environment, output,
                                     [str(watch)], timeout=90)
    (tmp_path / "proof.json").write_text(json.dumps(proof, indent=2))
    (tmp_path / "review.json").write_text(json.dumps(result, indent=2))
    assert result["actual_returncode"] == 0, result["stdout"]
    receipt = json.loads(result["stdout"])
    daemon = receipt["daemon_pid"]
    frames = result["frames"]
    daemon_finishes = [row for row in frames if row["event"] == "process_finish" and row["pid"] == daemon]
    actual_daemon_exit = [row for row in frames if row["event"] == "child_exit" and row["child_pid"] == daemon]
    assert len(actual_daemon_exit) == 1 and actual_daemon_exit[0]["returncode"] == receipt["returncode"]
    worker_command = frame_digest({"arguments": ["-m", "sciplot_core.veusz_worker.persistent"]})
    workers = [row["pid"] for row in frames if row["event"] == "process_start" and row["command_sha256"] == worker_command]
    assert len(workers) == 1
    if termination == "SIGTERM":
        assert result["status"] == "COMPLETE", result["issues"]
        assert len(daemon_finishes) == 1
        assert any(row["event"] == "child_exit" and row["pid"] == daemon
                   and row["child_pid"] == workers[0] and row["returncode"] == 0 for row in frames)
        assert any(row["event"] == "process_finish" and row["pid"] == workers[0] for row in frames)
    else:
        assert result["status"] == "BLOCKED" and daemon_finishes == [], result["issues"]
