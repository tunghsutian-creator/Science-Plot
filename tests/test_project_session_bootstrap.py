"""Explicit native admission imports old projects without changing read-only queries."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from test_project_query import project as project
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectRecoveryRequired
from sciplot_core.studio_core import project_session as sessions
from sciplot_core.studio_core.project_query import inspect_project


def _window() -> SimpleNamespace:
    return SimpleNamespace(filename="", document=SimpleNamespace(save=lambda *_args: None))


def _files(root: Path, *, include_store: bool = True) -> dict[str, tuple[bytes, int]]:
    return {path.relative_to(root).as_posix(): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            for path in root.rglob("*") if path.is_file()
            and (include_store or ".sciplot_store" not in path.relative_to(root).parts)}


@pytest.mark.parametrize("figure", ["studio/document.vsz", "studio/figures/second.vsz"])
def test_first_explicit_native_open_imports_original_files_once_and_binds_only_selection(project, figure):
    target = project / figure
    original = _files(project)
    assert not (project / ".sciplot_store").exists()
    window = _window()
    try:
        with sessions.window_document_session(window, target, loading=True):
            window.filename = str(target)
        store = FileProjectStore(project)
        before = store.snapshot()
        witness = window.document._sciplot_project_read_set
        assert before["origin"] == "explicit_legacy_import" and before["sequence"] == 0
        assert witness["generation"] == before["generation"]
        assert figure in witness["files"] and "source/data.csv" in witness["files"]
        other = "studio/figures/second.vsz" if figure == "studio/document.vsz" else "studio/document.vsz"
        assert other not in witness["files"]
        assert _files(project, include_store=False) == original
        # Existing Core opens reuse its exact authority; they do not import again.
        with sessions.window_document_session(window, target, loading=True):
            pass
        assert store.snapshot()["generation"] == before["generation"]
        assert _files(project, include_store=False) == original
        with sessions.ProjectSessionLease(project, native=False):
            pass
    finally:
        sessions.close_window_session(window)


def test_cold_native_first_open_uses_this_project_without_preseeding_its_store(project):
    original = _files(project)
    code = """
from pathlib import Path
import sys
from types import SimpleNamespace
from sciplot_core.studio_core.project_session import window_document_session, close_window_session
from sciplot_core.project_store import FileProjectStore
project = Path(sys.argv[1])
target = project / 'studio/document.vsz'
assert not (project / '.sciplot_store').exists()
window = SimpleNamespace(filename='', document=SimpleNamespace(save=lambda *_args: None))
with window_document_session(window, target, loading=True):
    window.filename = str(target)
