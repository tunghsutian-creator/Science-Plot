"""Font lookup cannot initialize Qt in an MCP or other caller worker thread."""

import builtins
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import threading

import pytest

from sciplot_core import native_font_catalog as catalog
from sciplot_core import task_common_edits as edits
from sciplot_core.native_process.protocol import validate_request
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.veusz_worker.cli import _build_parser
from sciplot_core.veusz_worker.font_catalog import font_families


def _payload(families=None):
    return {"kind": "sciplot_native_font_catalog", "version": 1,
            "families": ["Arial", "Helvetica"] if families is None else families}


def test_caller_thread_queries_existing_native_worker_and_never_imports_qt(monkeypatch):
    calls = []
    def native(command, **options):
        calls.append((command, options, threading.current_thread()))
        return subprocess.CompletedProcess(command, 0, json.dumps(_payload()), "")
    monkeypatch.setattr(catalog, "run_worker", native)
    original = builtins.__import__
    def no_parent_qt(name, *args, **kwargs):
        if name.startswith("PyQt6"):
            pytest.fail("font lookup attempted to import Qt in the caller process")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_parent_qt)
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(edits._installed_font, "Helvetica").result() is None
    command, options, thread = calls[0]
    assert command == [sys.executable, "-m", "sciplot_core.veusz_worker", "font-families"]
    assert thread is not threading.main_thread()
    assert options["capture_output"] is True and options["text"] is True and options["timeout"] == 30
    assert "PYTHONPATH" in options["env"]


def test_native_font_leaf_rejects_worker_thread_before_any_qt_import(monkeypatch):
    original = builtins.__import__
    def no_qt(name, *args, **kwargs):
        if name.startswith("PyQt6"):
            pytest.fail("wrong-thread native leaf imported Qt before rejecting")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_qt)
    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(RuntimeError, match="main thread"):
        pool.submit(font_families).result()


@pytest.mark.parametrize("arguments", [["/data.vsz"], ["--out", "/tmp/out"], ["--code", "print(1)"], ["--help"]])
def test_font_transport_command_has_no_argument_or_path_capability(arguments):
    assert validate_request({"id": "font-query", "argv": ["font-families"]}) == ("font-query", ["font-families"])
    with pytest.raises(ValueError, match="no arguments"):
        validate_request({"id": "font-query", "argv": ["font-families", *arguments]})
    if arguments != ["--help"]:
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["font-families", *arguments])


@pytest.mark.parametrize("payload,returncode", [
    ("not json", 0), (_payload(), 1), ({**_payload(), "extra": "untrusted"}, 0),
    (_payload([]), 0), (_payload(["Helvetica", "Arial"]), 0), (_payload(["Arial", "Arial"]), 0),
    (_payload([23]), 0), ({**_payload(), "version": True}, 0),
])
def test_unverified_catalog_cannot_turn_into_font_substitution_or_an_edit(monkeypatch, tmp_path, payload, returncode):
    output = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(catalog, "run_worker", lambda command, **_: subprocess.CompletedProcess(command, returncode, output, "diagnostic"))
    monkeypatch.setattr(edits, "doctor_payload", lambda: pytest.fail("queried runtime after invalid catalog"))
    with pytest.raises(EngineError) as error:
        edits.edit_task(tmp_path / "never-opened", font_family="Helvetica", task_dir=tmp_path / "never-allocated")
    assert error.value.reason_code == "common_edit_font_catalog_unavailable"
    assert not list(tmp_path.iterdir())


def test_unavailable_font_rejects_before_runtime_read_document_or_entry_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "installed_font_families", lambda: ["Arial", "Helvetica"])
    monkeypatch.setattr(edits, "doctor_payload", lambda: pytest.fail("queried runtime for unavailable font"))
    class Unopened:
        def open(self, *_a, **_k):
            pytest.fail("opened document for unavailable font")
        def close(self):
            pass
    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(EngineError) as error:
        pool.submit(edits.edit_task, tmp_path / "never-opened", font_family="Missing family", task_dir=tmp_path / "never-allocated", service=Unopened()).result()
    assert error.value.repair["fonts"] == ["Arial", "Helvetica"]
    assert error.value.repair["request_executed"] is False
    assert not list(tmp_path.iterdir())
