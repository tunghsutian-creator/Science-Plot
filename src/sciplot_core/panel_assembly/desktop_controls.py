"""Physical page and selected-panel controls for the assembly window."""

from PyQt6 import QtCore, QtWidgets


def number(name, *, integer=False, minimum=0, maximum=1000):
    box = QtWidgets.QSpinBox() if integer else QtWidgets.QDoubleSpinBox()
    box.setObjectName(name)
    box.setRange(minimum, maximum)
    if not integer:
        box.setDecimals(2)
        box.setSingleStep(0.5)
    return box


class LayoutControls(QtWidgets.QWidget):
    operationsRequested = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        form = QtWidgets.QFormLayout(self)
        self.rows = number("rows", integer=True, minimum=1, maximum=16)
        self.columns = number("columns", integer=True, minimum=1, maximum=16)
        self.width = number("widthMm", minimum=10, maximum=2000)
        self.height = number("heightMm", minimum=10, maximum=2000)
        self.gap_x = number("gapXMm", maximum=200)
        self.gap_y = number("gapYMm", maximum=200)
        for label, box in (("Rows", self.rows), ("Columns", self.columns), ("Page width (mm)", self.width),
                           ("Page height (mm)", self.height), ("Horizontal gap (mm)", self.gap_x),
                           ("Vertical gap (mm)", self.gap_y)):
            form.addRow(label, box)
        self.apply_button = QtWidgets.QPushButton("Apply page and grid")
        self.apply_button.setObjectName("applyLayout")
        form.addRow(self.apply_button)
        self.apply_button.clicked.connect(self._apply)

    def _apply(self):
        self.operationsRequested.emit([
            {"op": "set_grid", "rows": self.rows.value(), "columns": self.columns.value()},
            {"op": "set_page", "width_mm": self.width.value(), "height_mm": self.height.value()},
            {"op": "set_spacing", "gap_x_mm": self.gap_x.value(), "gap_y_mm": self.gap_y.value()}])

    def set_document(self, document):
        layout = document["layout"]
        for key, box in (("rows", self.rows), ("columns", self.columns), ("width_mm", self.width),
                         ("height_mm", self.height), ("gap_x_mm", self.gap_x), ("gap_y_mm", self.gap_y)):
            box.setValue(layout[key])


class PanelControls(QtWidgets.QWidget):
    operationsRequested = QtCore.pyqtSignal(object)
    cropModeChanged = QtCore.pyqtSignal(bool)
    replaceRequested = QtCore.pyqtSignal()
    refreshRequested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.identifier = ""
        form = QtWidgets.QFormLayout(self)
        self.title = QtWidgets.QLabel("Select a panel")
        self.title.setWordWrap(True)
        form.addRow(self.title)
        self.row_span = number("rowSpan", integer=True, minimum=1, maximum=16)
        self.column_span = number("columnSpan", integer=True, minimum=1, maximum=16)
        form.addRow("Row span", self.row_span)
        form.addRow("Column span", self.column_span)
        self.label = QtWidgets.QLineEdit()
        self.label.setObjectName("panelLabel")
        self.label.setMaxLength(16)
        self.label.setPlaceholderText("Automatic a, b, c…")
        form.addRow("Panel letter", self.label)
        self.apply_button = QtWidgets.QPushButton("Apply panel settings")
        self.apply_button.setObjectName("applyPanel")
        form.addRow(self.apply_button)
        self.crop_mode = QtWidgets.QCheckBox("Crop selected image by dragging")
        self.crop_mode.setObjectName("cropMode")
        form.addRow(self.crop_mode)
        self.crop_values = [number(name, maximum=1) for name in ("cropLeft", "cropTop", "cropRight", "cropBottom")]
        for box in self.crop_values:
            box.setDecimals(4)
            box.setSingleStep(0.01)
        for label, box in zip(("Crop left (0–1)", "Crop top (0–1)", "Crop right (0–1)", "Crop bottom (0–1)"), self.crop_values, strict=True):
            form.addRow(label, box)
        self.crop_apply = QtWidgets.QPushButton("Apply crop")
        self.crop_apply.setObjectName("applyCrop")
        self.crop_reset = QtWidgets.QPushButton("Reset crop")
        form.addRow(self.crop_apply)
        form.addRow(self.crop_reset)
        self.replace_button = QtWidgets.QPushButton("Replace with selected library source")
        self.replace_button.setObjectName("replacePanel")
        self.refresh_button = QtWidgets.QPushButton("Use current source version")
        self.refresh_button.setObjectName("refreshSource")
        self.remove_button = QtWidgets.QPushButton("Remove panel")
        self.remove_button.setObjectName("removePanel")
        for button in (self.replace_button, self.refresh_button, self.remove_button):
            form.addRow(button)
        self.apply_button.clicked.connect(self._apply)
        self.crop_mode.toggled.connect(self.cropModeChanged)
        self.crop_apply.clicked.connect(lambda: self._crop([box.value() for box in self.crop_values]))
        self.crop_reset.clicked.connect(lambda: self._crop(None))
        self.replace_button.clicked.connect(self.replaceRequested)
        self.refresh_button.clicked.connect(self.refreshRequested)
        self.remove_button.clicked.connect(lambda: self.operationsRequested.emit([{"op": "remove_panel", "id": self.identifier}]))
        self.setEnabled(False)

    def _apply(self):
        self.operationsRequested.emit([
            {"op": "set_span", "id": self.identifier, "row_span": self.row_span.value(), "column_span": self.column_span.value()},
            {"op": "set_label", "id": self.identifier, "label": self.label.text() or None}])

    def _crop(self, crop):
        self.operationsRequested.emit([{"op": "set_crop", "id": self.identifier, "crop": crop}])

    def set_panel(self, panel, title=""):
        self.setEnabled(panel is not None)
        if panel is None:
            self.identifier = ""
            self.title.setText("Select a panel")
            return
        self.identifier = panel["id"]
        self.title.setText(title)
        self.row_span.setValue(panel["row_span"])
        self.column_span.setValue(panel["column_span"])
        self.label.setText(panel.get("label") or "")
        image = panel["source"]["kind"] == "image"
        self.crop_mode.setEnabled(image)
        if not image:
            self.crop_mode.setChecked(False)
        for box, value in zip(self.crop_values, panel.get("crop") or [0, 0, 1, 1], strict=True):
            box.setEnabled(image)
            box.setValue(value)
        self.crop_apply.setEnabled(image)
        self.crop_reset.setEnabled(image)
