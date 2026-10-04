"""Only the private closed busy marker supplements existing native worker errors."""

import json
import subprocess

import pytest

from sciplot_core import rheology_tts_render as render
from sciplot_core.studio_core.project_session import ProjectSessionBusy


BUSY = {"kind": "sciplot_tts_native_failure", "version": 1, "native_reason_code": "project_busy"}


@pytest.mark.parametrize("wire", [BUSY, {}, [], None, "not JSON", {**BUSY, "version": True},
    {**BUSY, "version": 1.0}, {**BUSY, "version": 2}, {**BUSY, "kind": "another_worker"},
    {**BUSY, "native_reason_code": "unknown_reason"}, {**BUSY, "extra": "project_busy"},
    {"kind": "sciplot_tts_native_failure", "version": 1}])
def test_worker_error_preserves_runtime_error_and_trusts_only_closed_busy_marker(monkeypatch, wire):
    stderr = "the complete original worker traceback\nfinal message\n"
    monkeypatch.setattr(render, "needs_veusz_worker_process", lambda: True)
    monkeypatch.setattr(render.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, stdout=wire if isinstance(wire, str) else json.dumps(wire), stderr=stderr))
    with pytest.raises(RuntimeError) as caught:
        render._dispatch({"action": "render"})
    assert type(caught.value) is RuntimeError
    assert caught.value.args == ("Native TTS figure operation failed:\n" + stderr,)
    trusted = isinstance(wire, dict) and wire == BUSY and type(wire.get("version")) is int
    assert getattr(caught.value, "native_reason_code", None) == ("project_busy" if trusted else None)
    assert not hasattr(caught.value, "reason_code")


@pytest.mark.parametrize("busy", [False, True])
def test_worker_marker_does_not_wrap_or_rewrite_original_exception(monkeypatch, capsys, busy):
    error = ProjectSessionBusy("original busy detail") if busy else ValueError("original native failure")
    def fail(_request):
        raise error
    monkeypatch.setattr(render, "_run_native", fail)
    with pytest.raises(type(error)) as caught:
        render._worker_result({"action": "render"})
    assert caught.value is error
    output = capsys.readouterr()
    assert json.loads(output.out) == BUSY if busy else output.out == ""
    assert output.err == ""
