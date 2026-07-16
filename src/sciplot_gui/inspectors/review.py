from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.canvas.annotations import (
    PROMOTABLE_ANNOTATION_SHAPES,
    ReviewAnnotation,
    ReviewAnnotationStyle,
)


_SHAPE_LABELS = {
    "text": "Note",
    "arrow": "Arrow",
    "rectangle": "Rectangle",
    "ellipse": "Ellipse",
    "freehand": "Pen",
}


class ReviewInspectorPanel(QtWidgets.QFrame):
    """Discoverable review tools for the non-exported annotation sidecar."""

    toolChanged = QtCore.pyqtSignal(str)
    annotationSelected = QtCore.pyqtSignal(str)
    updateRequested = QtCore.pyqtSignal(str, object)
    promoteRequested = QtCore.pyqtSignal(str)
    removeRequested = QtCore.pyqtSignal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewInspector")
        self._annotations: dict[str, ReviewAnnotation] = {}
        self._selected_id: str | None = None
        self._loading = False
        self._baseline: dict[str, Any] | None = None
        self._color = "#ff9f0a"
        self._build_ui()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setObjectName("inspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        body = QtWidgets.QWidget(scroll)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 18)
        layout.setSpacing(14)

        title = QtWidgets.QLabel("Review layer", body)
        title.setObjectName("inspectorTitle")
        description = QtWidgets.QLabel(
            "Marks stay outside the publication document until you explicitly "
            "promote one.",
            body,
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        safety = QtWidgets.QLabel(
            "NON-EXPORTING OVERLAY",
            body,
        )
        safety.setObjectName("reviewSafetyBadge")
        safety.setAccessibleName("Review marks do not export")
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(safety)

        tools_group = QtWidgets.QGroupBox("Tools", body)
        tools_group.setObjectName("inspectorSection")
        tools_layout = QtWidgets.QGridLayout(tools_group)
        tools_layout.setContentsMargins(10, 14, 10, 10)
        tools_layout.setHorizontalSpacing(7)
        tools_layout.setVerticalSpacing(7)
        self.tool_group = QtWidgets.QButtonGroup(self)
        self.tool_group.setExclusive(True)
        tool_specs = [
            ("select", "Select"),
            ("text", "Note"),
            ("arrow", "Arrow"),
            ("rectangle", "Box"),
            ("ellipse", "Oval"),
            ("freehand", "Pen"),
        ]
        self.tool_buttons: dict[str, QtWidgets.QToolButton] = {}
        for index, (tool, label) in enumerate(tool_specs):
            button = QtWidgets.QToolButton(tools_group)
            button.setObjectName("reviewToolButton")
            button.setText(label)
            button.setCheckable(True)
            button.setToolButtonStyle(
                QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
            )
            button.setAccessibleName(f"Review tool: {label}")
            button.setToolTip(
                "Select and move review marks"
                if tool == "select"
                else f"Draw a non-exported {label.lower()} review mark"
            )
            self.tool_group.addButton(button)
            self.tool_buttons[tool] = button
            tools_layout.addWidget(button, index // 3, index % 3)
            button.clicked.connect(
                lambda checked, selected=tool: (
                    self.toolChanged.emit(selected) if checked else None
                )
            )
        self.tool_buttons["select"].setChecked(True)

        anchor_label = QtWidgets.QLabel("Anchor", tools_group)
        anchor_label.setObjectName("fieldLabel")
        self.anchor_combo = QtWidgets.QComboBox(tools_group)
        self.anchor_combo.setAccessibleName("Review coordinate anchor")
        for label, value in (
            ("Page · responsive", "normalized_page"),
            ("Page · absolute", "page"),
            ("Graph", "graph"),
            ("Data coordinates", "data"),
            ("Selected object", "object"),
        ):
            self.anchor_combo.addItem(label, value)
        self.anchor_combo.setToolTip(
            "Choose what the review mark follows when the page or data changes."
        )
        tools_layout.addWidget(anchor_label, 2, 0)
        tools_layout.addWidget(self.anchor_combo, 2, 1, 1, 2)
        layout.addWidget(tools_group)

        marks_group = QtWidgets.QGroupBox("Marks on this page", body)
        marks_group.setObjectName("inspectorSection")
        marks_layout = QtWidgets.QVBoxLayout(marks_group)
        marks_layout.setContentsMargins(10, 14, 10, 10)
        self.annotation_list = QtWidgets.QListWidget(marks_group)
        self.annotation_list.setObjectName("reviewAnnotationList")
        self.annotation_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.annotation_list.setAccessibleName("Review annotations on current page")
        self.annotation_list.currentItemChanged.connect(
            self._list_selection_changed
        )
        self.empty_label = QtWidgets.QLabel(
            "Draw on the canvas to start a review.",
            marks_group,
        )
        self.empty_label.setObjectName("muted")
        self.empty_label.setWordWrap(True)
        marks_layout.addWidget(self.annotation_list)
        marks_layout.addWidget(self.empty_label)
        layout.addWidget(marks_group)

        edit_group = QtWidgets.QGroupBox("Selected mark", body)
        edit_group.setObjectName("inspectorSection")
        edit_layout = QtWidgets.QFormLayout(edit_group)
        edit_layout.setContentsMargins(10, 14, 10, 10)
        edit_layout.setHorizontalSpacing(10)
        edit_layout.setVerticalSpacing(9)

        self.text_edit = QtWidgets.QLineEdit(edit_group)
        self.text_edit.setPlaceholderText("Review note or comment")
        self.text_edit.setAccessibleName("Review annotation text")
        self.color_button = QtWidgets.QToolButton(edit_group)
        self.color_button.setObjectName("colorSwatch")
        self.color_button.setText("Color")
        self.color_button.setAccessibleName("Review annotation color")
        self.color_button.clicked.connect(self._choose_color)
        self.line_width = QtWidgets.QDoubleSpinBox(edit_group)
        self.line_width.setRange(0.5, 12.0)
        self.line_width.setDecimals(1)
        self.line_width.setSingleStep(0.5)
        self.line_width.setSuffix(" pt")
        self.line_width.setAccessibleName("Review line width")
        self.font_size = QtWidgets.QDoubleSpinBox(edit_group)
        self.font_size.setRange(6.0, 72.0)
        self.font_size.setDecimals(1)
        self.font_size.setSingleStep(1.0)
        self.font_size.setSuffix(" pt")
        self.font_size.setAccessibleName("Review note font size")
        edit_layout.addRow("Text", self.text_edit)
        edit_layout.addRow("Color", self.color_button)
        edit_layout.addRow("Line", self.line_width)
        edit_layout.addRow("Text size", self.font_size)

        button_row = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton("Apply", edit_group)
        self.apply_button.clicked.connect(self._apply_selected)
        self.revert_button = QtWidgets.QPushButton("Revert", edit_group)
        self.revert_button.setObjectName("secondaryButton")
        self.revert_button.clicked.connect(self.revert_staged)
        button_row.addWidget(self.apply_button)
        button_row.addWidget(self.revert_button)
        edit_layout.addRow(button_row)

        action_row = QtWidgets.QHBoxLayout()
        self.promote_button = QtWidgets.QPushButton(
            "Promote to Figure",
            edit_group,
        )
        self.promote_button.setToolTip(
            "Convert this review mark into an editable native Veusz annotation."
        )
        self.promote_button.clicked.connect(self._promote_selected)
        self.remove_button = QtWidgets.QPushButton("Remove", edit_group)
        self.remove_button.setObjectName("secondaryButton")
        self.remove_button.clicked.connect(self._remove_selected)
        action_row.addWidget(self.promote_button, 1)
        action_row.addWidget(self.remove_button)
        edit_layout.addRow(action_row)
        layout.addWidget(edit_group)
        layout.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll)
        self.scroll = scroll
        self.body = body
        self.edit_group = edit_group
        self._set_selected_annotation(None)

    @property
    def current_tool(self) -> str:
        for tool, button in self.tool_buttons.items():
            if button.isChecked():
                return tool
        return "select"

    @property
    def coordinate_space(self) -> str:
        return str(self.anchor_combo.currentData())

    @property
    def selected_annotation_id(self) -> str | None:
        return self._selected_id

    @property
    def drawing_style(self) -> ReviewAnnotationStyle:
        return ReviewAnnotationStyle(
            color=self._color,
            fill_color=self._baseline_fill_color(),
            line_width=self.line_width.value(),
            font_size=self.font_size.value(),
            opacity=self._baseline_opacity(),
        )

    @property
    def has_staged_changes(self) -> bool:
        if self._baseline is None or self._selected_id is None:
            return False
        return self.collect_changes() != self._baseline

    def collect_changes(self) -> dict[str, Any]:
        return {
            "text": self.text_edit.text(),
            "style": {
                "color": self._color,
                "fill_color": self._baseline_fill_color(),
                "line_width": self.line_width.value(),
                "font_size": self.font_size.value(),
                "opacity": self._baseline_opacity(),
            },
        }

    def _baseline_fill_color(self) -> str:
        if self._baseline is None:
            return "#fff2cc"
        return str(self._baseline["style"]["fill_color"])

    def _baseline_opacity(self) -> float:
        if self._baseline is None:
            return 0.96
        return float(self._baseline["style"]["opacity"])

    def _set_color(self, color: str) -> None:
        self._color = str(color)
        self.color_button.setStyleSheet(
            f"QToolButton#colorSwatch {{ background: {self._color}; }}"
        )
        self.color_button.setText(self._color)

    def _choose_color(self) -> None:
        chosen = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self._color),
            self,
            "Review color",
        )
        if chosen.isValid():
            self._set_color(chosen.name(QtGui.QColor.NameFormat.HexRgb))

    def set_tool(self, tool: str) -> None:
        if tool not in self.tool_buttons:
            raise ValueError(f"Unsupported review tool: {tool!r}")
        blocker = QtCore.QSignalBlocker(self.tool_buttons[tool])
        self.tool_buttons[tool].setChecked(True)
        del blocker

    def set_annotations(
        self,
        annotations: list[ReviewAnnotation],
        *,
        selected_id: str | None = None,
    ) -> None:
        self._loading = True
        try:
            self._annotations = {
                annotation.annotation_id: annotation
                for annotation in annotations
                if annotation.state != "removed"
            }
            requested = selected_id or self._selected_id
            self.annotation_list.clear()
            selected_row = -1
            for row, annotation in enumerate(self._annotations.values()):
                label = _SHAPE_LABELS[annotation.shape]
                if annotation.text:
                    excerpt = annotation.text.strip().replace("\n", " ")
                    if len(excerpt) > 34:
                        excerpt = f"{excerpt[:31]}…"
                    label = f"{label} · {excerpt}"
                if annotation.state == "promoted":
                    label = f"{label} · Promoted"
                item = QtWidgets.QListWidgetItem(label)
                item.setData(
                    QtCore.Qt.ItemDataRole.UserRole,
                    annotation.annotation_id,
                )
                item.setToolTip(
                    f"{annotation.coordinate_space} anchor · {annotation.state}"
                )
                self.annotation_list.addItem(item)
                if annotation.annotation_id == requested:
                    selected_row = row
            self.empty_label.setVisible(not self._annotations)
            self.annotation_list.setVisible(bool(self._annotations))
            if selected_row >= 0:
                self.annotation_list.setCurrentRow(selected_row)
                annotation = list(self._annotations.values())[selected_row]
                self._set_selected_annotation(annotation)
            else:
                self._set_selected_annotation(None)
        finally:
            self._loading = False

    def select_annotation(self, annotation_id: str | None) -> None:
        self._loading = True
        try:
            if annotation_id is None:
                self.annotation_list.clearSelection()
                self.annotation_list.setCurrentRow(-1)
                self._set_selected_annotation(None)
                return
            for row in range(self.annotation_list.count()):
                item = self.annotation_list.item(row)
                if item.data(QtCore.Qt.ItemDataRole.UserRole) == annotation_id:
                    self.annotation_list.setCurrentRow(row)
                    self._set_selected_annotation(self._annotations[annotation_id])
                    return
        finally:
            self._loading = False

    def _list_selection_changed(
        self,
        current: QtWidgets.QListWidgetItem | None,
        previous: QtWidgets.QListWidgetItem | None,
    ) -> None:
        del previous
        if self._loading:
            return
        annotation_id = (
            str(current.data(QtCore.Qt.ItemDataRole.UserRole))
            if current is not None
            else None
        )
        if annotation_id is not None:
            self.annotationSelected.emit(annotation_id)

    def _set_selected_annotation(
        self,
        annotation: ReviewAnnotation | None,
    ) -> None:
        self._selected_id = annotation.annotation_id if annotation else None
        enabled = annotation is not None and annotation.state == "review_only"
        for widget in (
            self.text_edit,
            self.color_button,
            self.line_width,
            self.font_size,
            self.apply_button,
            self.revert_button,
            self.remove_button,
        ):
            widget.setEnabled(enabled)
        self.promote_button.setEnabled(
            bool(
                annotation is not None
                and annotation.state == "review_only"
                and annotation.shape in PROMOTABLE_ANNOTATION_SHAPES
            )
        )
        if annotation is None:
            self.text_edit.clear()
            self.line_width.setValue(1.0)
            self.font_size.setValue(7.0)
            self._set_color("#ff9f0a")
            self._baseline = None
            return
        baseline = {
            "text": annotation.text,
            "style": annotation.style.to_dict(),
        }
        self._baseline = baseline
        self.text_edit.setText(annotation.text)
        self.line_width.setValue(annotation.style.line_width)
        self.font_size.setValue(annotation.style.font_size)
        self._set_color(annotation.style.color)

    def revert_staged(self) -> None:
        if self._selected_id is None:
            return
        annotation = self._annotations.get(self._selected_id)
        self._set_selected_annotation(annotation)

    def _apply_selected(self) -> None:
        if self._selected_id is None:
            return
        payload = self.collect_changes()
        ReviewAnnotationStyle.from_dict(payload["style"])
        self.updateRequested.emit(self._selected_id, payload)

    def _promote_selected(self) -> None:
        if self._selected_id is not None:
            self.promoteRequested.emit(self._selected_id)

    def _remove_selected(self) -> None:
        if self._selected_id is not None:
            self.removeRequested.emit(self._selected_id)


__all__ = ["ReviewInspectorPanel"]
