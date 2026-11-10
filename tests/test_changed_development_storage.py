"""Check execution facts across disposable and recorded verification boundaries."""
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sciplot_core.verification import changed, changed_evidence, development_storage


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path_factory, monkeypatch):
    cache = tmp_path_factory.mktemp("sciplot-cache")
    monkeypatch.setattr(development_storage, "user_cache_path", lambda _app: cache)


def _plan(command):
    return {"status": "planned", "unowned_paths": [], "checks": [
        {"check_id": "pytest_changed_owners", "command": command, "status": "planned"},
    ]}


@pytest.mark.parametrize("fails", (False, True))
@pytest.mark.parametrize("space_available", (False, True))
def test_real_changed_child_reports_actual_command_exit_and_scratch(tmp_path, monkeypatch, fails, space_available):
    if not space_available:
        def unavailable(_path):
            raise OSError("generated capacity observation failure")
        monkeypatch.setattr(development_storage.shutil, "disk_usage", unavailable)
    case = tmp_path / "test_generated.py"
    report = tmp_path / "temporary-path.txt"
    case.write_text("from pathlib import Path\ndef test_generated(tmp_path):\n"
                    "    (tmp_path / 'payload').write_bytes(b'x' * 262144)\n"
                    f"    Path({str(report)!r}).write_text(str(tmp_path))\n"
                    f"    assert {not fails!r}\n")
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    command = [sys.executable, "-m", "pytest", "-q", "-c", str(config), str(case)]
    monkeypatch.setattr(changed, "build_changed_verification_plan", lambda *a, **k: _plan(command))
    result = changed.run_changed_verification(repo_root=tmp_path, changed_paths=["generated"])
    assert result["status"] == ("failed" if fails else "passed")
    assert result["checks_executed"] == 1
    check = result["checks"][0]
    assert check["exit_code"] == int(fails)
    if space_available:
        assert result["storage_before"]["free_bytes"] > 0
        assert result["storage_after"]["free_bytes"] > 0
    else:
        assert result["storage_before"]["free_bytes"] is None
        assert result["storage_after"]["free_bytes"] is None
        assert "observation failure" in result["storage_after"]["warning"]
    if "development_storage" in check:
        assert "tmp_path_retention_policy=failed" in check["command"]
        assert Path(report.read_text()).exists() is fails
    else:
        assert check["command"] == command
        assert Path(report.read_text()).exists()


@pytest.mark.parametrize("exit_code", (0, 1))
def test_original_exit_is_kept_when_scratch_finalization_fails(tmp_path, monkeypatch, capsys, exit_code):
    command = [sys.executable, "-m", "pytest", "-q", "tests/test_generated.py"]
    monkeypatch.setattr(changed, "build_changed_verification_plan", lambda *a, **k: _plan(command))

    @contextmanager
    def failing_storage(*args, **kwargs):
        def finish(_code):
            raise OSError("generated scratch completion write failed")
        yield SimpleNamespace(command=command, environment={}, managed=True,
                              directory=tmp_path, cleanup={}, finish=finish)

    monkeypatch.setattr(development_storage, "development_check_run", failing_storage)
    monkeypatch.setattr(changed, "_run_command", lambda *a, **k:
                        subprocess.CompletedProcess(command, exit_code, "actual child output", ""))
    result = changed.run_changed_verification(repo_root=tmp_path, changed_paths=["generated"])
    assert result["status"] == ("passed" if exit_code == 0 else "failed")
    assert result["checks_executed"] == 1
    check = result["checks"][0]
    assert check["exit_code"] == exit_code and check["stdout"] == "actual child output"
    assert "completion write failed" in check["development_storage_warning"]
    assert f"original child exited {exit_code}" in capsys.readouterr().err


def test_unsafe_scratch_setup_does_not_start_or_claim_a_child(tmp_path, monkeypatch):
    command = [sys.executable, "-m", "pytest", "-q"]
    monkeypatch.setattr(changed, "build_changed_verification_plan", lambda *a, **k: _plan(command))

    @contextmanager
    def unsafe(*args, **kwargs):
        raise ValueError("generated scratch alias")
        yield

    monkeypatch.setattr(development_storage, "development_check_run", unsafe)
    monkeypatch.setattr(changed, "_run_command", lambda *a, **k: pytest.fail("Started unsafe child"))
    result = changed.run_changed_verification(repo_root=tmp_path, changed_paths=["generated"])
    assert result["status"] == "BLOCKED" and result["checks_executed"] == 0
    assert result["checks"][0]["status"] == "not_run"
    assert result["error"]["message"] == "generated scratch alias"


@pytest.mark.parametrize("mode", ("record", "reuse"))
def test_recorded_modes_never_enter_disposable_lifecycle(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(changed, "build_changed_verification_plan", lambda *a, **k: _plan(["generated"]))
    monkeypatch.setattr(development_storage, "development_check_run",
                        lambda *a, **k: pytest.fail("Recorded evidence entered disposable lifecycle"))
    calls = []
    monkeypatch.setattr(changed_evidence, "run_evidence_checks", lambda plan, **kwargs:
                        calls.append(kwargs) or {"status": "recorded_owner_called"})
    directory = tmp_path / ".tmp_verify" / "record"
    result = changed.run_changed_verification(repo_root=tmp_path, changed_paths=["generated"],
                                             **{mode: directory})
    assert result == {"status": "recorded_owner_called"}
    assert calls == [{"repo_root": tmp_path.resolve(), "directory": directory, "reuse": mode == "reuse"}]
    assert not directory.exists()
