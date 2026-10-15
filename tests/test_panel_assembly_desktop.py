"""Actual Qt events exercise local assembly without a plotting service."""

from pathlib import Path
import threading
import time

import pytest


@pytest.fixture(scope="module")
def qt():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6 import QtCore, QtTest

    app = widgets.QApplication.instance() or widgets.QApplication([])
    yield app, QtCore, QtTest, widgets


@pytest.fixture
def workbench(qt):
    from sciplot_core.panel_assembly.desktop import AssemblyWindow

    window = AssemblyWindow()
    window.show()
    qt[2].QTest.qWait(60)
    yield window
    settle(window, qt)
    window._saved_document = window.document
    window.close()
    window.deleteLater()
    qt[0].processEvents()


def settle(window, qt, *, timeout=10):
    deadline = time.monotonic() + timeout
    while window.busy or (hasattr(window, "previews") and window.previews.busy):
        assert time.monotonic() < deadline, "Native UI worker did not finish"
        qt[2].QTest.qWait(10)
    qt[0].processEvents()


def image(tmp_path, name="microscopy.png", color="#8ca1b5"):
    from PyQt6 import QtGui

    path = tmp_path / name
    pixels = QtGui.QImage(360, 240, QtGui.QImage.Format.Format_RGB32)
    pixels.fill(QtGui.QColor(color))
    assert pixels.save(str(path))
    return path


def add_image(window, qt, path):
    window.library.add_choices([(path.name, {"kind": "image", "path": str(path)})])
    qt[2].QTest.mouseClick(window.library.add_button, qt[1].Qt.MouseButton.LeftButton)
    settle(window, qt)
    return window.selected


def drag(qt, canvas, start, end):
    qt[2].QTest.mousePress(canvas, qt[1].Qt.MouseButton.LeftButton, pos=start.toPoint())
    qt[2].QTest.mouseMove(canvas, end.toPoint(), 30)
    qt[2].QTest.mouseRelease(canvas, qt[1].Qt.MouseButton.LeftButton, pos=end.toPoint())
    qt[0].processEvents()


def test_actual_qt_drag_swap_gap_span_labels_and_undo(workbench, qt, tmp_path, monkeypatch):
    from PyQt6 import QtGui
    from sciplot_core.panel_assembly import preview, sources

    window = workbench
    first = add_image(window, qt, image(tmp_path))
    second = add_image(window, qt, image(tmp_path, "diagram.png", "#c8d9b8"))
    assert len(window.document["panels"]) == 2

    def no_source_call(*_args, **_kwargs):
        pytest.fail("Layout gestures must not capture, rebind or inspect scientific sources")

    monkeypatch.setattr(sources, "capture_source", no_source_call)
    monkeypatch.setattr(sources, "assert_source_current", no_source_call)
    monkeypatch.setattr(preview, "render_preview", no_source_call)
    drag(qt, window.canvas, window.canvas.panel_rect(first).center(), window.canvas.panel_rect(second).center())
    by_id = {p["id"]: p for p in window.document["panels"]}
    assert by_id[first]["column"] == 1 and by_id[second]["column"] == 0
    qt[2].QTest.keySequence(window.canvas, QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Undo))
    qt[0].processEvents()
    assert next(p for p in window.document["panels"] if p["id"] == first)["column"] == 0
    toolbar = window.findChild(qt[3].QToolBar)
    qt[2].QTest.mouseClick(toolbar.widgetForAction(window.actions["redo"]), qt[1].Qt.MouseButton.LeftButton)
    assert next(p for p in window.document["panels"] if p["id"] == first)["column"] == 1
    qt[2].QTest.mouseClick(toolbar.widgetForAction(window.actions["undo"]), qt[1].Qt.MouseButton.LeftButton)
    assert next(p for p in window.document["panels"] if p["id"] == first)["column"] == 0
    qt[2].QTest.mouseClick(toolbar.widgetForAction(window.actions["redo"]), qt[1].Qt.MouseButton.LeftButton)
    layout = window.layout_controls
    layout.gap_x.setValue(7.5)
    layout.gap_y.setValue(4.5)
    layout.width.setValue(190)
    layout.height.setValue(150)
    qt[2].QTest.mouseClick(layout.apply_button, qt[1].Qt.MouseButton.LeftButton)
    assert window.document["layout"]["gap_x_mm"] == 7.5
    assert window.document["layout"]["gap_y_mm"] == 4.5
    window.select_panel(first)
    window.panel_controls.row_span.setValue(2)
    window.panel_controls.automatic_label.setChecked(False)
    window.panel_controls.label.setText("B")
    qt[2].QTest.mouseClick(window.panel_controls.apply_button, qt[1].Qt.MouseButton.LeftButton)
    panel = next(p for p in window.document["panels"] if p["id"] == first)
    assert panel["row_span"] == 2 and panel["label"] == "B"
    before = window.document
    window.panel_controls.column_span.setValue(2)
    qt[2].QTest.mouseClick(window.panel_controls.apply_button, qt[1].Qt.MouseButton.LeftButton)
    assert window.document == before, "An invalid overlapping span must be atomic"
    assert window.status.text()
    screenshot(window, "layout-grid.png")


