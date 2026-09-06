from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from sciplot_core.studio_core import project_session as sessions
from sciplot_core.veusz_runtime import veusz_worker_environment


def test_native_lease_blocks_external_process_until_closed(tmp_path):
    project = tmp_path / "managed"
    project.mkdir()
    lease = sessions.ProjectSessionLease(project, native=True)
    code = "from pathlib import Path; from sciplot_core.studio_core.project_session import ProjectSessionLease; import sys; ProjectSessionLease(Path(sys.argv[1]), native=False).close()"

    def attempt():
        return subprocess.run(
            [sys.executable, "-c", code, str(project)],
            capture_output=True,
            text=True,
            timeout=20,
        )

    try:
        assert "writable Veusz session" in attempt().stderr
    finally:
        lease.close()
    assert attempt().returncode == 0


def test_clean_window_owns_lifetime_lease_and_failed_switch_keeps_it(
    tmp_path, monkeypatch
):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(
        sessions,
        "_project_context_for_document",
        lambda path: {"project_dir": path.parent},
    )
    window = SimpleNamespace(
        filename="", document=SimpleNamespace(isModified=lambda: False)
    )
    with sessions.window_document_session(window, first / "document.vsz"):
        window.filename = str(first / "document.vsz")
    with pytest.raises(sessions.ProjectSessionBusy):
        sessions.ProjectSessionLease(first, native=False)
    with pytest.raises(OSError, match="load failed"):
        with sessions.window_document_session(window, second / "document.vsz"):
            raise OSError("load failed")
    sessions.ProjectSessionLease(second, native=False).close()
    with pytest.raises(sessions.ProjectSessionBusy):
        sessions.ProjectSessionLease(first, native=False)
    sessions.close_window_session(window)
    sessions.ProjectSessionLease(first, native=False).close()


def test_cancelled_load_releases_new_lease_without_releasing_old(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    monkeypatch.setattr(
        sessions,
        "_project_context_for_document",
        lambda path: {"project_dir": path.parent},
    )
    window = SimpleNamespace(filename=str(old / "document.vsz"))
    with sessions.window_document_session(window, old / "document.vsz"):
        pass
    with sessions.window_document_session(window, new / "document.vsz"):
        pass  # Veusz returns without changing filename when a load is cancelled.
    sessions.ProjectSessionLease(new, native=False).close()
    assert window._sciplot_project_session.project == old
    sessions.close_window_session(window)


@pytest.mark.comprehensive
def test_real_clean_native_window_retains_lease_until_close(tmp_path):
    project = tmp_path / "managed"
    (project / "studio").mkdir(parents=True)
    (project / "plot_request.json").write_text("{}")
    code = """
import sys
from pathlib import Path
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
ensure_veusz_runtime_path()
ensure_veusz_loader_compat()
from PyQt6.QtWidgets import QApplication
from veusz import document, widgets, dataimport
from veusz.document import CommandInterface
from sciplot_core.studio_core.qt_window import _create_veusz_window
from sciplot_core.studio_core.project_session import ProjectSessionLease, ProjectSessionBusy
app = QApplication([])
project = Path(sys.argv[1])
path = project / 'studio/document.vsz'
doc = document.Document()
interface = CommandInterface(doc)
interface.Add('page', name='page1')
interface.Save(str(path))
window = _create_veusz_window(path)
assert window.document.isModified() is False
try:
    ProjectSessionLease(project, native=False)
except ProjectSessionBusy:
    pass
else:
    raise AssertionError('clean native window failed to exclude external writes')
window.close()
app.processEvents()
ProjectSessionLease(project, native=False).close()
print('native lifetime lease passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(project)],
        env=veusz_worker_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "native lifetime lease passed" in result.stdout
