"""Native local figure assembly: source selection, physical layout and export."""

from pathlib import Path
from uuid import uuid4

from PyQt6 import QtCore, QtGui, QtWidgets

from . import model
from .desktop_canvas import AssemblyCanvas
from .desktop_controls import LayoutControls, PanelControls
from .desktop_jobs import AssemblyJob
from .desktop_messages import display_message
from .desktop_previews import SourcePreviews, preview_key
from .desktop_sources import SourceLibrary, source_reference, source_title
from .history import AssemblyHistory


class AssemblyWindow(QtWidgets.QMainWindow):
    exportFinished = QtCore.pyqtSignal(object)

    def __init__(self, layout_path=None, parent=None):
        super().__init__(parent)
        self.path = Path(layout_path).expanduser().resolve() if layout_path else None
        document = model.load_document(self.path) if self.path else model.new_document()
        self.history = AssemblyHistory(document)
        self._saved_document = document
        self._saved_revision = document["revision"] if self.path else None
        self._job = None
        self.selected = ""
        self.conflicts = {}
        self.setObjectName("panelAssemblyWorkbench")
        self.resize(1280, 860)
        self._build()
        self._render()
        if document["panels"]:
            QtCore.QTimer.singleShot(0, self.check_sources)

    @property
    def document(self):
        return self.history.document

    @property
    def dirty(self):
        return self._saved_document != self.document

    @property
    def busy(self):
        return self._job is not None or self.library.busy

    def _build(self):
        self.previews = SourcePreviews(self)
        self.canvas = AssemblyCanvas(self.previews, self)
        self.previews.updated.connect(lambda _key: self.canvas.update())
        self.previews.failed.connect(self._preview_failed)
        self.setCentralWidget(self.canvas)
        self.library = SourceLibrary(self)
        self._dock("Sources", self.library, QtCore.Qt.DockWidgetArea.LeftDockWidgetArea)
        right = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(right)
        self.layout_controls = LayoutControls()
        self.panel_controls = PanelControls()
        for name, widget in (("Page & grid", self.layout_controls), ("Selected panel", self.panel_controls)):
            group = QtWidgets.QGroupBox(name)
            group_layout = QtWidgets.QVBoxLayout(group)
            group_layout.addWidget(widget)
            layout.addWidget(group)
        layout.addStretch()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(right)
        self._dock("Layout", scroll, QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
        toolbar = self.addToolBar("Assembly")
        toolbar.setMovable(False)
        self.actions = {}
        for name, title, shortcut, callback in (
            ("new", "New", QtGui.QKeySequence.StandardKey.New, self.new_layout),
            ("open", "Open…", QtGui.QKeySequence.StandardKey.Open, self._open_dialog),
            ("save", "Save", QtGui.QKeySequence.StandardKey.Save, self._save_dialog),
            ("undo", "Undo", QtGui.QKeySequence.StandardKey.Undo, self.undo),
            ("redo", "Redo", QtGui.QKeySequence.StandardKey.Redo, self.redo),
            ("check", "Check sources", None, self.check_sources),
            ("export", "Export PDF / TIFF / editable layout…", None, self._export_dialog),
        ):
            action = toolbar.addAction(title)
            action.setObjectName(name + "Action")
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.actions[name] = action
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.statusBar().addWidget(self.status, 1)
        self.status.setText("Drag whole panels to move or swap. Images keep their aspect ratio.")
        self.library.message.connect(self._message)
        self.library.sourceRequested.connect(self.add_source)
        self.layout_controls.operationsRequested.connect(self.apply)
        self.panel_controls.operationsRequested.connect(self.apply)
        self.panel_controls.cropModeChanged.connect(self._crop_mode)
        self.panel_controls.replaceRequested.connect(self.replace_selected)
        self.panel_controls.refreshRequested.connect(self.refresh_selected)
        self.canvas.panelSelected.connect(self.select_panel)
        self.canvas.panelMoved.connect(lambda identifier, row, column: self.apply([
            {"op": "move_panel", "id": identifier, "row": row, "column": column, "swap": True}]))
        self.canvas.panelCropped.connect(lambda identifier, crop: self.apply([
            {"op": "set_crop", "id": identifier, "crop": crop}]))
        self.canvas.undoRequested.connect(self.undo)
        self.canvas.redoRequested.connect(self.redo)
        self.canvas.removeRequested.connect(lambda identifier: self.apply([{"op": "remove_panel", "id": identifier}]))

    def _dock(self, title, widget, area):
        dock = QtWidgets.QDockWidget(title, self)
        dock.setObjectName(title.lower() + "Dock")
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setWidget(widget)
        dock.setMinimumWidth(250)
        self.addDockWidget(area, dock)

    def _message(self, message):
        self.status.setToolTip(message)
        self.status.setText(display_message(message))

    def _preview_failed(self, key, message):
        if any(preview_key(panel["source"]) == key for panel in self.document["panels"]):
            self._message("Preview unavailable: " + message)

    def _render(self):
        document = self.document
        ids = {panel["id"] for panel in document["panels"]}
        self.conflicts = {key: value for key, value in self.conflicts.items() if key in ids}
        if self.selected not in ids:
            self.selected = ""
        self.canvas.conflicts = self.conflicts
        self.canvas.set_document(document, self.selected)
        self.previews.request_document(document)
        self.layout_controls.set_document(document)
        panel = next((item for item in document["panels"] if item["id"] == self.selected), None)
        self.panel_controls.set_panel(panel, source_title(panel["source"]) if panel else "")
        for name in ("new", "open", "check", "export"):
            self.actions[name].setEnabled(not self.busy)
        self.actions["undo"].setEnabled(self.history.can_undo and not self.busy)
        self.actions["redo"].setEnabled(self.history.can_redo and not self.busy)
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{self.path.name if self.path else 'Untitled'} — SciPlot Figure Assembly")

    def select_panel(self, identifier):
        self.selected = identifier
        self._render()

    def _crop_mode(self, enabled):
        self.canvas.crop_mode = enabled
        self.canvas.setCursor(QtCore.Qt.CursorShape.CrossCursor if enabled else QtCore.Qt.CursorShape.ArrowCursor)

    def apply(self, operations):
        if self.busy:
            return False
        try:
            self.history.apply(operations)
        except (ValueError, RuntimeError) as exc:
            self._message(str(exc))
            self._render()
            return False
        self._render()
        self._message("Layout updated locally. Native sources reflow at their target size on export.")
        return True

    def undo(self):
        if not self.busy and self.history.can_undo:
            self.history.undo()
            self._render()

    def redo(self):
        if not self.busy and self.history.can_redo:
            self.history.redo()
            self._render()

    def _start(self, operation, callback, message):
        if self.busy:
            return False
        self._message(message)
        self._job = AssemblyJob(operation, self)
        self._job.succeeded.connect(lambda result: self._complete(callback, result))
        self._job.failed.connect(self._message)
        self._job.finished.connect(self._finished)
        self._job.start()
        self._render()
        return True

    def _complete(self, callback, result):
        try:
            callback(result)
        except (OSError, ValueError, RuntimeError) as exc:
            self._message(str(exc))

    def _finished(self):
        self._job.deleteLater()
        self._job = None
        self._render()

    def add_source(self, reference):
        from .sources import capture_source

        def complete(source):
            identifier = uuid4().hex
            document = self.document
            occupied = {(row, column) for panel in document["panels"]
                        for row in range(panel["row"], panel["row"] + panel["row_span"])
                        for column in range(panel["column"], panel["column"] + panel["column_span"])}
            cell = next(((r, c) for r in range(document["layout"]["rows"])
                         for c in range(document["layout"]["columns"]) if (r, c) not in occupied), None)
            if cell is None:
                self._message("The grid is full. Increase rows or columns before adding a panel.")
                return
            self.history.apply([{"op": "add_panel", "panel": {"id": identifier, "source": source,
                                "row": cell[0], "column": cell[1], "row_span": 1, "column_span": 1,
                                "label": None, "crop": None}}])
            self.selected = identifier
            self._message("Panel added from the selected source version.")

        return self._start(lambda: capture_source(reference), complete, "Reading selected source version…")

    def _replace(self, reference):
        from .sources import capture_source

        identifier = self.selected
        if not identifier or reference is None:
            self._message("Select a panel and its replacement in the source library.")
            return False

        def complete(source):
            self.history.apply([{"op": "replace_panel", "id": identifier, "source": source}])
            self.previews.retry(source)
            self.conflicts.pop(identifier, None)
            self._message("Panel source replaced. Its position, span and letter are retained.")

        return self._start(lambda: capture_source(reference), complete, "Reading replacement source version…")

    def replace_selected(self):
        return self._replace(self.library.reference())

    def refresh_selected(self):
        panel = next((p for p in self.document["panels"] if p["id"] == self.selected), None)
        return self._replace(source_reference(panel["source"])) if panel else False

    def check_sources(self):
        from .sources import assert_source_current

        document = self.document

        def check():
            conflicts = {}
            for panel in document["panels"]:
                try:
                    assert_source_current(panel["source"])
                except (ValueError, RuntimeError) as exc:
                    conflicts[panel["id"]] = str(exc)
            return conflicts

        def complete(conflicts):
            self.conflicts = conflicts
            self._message("Source conflicts: " + "; ".join(conflicts.values()) if conflicts else "All selected source versions are current.")

        return self._start(check, complete, "Checking selected source versions…")

    def save_layout(self, path):
        target = Path(path).expanduser().resolve()
        expected = self._saved_revision if target == self.path else None
        try:
            model.save_document(self.document, target, expected_revision=expected)
        except (OSError, ValueError, RuntimeError) as exc:
            self._message(f"Save failed: {exc}")
            return False
        self.path, self._saved_document = target, self.document
        self._saved_revision = self.document["revision"]
        self._render()
        self._message(f"Saved editable layout: {target}")
        return True

    def _save_dialog(self):
        path = str(self.path) if self.path else QtWidgets.QFileDialog.getSaveFileName(
            self, "Save editable assembly layout", "figure-assembly.json", "Assembly layout (*.json)")[0]
        return self.save_layout(path) if path else False

    def _discard_guard(self):
        if self.busy or self.previews.busy:
            self._message("Wait for the current source or export operation to finish.")
            return False
        if not self.dirty:
            return True
        answer = QtWidgets.QMessageBox.question(self, "Unsaved assembly", "Save layout changes before continuing?",
            QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Save)
        return self._save_dialog() if answer == QtWidgets.QMessageBox.StandardButton.Save else answer == QtWidgets.QMessageBox.StandardButton.Discard

    def load_layout(self, path):
        document = model.load_document(path)
        self.path = Path(path).expanduser().resolve()
        self.history = AssemblyHistory(document)
        self._saved_document, self._saved_revision = document, document["revision"]
        self.selected, self.conflicts = "", {}
        self._render()
        self.check_sources()

    def _open_dialog(self):
        if self._discard_guard():
            path = QtWidgets.QFileDialog.getOpenFileName(self, "Open assembly layout", "", "Assembly layout (*.json)")[0]
            if path:
                try:
                    self.load_layout(path)
                except (OSError, ValueError, RuntimeError) as exc:
                    self._message(f"Open failed: {exc}")

    def new_layout(self):
        if self._discard_guard():
            self.path, self._saved_revision = None, None
            self.history = AssemblyHistory(model.new_document())
            self._saved_document = self.document
            self.selected, self.conflicts = "", {}
            self._render()

    def export_to(self, out, *, dpi=300):
        from .export import export_document

        snapshot = self.document
        return self._start(lambda: export_document(snapshot, Path(out), dpi=dpi),
                           self._export_complete, "Exporting native panels at their physical target sizes…")

    def _export_complete(self, result):
        self._message(f"Export finished: {result.get('out', result.get('output', 'PDF, TIFF and editable layout saved'))}")
        self.exportFinished.emit(result)

    def _export_dialog(self):
        path = QtWidgets.QFileDialog.getSaveFileName(self, "New export package directory", "assembled-figure", "Package directory (*)")[0]
        if path:
            self.export_to(path)

    def closeEvent(self, event):
        event.accept() if self._discard_guard() else event.ignore()


def open_workbench(layout_path: Path | None = None) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = AssemblyWindow(layout_path)
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()