def test_actual_qt_image_crop_save_open_and_replace_preserve_layout(workbench, qt, tmp_path):
    window = workbench
    original = image(tmp_path)
    before_bytes = original.read_bytes()
    identifier = add_image(window, qt, original)
    qt[2].QTest.mouseClick(window.panel_controls.crop_mode, qt[1].Qt.MouseButton.LeftButton)
    rectangle = window.canvas.image_rect(identifier)
    start = rectangle.topLeft() + qt[1].QPointF(rectangle.width() * 0.15, rectangle.height() * 0.2)
    end = rectangle.topLeft() + qt[1].QPointF(rectangle.width() * 0.8, rectangle.height() * 0.9)
    drag(qt, window.canvas, start, end)
    panel = window.document["panels"][0]
    assert panel["crop"] == pytest.approx([0.15, 0.2, 0.8, 0.9], abs=0.015)
    assert original.read_bytes() == before_bytes
    target = tmp_path / "editable-layout.json"
    assert window.save_layout(target)
    saved = window.document
    qt[2].QTest.mouseClick(window.panel_controls.crop_reset, qt[1].Qt.MouseButton.LeftButton)
    assert window.document["panels"][0]["crop"] is None
    window.load_layout(target)
    settle(window, qt)
    assert window.document == saved
    window.select_panel(identifier)
    replacement = image(tmp_path, "replacement.png", "#dba37b")
    window.library.add_choices([(replacement.name, {"kind": "image", "path": str(replacement)})])
    qt[2].QTest.mouseClick(window.panel_controls.replace_button, qt[1].Qt.MouseButton.LeftButton)
    settle(window, qt)
    updated = window.document["panels"][0]
    for field in ("id", "row", "column", "row_span", "column_span", "label"):
        assert updated[field] == panel[field]
    assert Path(updated["source"]["path"]) == replacement
    assert original.read_bytes() == before_bytes
    screenshot(window, "crop-replacement.png")


def test_source_conflict_requires_explicit_refresh_and_save_conflict_is_visible(workbench, qt, tmp_path):
    from sciplot_core.panel_assembly import model

    window = workbench
    path = image(tmp_path)
    identifier = add_image(window, qt, path)
    frozen = window.document["panels"][0]["source"]
    image(tmp_path, color="#a471c8")
    window.actions["check"].trigger()
    settle(window, qt)
    assert identifier in window.conflicts
    assert window.document["panels"][0]["source"] == frozen
    qt[2].QTest.mouseClick(window.panel_controls.refresh_button, qt[1].Qt.MouseButton.LeftButton)
    settle(window, qt)
    assert identifier not in window.conflicts
    assert window.document["panels"][0]["source"] != frozen
    target = tmp_path / "assembly.json"
    assert window.save_layout(target)
    external = model.apply_operations(window.document, [{"op": "set_label", "id": identifier, "label": "X"}])
    model.save_document(external, target, expected_revision=window.document["revision"])
    external_bytes = target.read_bytes()
    assert not window.save_layout(target)
    assert "Save failed" in window.status.text()
    assert target.read_bytes() == external_bytes


