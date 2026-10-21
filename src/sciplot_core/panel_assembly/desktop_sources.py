"""Explicit source selection and disposable thumbnails for assembly."""

from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from .desktop_jobs import AssemblyJob


def project_choices(project):
    """Source owner selects current native or canonical managed authority."""
    from .sources import project_references

    return project_references(Path(project))


def managed_choice(project):
    from sciplot_core.plot_engine.storage import load_head

    root = Path(project).expanduser().resolve()
    document = load_head(root)["document"]
    if document.get("plot_type") != "ManagedPlot":
        raise ValueError("Choose a canonical ManagedPlot directory containing head.json.")
    identifier = document["plot_id"]
    return [(f"Managed / {identifier}", {"kind": "managed", "project": str(root), "plot_id": identifier})]


def source_title(source):
    if source["kind"] == "image":
        return Path(source["path"]).name
    identifier = source.get("figure_id") or source.get("plot_id")
    return f"{Path(source['project']).name}\n{identifier.replace('_', ' ')}"


def source_reference(source):
    return {key: value for key, value in source.items() if key != "binding"}


class SourceLibrary(QtWidgets.QWidget):
    sourceRequested = QtCore.pyqtSignal(object)
    message = QtCore.pyqtSignal(str)
    busyChanged = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._job = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("SOURCE LIBRARY"))
        hint = QtWidgets.QLabel("Select saved figures from several projects, or add an image / diagram.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.project_button = QtWidgets.QPushButton("Add project…")
        self.project_button.setObjectName("addProject")
        self.managed_button = QtWidgets.QPushButton("Add managed plot…")
        self.image_button = QtWidgets.QPushButton("Add image / diagram…")
        self.image_button.setObjectName("addImage")
        for button in (self.project_button, self.managed_button, self.image_button):
            layout.addWidget(button)
        self.items = QtWidgets.QListWidget()
        self.items.setObjectName("sourceLibrary")
        self.items.setWordWrap(True)
        layout.addWidget(self.items, 1)
        self.add_button = QtWidgets.QPushButton("Add selected panel")
        self.add_button.setObjectName("addSelectedPanel")
        self.add_button.setEnabled(False)
        layout.addWidget(self.add_button)
        self.project_button.clicked.connect(self._project_dialog)
        self.managed_button.clicked.connect(self._managed_dialog)
        self.image_button.clicked.connect(self._image_dialog)
        self.items.itemSelectionChanged.connect(lambda: self.add_button.setEnabled(self.reference() is not None))
        self.items.itemDoubleClicked.connect(lambda _item: self._request())
        self.add_button.clicked.connect(self._request)

    @property
    def busy(self):
        return self._job is not None

    def reference(self):
        item = self.items.currentItem()
        return item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None

    def add_choices(self, choices):
        existing = [self.items.item(i).data(QtCore.Qt.ItemDataRole.UserRole) for i in range(self.items.count())]
        for title, reference in choices:
            if reference in existing:
                continue
            item = QtWidgets.QListWidgetItem(title)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, reference)
            item.setToolTip(str(reference.get("path") or reference.get("project")))
            self.items.addItem(item)
            existing.append(reference)
            self.items.setCurrentItem(item)

    def load_project(self, path, *, managed=False):
        if self.busy:
            return False
        self.message.emit("Reading saved figure catalogue…")
        self._job = AssemblyJob(lambda: managed_choice(path) if managed else project_choices(path), self)
        self._job.succeeded.connect(self.add_choices)
        self._job.failed.connect(self.message)
        self._job.finished.connect(self._finished)
        self.busyChanged.emit(True)
        self._job.start()
        return True

    def _finished(self):
        self._job.deleteLater()
        self._job = None
        self.busyChanged.emit(False)

    def _request(self):
        reference = self.reference()
        if reference is not None:
            self.sourceRequested.emit(reference)

    def _project_dialog(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select saved SciPlot project")
        if path:
            self.load_project(path)

    def _managed_dialog(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select managed document directory (head.json)")
        if path:
            self.load_project(path, managed=True)

    def _image_dialog(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add SEM image, photograph or diagram", "",
            "Images and diagrams (*.png *.jpg *.jpeg *.tif *.tiff *.pdf);;All files (*)")
        self.add_choices([(Path(path).name, {"kind": "image", "path": path}) for path in paths])
