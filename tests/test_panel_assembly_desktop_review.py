"""Regressions for independent desktop completion, label and path review."""

import threading

import pytest
import test_panel_assembly_desktop as support

qt = support.qt
workbench = support.workbench


@pytest.mark.parametrize("catalogue_fails", [False, True])
def test_catalogue_completion_restores_toolbar_after_panel_selection(workbench, qt, tmp_path, monkeypatch, catalogue_fails):
    from sciplot_core.panel_assembly import desktop_sources

    window = workbench
    identifier = support.add_image(window, qt, support.image(tmp_path))
    gate = threading.Event()

    def catalogue(_path):
        assert gate.wait(5), "Test must release its catalogue worker"
        if catalogue_fails:
            raise ValueError("Catalogue failed for the test")
        return []

    monkeypatch.setattr(desktop_sources, "project_choices", catalogue)
    keys = ("new", "open", "check", "export")
    assert window.library.load_project(tmp_path)
    try:
        qt[2].QTest.mouseClick(window.canvas, qt[1].Qt.MouseButton.LeftButton,
                             pos=window.canvas.panel_rect(identifier).center().toPoint())
        assert window.library.busy and window.selected == identifier
        assert all(not window.actions[key].isEnabled() for key in keys)
    finally:
        gate.set()
    support.settle(window, qt)
    assert not window.library.busy
    assert all(window.actions[key].isEnabled() for key in keys)
    assert window.actions["undo"].isEnabled()
    if catalogue_fails:
        assert "Catalogue failed" in window.status.text()


def test_hidden_custom_and_automatic_labels_paint_and_survive_panel_edits(workbench, qt, tmp_path):
    from sciplot_core.panel_assembly import model

    window = workbench
    identifier = support.add_image(window, qt, support.image(tmp_path))
    controls = window.panel_controls
    left = qt[1].Qt.MouseButton.LeftButton
    assert controls.automatic_label.isChecked()
    assert model.resolve_document(window.document)["panels"][0]["label"] == "a"
    qt[2].QTest.mouseClick(controls.automatic_label, left)
    assert controls.label.isEnabled()
    qt[2].QTest.mouseClick(controls.apply_button, left)
    hidden = model.resolve_document(window.document)["panels"][0]
    assert hidden["id"] == identifier and hidden["label"] == "" and hidden["label_mm"] is None
    assert not window.canvas.grab().isNull(), "A hidden letter must survive a real Qt paint"
    controls.row_span.setValue(2)
    qt[2].QTest.mouseClick(controls.apply_button, left)
    assert window.document["panels"][0]["label"] == ""
    qt[2].QTest.keyClicks(controls.label, "B")
    qt[2].QTest.mouseClick(controls.apply_button, left)
    assert model.resolve_document(window.document)["panels"][0]["label"] == "B"
    assert not window.canvas.grab().isNull()
    qt[2].QTest.mouseClick(controls.automatic_label, left)
    qt[2].QTest.mouseClick(controls.apply_button, left)
    assert window.document["panels"][0]["label"] is None
    assert model.resolve_document(window.document)["panels"][0]["label"] == "a"
    assert not window.canvas.grab().isNull()


def test_desktop_constructor_and_save_refuse_layout_symlinks(workbench, qt, tmp_path):
    from sciplot_core.panel_assembly.desktop import AssemblyWindow
    from sciplot_core.panel_assembly.errors import AssemblyError

    window = workbench
    target = tmp_path / "original.json"
    assert window.save_layout(target)
    before = target.read_bytes()
    alias = tmp_path / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(AssemblyError, match="symbolic links") as error:
        AssemblyWindow(alias)
    assert error.value.code == "assembly_file_conflict"
    assert window.apply([{"op": "set_spacing", "gap_x_mm": 8, "gap_y_mm": 7}])
    document = window.document
    assert not window.save_layout(alias)
    assert "Save failed" in window.status.text()
    assert window.path == target and target.read_bytes() == before and alias.is_symlink()
    with pytest.raises(AssemblyError, match="symbolic links"):
        window.load_layout(alias)
    assert window.document == document
    dangling_target = tmp_path / "uncreated.json"
    dangling = tmp_path / "dangling.json"
    dangling.symlink_to(dangling_target)
    assert not window.save_layout(dangling)
    assert dangling.is_symlink() and not dangling_target.exists()
    assert target.read_bytes() == before