def test_export_runs_off_ui_thread_and_retains_snapshot(workbench, qt, tmp_path, monkeypatch):
    from sciplot_core.panel_assembly import export

    window = workbench
    add_image(window, qt, image(tmp_path))
    expected = window.document
    calls, pulses, results = [], [], []
    main_thread = threading.get_ident()

    def exporting(document, out, *, dpi):
        calls.append((document, out, dpi, threading.get_ident()))
        time.sleep(0.16)
        return {"status": "ready", "out": str(out)}

    monkeypatch.setattr(export, "export_document", exporting)
    timer = qt[1].QTimer()
    timer.timeout.connect(lambda: pulses.append(1))
    timer.start(5)
    window.exportFinished.connect(results.append)
    assert window.export_to(tmp_path / "new-package", dpi=600)
    assert not window.apply([{"op": "set_spacing", "gap_x_mm": 9, "gap_y_mm": 9}])
    settle(window, qt)
    timer.stop()
    assert len(pulses) >= 5
    assert calls[0][:3] == (expected, tmp_path / "new-package", 600)
    assert calls[0][3] != main_thread
    assert results == [{"status": "ready", "out": str(tmp_path / "new-package")}]


def screenshot(window, name):
    import os

    output = os.environ.get("SCIPLOT_ASSEMBLY_QT_EVIDENCE")
    if output:
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(target / name))


def test_source_library_actual_catalogues_across_projects(qt, tmp_path):
    from sciplot_core.panel_assembly.desktop_sources import SourceLibrary

    library = SourceLibrary()
    library.resize(340, 620)
    library.show()
    requests = []
    library.sourceRequested.connect(requests.append)
    projects = [tmp_path / "Project A", tmp_path / "Project B"]
    try:
        for project in projects:
            (project / "studio").mkdir(parents=True)
            (project / "plot_request.json").write_text("{}")
            (project / "studio/document.vsz").write_text("# Existing saved native document\n")
            (project / "studio/spec.json").write_text("{}")
            assert library.load_project(project)
            settle(library, qt)
        assert library.items.count() == 2
        for index, project in enumerate(projects):
            library.items.setCurrentRow(index)
            qt[2].QTest.mouseClick(library.add_button, qt[1].Qt.MouseButton.LeftButton)
            assert requests[-1] == {"kind": "project", "project": str(project), "figure_id": "primary"}
        screenshot(library, "cross-project-source-selection.png")
    finally:
        library.close()
        library.deleteLater()


