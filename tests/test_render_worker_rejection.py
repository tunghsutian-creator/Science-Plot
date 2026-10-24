"""Expected native preparation rejections retain their actual repair reason."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.cli.value_io import _cli_runtime_error_payload
from sciplot_core.render import target_paths
from sciplot_core.studio_render.models import StudioPreparationBlocked


def _failure():
    return {"kind": "sciplot_worker_preparation_blocked", "version": 1,
            "reason_code": "performance_radar_presentation_size_conflict",
            "message": "Radar needs 120x55 mm; explicit 60x55 conflicts. Plot panel remains 60x55 mm."}


def test_worker_domain_rejection_is_closed_stderr_and_nonzero(monkeypatch, capsys):
    import sciplot_core.veusz_worker as worker

    for channel in ("none", "fd2", "python_stderr", "fd1"):
        def reject(channel=channel):
            if channel == "fd2":
                os.write(2, b"native fd2 preparation diagnostic\n")
            elif channel == "python_stderr":
                print("Python preparation diagnostic", file=sys.stderr)
            elif channel == "fd1":
                os.write(1, b"native fd1 preparation diagnostic\n")
            raise StudioPreparationBlocked(_failure()["reason_code"], _failure()["message"])
        monkeypatch.setattr(worker, "main", reject)
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_module("sciplot_core.veusz_worker.__main__", run_name="__main__")
        captured = capsys.readouterr()
        assert exit_info.value.code == 1 and captured.out == ""
        assert json.loads(captured.err) == _failure(), channel

    def crash():
        os.write(2, b"untyped native diagnostic\n")
        raise RuntimeError("untyped worker failure")
    monkeypatch.setattr(worker, "main", crash)
    with pytest.raises(RuntimeError, match="untyped worker failure"):
        runpy.run_module("sciplot_core.veusz_worker.__main__", run_name="__main__")
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "untyped native diagnostic\n"


@pytest.mark.parametrize("fault", [None, "traceback", "kind", "extra", "version", "returncode", "message"])
def test_parent_only_projects_an_exact_expected_worker_failure(monkeypatch, tmp_path, fault):
    failure = _failure()
    if fault == "kind":
        failure["kind"] = "some_unrelated_error"
    elif fault == "extra":
        failure["execute"] = "arbitrary"
    elif fault == "version":
        failure["version"] = True
    elif fault == "message":
        failure["message"] = []
    stderr = "Traceback: worker crashed" if fault == "traceback" else json.dumps(failure)
    stderrs = [stderr]
    if fault == "traceback":
        stderrs.append("native diagnostic\n" + json.dumps(failure))
    for stderr in stderrs:
        original = subprocess.CalledProcessError(2 if fault == "returncode" else 1, ["worker"], stderr=stderr)
        def failed(*a, _original=original, **kw):
            raise _original
        monkeypatch.setattr(target_paths.subprocess, "run", failed)
        monkeypatch.setattr(target_paths, "_veusz_worker_env", lambda: {})
        expected = StudioPreparationBlocked if fault is None else subprocess.CalledProcessError
        with pytest.raises(expected) as caught:
            target_paths._render_studio_exports(tmp_path / "request.json", ("pdf",))
        if fault is None:
            payload = _cli_runtime_error_payload(caught.value)
            assert payload["reason_code"] == _failure()["reason_code"]
            assert payload["category"] == "expected_runtime_failure"
            assert payload["message"] == _failure()["message"]
        else:
            assert caught.value is original


@pytest.mark.comprehensive
def test_real_public_radar_size_conflict_retains_clear_reason_and_no_artifacts(tmp_path):
    fixture = REPO_ROOT / "tests/fixtures/performance_comparison/material_performance_long.csv"
    output = tmp_path / "rejected"
    result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "render", str(fixture),
                             "--template", "polar_curve", "--auto", "--options", '{"size":"60x55"}',
                             "--out", str(output), "--json"], capture_output=True, text=True, timeout=120,
                            env={**os.environ, "SCIPLOT_PYTHON": sys.executable})
    artifacts = [str(path.relative_to(output)) for path in output.rglob("*")
                 if path.suffix.lower() in {".pdf", ".tiff", ".vsz"}]
    diagnostic = json.dumps({"returncode": result.returncode, "stdout": result.stdout,
                             "stderr": result.stderr, "scientific_artifacts": artifacts},
                            ensure_ascii=False)
    assert result.returncode == 1, diagnostic
    payload = json.loads(result.stdout)
    assert payload["reason_code"] == "performance_radar_presentation_size_conflict", diagnostic
    assert "120x55" in payload["message"] and "60x55" in payload["message"], diagnostic
    assert not artifacts, diagnostic
