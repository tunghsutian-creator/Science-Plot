"""Small real native/Qt paths need genuine worker and exec epoch endings."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from sciplot_core.verification.private_observer import CHILD, CONTINUATION, PARENT, RUN, write_bootstrap
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