@pytest.mark.comprehensive
def test_qt_selects_two_projects_and_managed_plot_then_exports_native_mix(workbench, qt, tmp_path, monkeypatch):
    import pymupdf
    from test_panel_assembly_export import managed_source
    from test_task_papers_native import _projects
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plot_engine.storage import load_head

    window = workbench
    raw, projects = _projects(tmp_path)
    managed, _bound = managed_source(tmp_path)
    photo = image(tmp_path, "micrograph.png", "#87aaba")
    protected = [*raw, photo, *(project / "studio/document.vsz" for project in projects),
                 *(project / "studio/spec.json" for project in projects)]
    originals = {path: file_sha256(path) for path in protected}
    canonical = load_head(managed)
    controls = window.layout_controls
    controls.width.setValue(230)
    controls.height.setValue(200)
    qt[2].QTest.mouseClick(controls.apply_button, qt[1].Qt.MouseButton.LeftButton)

    for project in projects:
        assert window.library.load_project(project)
        settle(window, qt, timeout=30)
        qt[2].QTest.mouseClick(window.library.add_button, qt[1].Qt.MouseButton.LeftButton)
        settle(window, qt, timeout=30)
    assert window.library.load_project(managed, managed=True)
    settle(window, qt)
    assert window.library.reference()["plot_id"] == canonical["document"]["plot_id"]
    qt[2].QTest.mouseClick(window.library.add_button, qt[1].Qt.MouseButton.LeftButton)
    settle(window, qt, timeout=30)
    window.library.add_choices([(photo.name, {"kind": "image", "path": str(photo)})])
    qt[2].QTest.mouseClick(window.library.add_button, qt[1].Qt.MouseButton.LeftButton)
    settle(window, qt)
    assert [panel["source"]["kind"] for panel in window.document["panels"]] == ["project", "project", "managed", "image"]
    assert all(not window.previews.get(panel["source"]).isNull() for panel in window.document["panels"])
    for box, value in zip(window.panel_controls.crop_values, [.1, .1, .9, .9], strict=True):
        box.setValue(value)
    qt[2].QTest.mouseClick(window.panel_controls.crop_apply, qt[1].Qt.MouseButton.LeftButton)

    layout = tmp_path / "saved-layout.json"
    out = tmp_path / "gui-native-package"
    monkeypatch.setattr(qt[3].QFileDialog, "getSaveFileName", lambda _parent, title, *_args:
                        (str(out if title.startswith("New export") else layout), ""))
    toolbar = window.findChild(qt[3].QToolBar)
    qt[2].QTest.mouseClick(toolbar.widgetForAction(window.actions["save"]), qt[1].Qt.MouseButton.LeftButton)
    assert layout.is_file() and not window.dirty
    results = []
    window.exportFinished.connect(results.append)
    qt[2].QTest.mouseClick(toolbar.widgetForAction(window.actions["export"]), qt[1].Qt.MouseButton.LeftButton)
    settle(window, qt, timeout=45)
    # The FTIR source has a data-anchored inline label at its lower axis bound.
    # Refuse actual target-size clipping; preserve all source bytes and the
    # destination until the user explicitly removes that unsupported panel.
    assert not results
    assert "clip" in window.status.text()
    assert "assembly_native_qa_failed" in window.status.toolTip()
    assert not out.exists()
    screenshot(window, "native-bounds-refusal.png")
    rejected = window.document["panels"][1]["id"]
    qt[2].QTest.mouseClick(window.canvas, qt[1].Qt.MouseButton.LeftButton,
                         pos=window.canvas.panel_rect(rejected).center().toPoint())
    qt[2].QTest.mouseClick(window.panel_controls.remove_button, qt[1].Qt.MouseButton.LeftButton)
    qt[2].QTest.mouseClick(toolbar.widgetForAction(window.actions["save"]), qt[1].Qt.MouseButton.LeftButton)
    qt[2].QTest.mouseClick(toolbar.widgetForAction(window.actions["export"]), qt[1].Qt.MouseButton.LeftButton)
    settle(window, qt, timeout=45)
    assert results, window.status.text()
    result = results[0]
    assert result["status"] == "complete"
    assert result["source_currentness"] == "passed"
    assert all(Path(result[key]).is_file() for key in ("pdf", "tiff", "layout", "manifest"))
    scientific = [panel for panel in result["panels"] if panel["evidence"]["authority"] != "image_bytes"]
    assert len(scientific) == 2
    for panel in scientific:
        assert panel["evidence"]["physical_size"]["scale"] == 1
        assert panel["evidence"]["publication_qa"]["native_text_checked"]
        assert panel["evidence"]["publication_qa"]["status"] == "passed"
    assert load_head(managed) == canonical
    assert not Path(canonical["binding"]["document"]).exists()
    assert {path: file_sha256(path) for path in protected} == originals
    with pymupdf.open(result["pdf"]) as pdf:
        assert pdf[0].rect.width * 25.4 / 72 == pytest.approx(230, abs=.001)
        assert pdf[0].rect.height * 25.4 / 72 == pytest.approx(200, abs=.001)
        assert "Wavelength" in pdf[0].get_text()
    screenshot(window, "native-project-managed-mix.png")