binding = window.document._sciplot_project_read_set
assert binding['project_id'] == FileProjectStore(project).snapshot()['project_id']
assert 'studio/figures/second.vsz' not in binding['files']
close_window_session(window)
"""
    result = subprocess.run([sys.executable, "-c", code, str(project)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _files(project, include_store=False) == original


def test_existing_core_open_after_directory_move_retains_original_source_locators(project):
    before = FileProjectStore(project).snapshot(import_legacy=True)
    original = _files(project, include_store=False)
    moved = project.with_name("moved-project")
    project.rename(moved)
    target = moved / "studio/document.vsz"
    window = _window()
    try:
        with sessions.window_document_session(window, target, loading=True):
            window.filename = str(target)
        binding = window.document._sciplot_project_read_set
        assert binding["project_id"] == before["project_id"]
        assert binding["generation"] == before["generation"]
        assert "source/data.csv" in binding["files"]
        assert not project.exists()
        assert _files(moved, include_store=False) == original
    finally:
        sessions.close_window_session(window)


@pytest.mark.parametrize("partial", ["empty", "missing-head", "foreign-head"])
def test_explicit_open_never_reimports_partial_or_foreign_core(project, partial):
    if partial == "empty":
        (project / ".sciplot_store").mkdir()
    else:
        FileProjectStore(project).snapshot(import_legacy=True)
        head = project / ".sciplot_store/head.json"
        if partial == "missing-head":
            head.unlink()
        else:
            value = json.loads(head.read_bytes())
            head.write_text(json.dumps({**value, "project_id": "0" * 32}))
    original = _files(project)
    window = _window()
    with pytest.raises((ProjectConflict, ProjectRecoveryRequired)):
        with sessions.window_document_session(window, project / "studio/document.vsz", loading=True):
            pytest.fail("partial or foreign Core reached native loading")
    assert _files(project) == original
    assert getattr(window, "_sciplot_project_session", None) is None
    assert not hasattr(window.document, "_sciplot_project_read_set")


def test_source_drift_cannot_become_a_registered_first_open_witness(project):
    (project / "source/data.csv").write_bytes(b"x,y\n1,999\n")
    original = _files(project)
    window = _window()
    try:
        with sessions.window_document_session(window, project / "studio/document.vsz", loading=True):
            window.filename = str(project / "studio/document.vsz")
        assert not (project / ".sciplot_store").exists()
        assert not hasattr(window.document, "_sciplot_project_read_set")
        with pytest.raises(sessions.ProjectSessionBusy):
            sessions.ProjectSessionLease(project, native=False)
        assert _files(project) == original
    finally:
        sessions.close_window_session(window)


def test_failed_native_load_retains_prior_draft_identity_and_leaves_original_files(project):
    target = project / "studio/document.vsz"
    window = _window()
    with sessions.window_document_session(window, target, loading=True):
        window.filename = str(target)
    original, witness = _files(project), window.document._sciplot_project_read_set
    lease = window._sciplot_project_session
    try:
        with pytest.raises(OSError, match="controlled load failure"):
            with sessions.window_document_session(window, project / "studio/figures/second.vsz", loading=True):
                raise OSError("controlled load failure")
        assert window._sciplot_project_session is lease
        assert window.document._sciplot_project_read_set is witness
        assert _files(project) == original
    finally:
        sessions.close_window_session(window)


def test_read_only_inspection_of_unregistered_project_does_not_admit_native_writes(project):
    original = _files(project)
    result = inspect_project(project, figure_id="first", native=False)
    assert result["status"] == "ok"
    assert _files(project) == original
    assert not (project / ".sciplot_store").exists()


def test_existing_project_writer_scope_remains_reentrant_during_native_admission(project):
    from sciplot_core.project_store.io import StoreIO

    store = FileProjectStore(project)
    original = store.snapshot(import_legacy=True)
    window = _window()
    try:
        with StoreIO(store.root, store.locations, store.location_members).locked():
            with sessions.window_document_session(window, project / "studio/document.vsz", loading=True):
                window.filename = str(project / "studio/document.vsz")
        assert window.document._sciplot_project_read_set["generation"] == original["generation"]
        assert store.snapshot()["generation"] == original["generation"]
    finally:
        sessions.close_window_session(window)


def test_unidentified_native_session_cannot_be_bypassed_by_first_open_import(project):
    window = _window()
    try:
        with sessions.ProjectSessionLease(project, native=True):
            with sessions.window_document_session(window, project / "studio/document.vsz", loading=True):
                window.filename = str(project / "studio/document.vsz")
            assert not (project / ".sciplot_store").exists()
            assert not hasattr(window.document, "_sciplot_project_read_set")
            with pytest.raises(sessions.ProjectSessionBusy):
                sessions.ProjectSessionLease(project, native=False)
    finally:
        sessions.close_window_session(window)


@pytest.mark.parametrize("intervening", ["empty", "partial", "complete"])
def test_first_open_rechecks_concurrent_store_creation_under_the_core_writer(project, monkeypatch, intervening):
    from sciplot_core.studio_core import project_command_scope

    original = _files(project)
    observe = project_command_scope.figure_read_state
    admitted = []

    def concurrent_import(*args, **kwargs):
        result = observe(*args, **kwargs)
        if not admitted:
            if intervening in {"empty", "partial"}:
                if intervening == "empty":
                    (project / ".sciplot_store").mkdir()
                else:
                    retained = project / ".sciplot_store/generations/interrupted.json"
                    retained.parent.mkdir(parents=True)
                    retained.write_bytes(b"retained incomplete import; recovery required")
                admitted.append(_files(project))
            else:
                admitted.append(FileProjectStore(project).snapshot(import_legacy=True))
        return result

    if intervening == "complete":
        admit_open = FileProjectStore.admit_open

        def completed_before_admission(store, **kwargs):
            # A cooperating writer finishes before this writer takes its lease;
            # it cannot publish inside the new writer's locked source preflight.
            if not admitted:
                admitted.append(FileProjectStore(project).snapshot(import_legacy=True))
            return admit_open(store, **kwargs)

        monkeypatch.setattr(FileProjectStore, "admit_open", completed_before_admission)
    else:
        monkeypatch.setattr(project_command_scope, "figure_read_state", concurrent_import)
    window = _window()
    try:
        if intervening in {"empty", "partial"}:
            with pytest.raises(ProjectRecoveryRequired):
                with sessions.window_document_session(window, project / "studio/document.vsz", loading=True):
                    pytest.fail("concurrent incomplete Core reached native loading")
            assert _files(project) == admitted[0]
            assert not (project / ".sciplot_store/head.json").exists()
        else:
            with sessions.window_document_session(window, project / "studio/document.vsz", loading=True):
                window.filename = str(project / "studio/document.vsz")
            assert window.document._sciplot_project_read_set["generation"] == admitted[0]["generation"]
            assert FileProjectStore(project).snapshot()["generation"] == admitted[0]["generation"]
        assert _files(project, include_store=False) == original
    finally:
        sessions.close_window_session(window)


@pytest.mark.comprehensive
def test_real_native_first_open_binds_before_loading_and_reopens_same_generation(project):
    from sciplot_core.veusz_runtime import veusz_worker_environment

    code = """
from pathlib import Path
import sys
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
ensure_veusz_runtime_path()
ensure_veusz_loader_compat()
from PyQt6.QtWidgets import QApplication
from veusz import document, widgets, dataimport
from veusz.document import CommandInterface
from sciplot_core.studio_core.qt_window import _create_veusz_window
from sciplot_core.studio_core.project_session import ProjectSessionLease
from sciplot_core.project_store import FileProjectStore
app = QApplication([])
project = Path(sys.argv[1])
target = project / 'studio/document.vsz'
doc = document.Document()
interface = CommandInterface(doc)
interface.Add('page', name='page1')
interface.Save(str(target))
original = target.read_bytes()
assert not (project / '.sciplot_store').exists()
window = _create_veusz_window(target)
binding = window.document._sciplot_project_read_set
store = FileProjectStore(project)
assert binding['generation'] == store.snapshot()['generation']
assert 'studio/figures/second.vsz' not in binding['files']
assert not window.document.isModified()
with ProjectSessionLease(project, native=False):
    pass
generation = binding['generation']
window.close()
app.processEvents()
reopened = _create_veusz_window(target)
assert reopened.document._sciplot_project_read_set['generation'] == generation
assert target.read_bytes() == original
reopened.close()
app.processEvents()
print('known native first open and reopen passed')
"""
    result = subprocess.run([sys.executable, "-c", code, str(project)],
        env=veusz_worker_environment(), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "known native first open and reopen passed" in result.stdout
