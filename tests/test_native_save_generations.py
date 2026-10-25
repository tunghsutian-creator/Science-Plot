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
    result = persistence.stage_veusz_document(document, target, staged_validator=lambda *_a, **_kw: True)
    stage = Path(result["staged"])
    try:
        assert stage.parent != target.parent
        assert stage.read_text() == repr(str(target))
        assert target.read_bytes() == b"old"
        assert (document.filename, document.modified, document.changeset) == ("live.vsz", True, 7)
    finally:
        stage.unlink()
