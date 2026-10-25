"""Native Save and command Save share the original edit baseline and quarantine."""

from pathlib import Path

import pytest

from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.adapters import publish_files, store_for_project
from sciplot_core.studio_core import persistence
from sciplot_core.studio_core.native_save_storage import project_save_binding
from test_veusz_series_revision import _SavableDocument


def fixture_document(tmp_path, monkeypatch):
    root = tmp_path / "project"
    target = root / "studio/document.vsz"
    target.parent.mkdir(parents=True)
    target.write_text("old native")
    (root / "plot_request.json").write_text("{}")
    document = _SavableDocument()
    document._sciplot_project_read_set = project_save_binding(root, target)
    monkeypatch.setattr(persistence, "_validate_staged_veusz_document", lambda *_a, **_kw: True)
    persistence.bind_project_document_save(document, root, target)
    return root, target, document


def test_direct_native_save_publishes_generation_and_updates_edit_baseline(tmp_path, monkeypatch):
    root, target, document = fixture_document(tmp_path, monkeypatch)
    before = document._sciplot_project_read_set.copy()
    receipt = document.save(str(target))
    store = store_for_project(root)
    assert receipt["project_command"]["phase"] == "complete"
    assert store.read_bytes("studio/document.vsz") == b"new document"
    assert document._sciplot_project_read_set["generation"] != before["generation"]
    assert document.filename == str(target)
    assert not document.isModified()
    assert not list(target.parent.glob(".sciplot*"))


def test_live_draft_save_refuses_foreign_same_figure_revision(tmp_path, monkeypatch):
    root, target, document = fixture_document(tmp_path, monkeypatch)
    publish_files(store_for_project(root), {"studio/document.vsz": b"foreign saved native"}, kind="save")
    with pytest.raises(ProjectConflict):
        document.save(str(target))
    assert target.read_bytes() == b"foreign saved native"
    assert document.isModified()


def test_native_save_checks_quarantine_installed_after_original_serializer(tmp_path, monkeypatch):
    _root, target, document = fixture_document(tmp_path, monkeypatch)

    class Quarantined:
        def require_usable(self):
            raise RuntimeError("native draft quarantined")

    document._sciplot_native_setting_batch_adapter = Quarantined()
    with pytest.raises(RuntimeError, match="quarantined"):
        document.save(str(target))
    assert target.read_bytes() == b"old native"
    assert document.isModified()


def test_private_stream_serialization_keeps_exact_logical_base(tmp_path):
    target = tmp_path / "document.vsz"
    target.write_bytes(b"old")
    document = _SavableDocument()
    document.saveToFile = lambda handle: handle.write(repr(handle.name))
    document._sciplot_project_read_set = {"files": {}}
    result = persistence.stage_veusz_document(document, target, staged_validator=lambda *_a, **_kw: True)
    stage = Path(result["staged"])
    try:
        assert stage.parent != target.parent
        assert stage.read_text() == repr(str(target))
        assert target.read_bytes() == b"old"
        assert (document.filename, document.modified, document.changeset) == ("live.vsz", True, 7)
    finally:
        stage.unlink()


def test_legacy_native_save_without_generation_keeps_ordinary_atomic_save(tmp_path, monkeypatch):
    root = tmp_path / "project"
    target = root / "studio/document.vsz"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    (root / "plot_request.json").write_bytes(b"{}")
    monkeypatch.setattr(persistence, "_validate_staged_veusz_document", lambda *_a, **_kw: True)
    receipt = persistence.atomic_save_veusz_document(_SavableDocument(), target)
    assert receipt["project_command"] is None
    assert target.read_bytes() == b"new document"
    assert not (root / ".sciplot_store").exists()


def test_native_save_uses_only_explicit_host_selected_store_capabilities(tmp_path, monkeypatch):
    from sciplot_core.project_store import FileProjectStore

    root, target, document = fixture_document(tmp_path, monkeypatch)
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    selected = FileProjectStore(root, locations={"delivery": delivery})
    publish_files(selected, {"@delivery/result.pdf": b"existing exact delivery"}, kind="publish")
    document._sciplot_project_read_set = project_save_binding(root, target, store=selected)
    document._sciplot_project_store = selected
    receipt = document.save(str(target))
    assert receipt["project_command"]["phase"] == "complete"
    assert (delivery / "result.pdf").read_bytes() == b"existing exact delivery"


@pytest.mark.comprehensive
def test_private_real_veusz_linked_source_save_keeps_logical_relative_base(tmp_path):
    import os
    import subprocess
    import sys

    script = r'''
import sys
from pathlib import Path
from sciplot_core.studio_core.runtime import _ensure_veusz_on_path
_ensure_veusz_on_path()
from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
ensure_veusz_loader_compat()
from PyQt6 import QtWidgets
from veusz import document, dataimport, setting, widgets
from veusz.document.commandinterface import CommandInterface
from sciplot_core.studio_core.persistence import atomic_save_veusz_document, bind_project_document_save
from sciplot_core.studio_core.native_save_storage import project_save_binding
app = QtWidgets.QApplication([])
root = Path(sys.argv[1])
target = root / "studio/document.vsz"
target.parent.mkdir(parents=True)
(root / "plot_request.json").write_bytes(b"{}")
source = root / "source.txt"
source.write_text("1 2\n3 4\n")
setting.settingdb['docfile_addimportpaths'] = False
live = document.Document()
CommandInterface(live).ImportFile(str(source), 'x y', linked=True)
live.save(str(target))
live._sciplot_project_read_set = project_save_binding(root, target)
bind_project_document_save(live, root, target)
receipt = atomic_save_veusz_document(live, target)
assert receipt['ready_for_export'] is True
assert '../source.txt' in target.read_text()
reopened = document.Document()
reopened.load(str(target), callbackunsafe=lambda:False)
assert reopened.data['x'].data.tolist() == [1.0, 3.0]
assert reopened.data['y'].data.tolist() == [2.0, 4.0]
assert source.read_text() == "1 2\n3 4\n"
app.quit()
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "project")],
        capture_output=True, text=True, check=False, env=dict(os.environ), timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
