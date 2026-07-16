from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core._utils import json_safe
from sciplot_core.canvas.inspector import (
    CanvasInspectorField,
    CanvasInspectorModel,
)


@dataclass
class _FieldBinding:
    field: CanvasInspectorField
    widget: QtWidgets.QWidget
    current_value: Any


class _ColorEditor(QtWidgets.QWidget):
    valueChanged = QtCore.pyqtSignal()

    def __init__(
        self,
        value: str,
        *,
        label: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.line_edit = QtWidgets.QLineEdit(value)
        self.line_edit.setClearButtonEnabled(True)
        self.line_edit.setAccessibleName(label)
        self.line_edit.textChanged.connect(self._value_changed)
        self.swatch_button = QtWidgets.QToolButton()
        self.swatch_button.setObjectName("colorSwatch")
        self.swatch_button.setText("●")
        self.swatch_button.setAccessibleName(f"Choose {label} color")
        self.swatch_button.clicked.connect(self._choose_color)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.swatch_button)
        self._sync_swatch()

    def value(self) -> str:
        return self.line_edit.text()

    def _value_changed(self) -> None:
        self._sync_swatch()
        self.valueChanged.emit()

    def _sync_swatch(self) -> None:
        color = QtGui.QColor(self.line_edit.text())
        if color.isValid():
            self.swatch_button.setStyleSheet(
                f"color: {color.name()};"
            )
            self.swatch_button.setToolTip(color.name())
        else:
            self.swatch_button.setStyleSheet("")
            self.swatch_button.setToolTip(
                "Choose a color or keep the Veusz color expression."
            )

    def _choose_color(self) -> None:
        initial = QtGui.QColor(self.line_edit.text())
        if not initial.isValid():
            initial = QtGui.QColor("#000000")
        color = QtWidgets.QColorDialog.getColor(
            initial,
            self,
            "Choose figure color",
        )
        if not color.isValid():
            return
        self.line_edit.setText(
            color.name(QtGui.QColor.NameFormat.HexRgb)
        )


class ContextualInspectorPanel(QtWidgets.QFrame):
    """Finite scientific editors backed by CanvasInspectorModel."""

    objectSelected = QtCore.pyqtSignal(str)
    applyRequested = QtCore.pyqtSignal(object)
    immediateRequested = QtCore.pyqtSignal(object)
    pointPickToggled = QtCore.pyqtSignal(bool)
    clearPointRequested = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inspector")
        self.setMinimumWidth(280)
        self.setMaximumWidth(720)
        self._model: CanvasInspectorModel | None = None
        self._bindings: dict[str, _FieldBinding] = {}
        self._loading = False
        self._build()

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self.title_label = QtWidgets.QLabel("Figure")
        self.title_label.setObjectName("inspectorTitle")
        self.title_label.setAccessibleName("Figure inspector")
        layout.addWidget(self.title_label)

        self.authority_label = QtWidgets.QLabel(
            "Exact-current VSZ · bounded scientific controls"
        )
        self.authority_label.setObjectName("muted")
        self.authority_label.setWordWrap(True)
        layout.addWidget(self.authority_label)
        layout.addWidget(self._divider())

        layout.addWidget(self._section_label("SELECTED OBJECT"))
        self.object_combo = QtWidgets.QComboBox()
        self.object_combo.setObjectName("objectNavigator")
        self.object_combo.setAccessibleName("Selected figure object")
        self.object_combo.setAccessibleDescription(
            "Choose a supported object on the current figure page."
        )
        self.object_combo.currentIndexChanged.connect(self._object_changed)
        layout.addWidget(self.object_combo)

        self.breadcrumb_label = QtWidgets.QLabel("No supported object")
        self.breadcrumb_label.setObjectName("breadcrumb")
        self.breadcrumb_label.setWordWrap(True)
        self.breadcrumb_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.breadcrumb_label)

        self.selection_detail = QtWidgets.QLabel("")
        self.selection_detail.setObjectName("muted")
        self.selection_detail.setWordWrap(True)
        layout.addWidget(self.selection_detail)

        point_row = QtWidgets.QHBoxLayout()
        point_row.setSpacing(8)
        self.point_pick_button = QtWidgets.QPushButton("Pick data point")
        self.point_pick_button.setObjectName("secondaryButton")
        self.point_pick_button.setCheckable(True)
        self.point_pick_button.setAccessibleName("Pick a data point from the canvas")
        self.point_pick_button.toggled.connect(self.pointPickToggled.emit)
        self.clear_point_button = QtWidgets.QToolButton()
        self.clear_point_button.setObjectName("secondaryToolButton")
        self.clear_point_button.setText("Clear")
        self.clear_point_button.setAccessibleName("Clear selected data point")
        self.clear_point_button.clicked.connect(self.clearPointRequested.emit)
        point_row.addWidget(self.point_pick_button, 1)
        point_row.addWidget(self.clear_point_button)
        layout.addLayout(point_row)

        self.point_detail = QtWidgets.QLabel("No data point selected")
        self.point_detail.setObjectName("pointSelection")
        self.point_detail.setWordWrap(True)
        self.point_detail.setAccessibleName("Selected data point details")
        layout.addWidget(self.point_detail)

        self.direct_hint = QtWidgets.QLabel("")
        self.direct_hint.setObjectName("directManipulationHint")
        self.direct_hint.setWordWrap(True)
        layout.addWidget(self.direct_hint)
        layout.addWidget(self._divider())

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("inspectorScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.form_host = QtWidgets.QWidget()
        self.form_layout = QtWidgets.QVBoxLayout(self.form_host)
        self.form_layout.setContentsMargins(0, 0, 4, 0)
        self.form_layout.setSpacing(10)
        self.form_layout.addStretch(1)
        self.scroll.setWidget(self.form_host)
        layout.addWidget(self.scroll, 1)

        self.validation_label = QtWidgets.QLabel("")
        self.validation_label.setObjectName("validationMessage")
        self.validation_label.setWordWrap(True)
        self.validation_label.hide()
        layout.addWidget(self.validation_label)

        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(8)
        self.revert_button = QtWidgets.QPushButton("Revert fields")
        self.revert_button.setObjectName("secondaryButton")
        self.revert_button.setAccessibleName("Revert staged inspector fields")
        self.revert_button.clicked.connect(self.revert_staged)
        self.apply_button = QtWidgets.QPushButton("Apply changes")
        self.apply_button.setAccessibleName("Apply inspector changes to live canvas")
        self.apply_button.clicked.connect(self._apply_clicked)
        actions.addWidget(self.revert_button)
        actions.addWidget(self.apply_button, 1)
        layout.addLayout(actions)

        layout.addWidget(self._divider())
        layout.addWidget(self._section_label("STRUCTURAL QA"))
        self.qa_status = QtWidgets.QLabel("Waiting for the first structural check.")
        self.qa_status.setObjectName("muted")
        self.qa_status.setWordWrap(True)
        self.qa_status.setAccessibleName("Fast Canvas structural QA")
        layout.addWidget(self.qa_status)

        self.contract_note = QtWidgets.QLabel(
            "Dataset mapping is read-only here. Save and Export + QA remain "
            "explicit exact-current operations."
        )
        self.contract_note.setObjectName("muted")
        self.contract_note.setWordWrap(True)
        layout.addWidget(self.contract_note)

    def _divider(self) -> QtWidgets.QFrame:
        divider = QtWidgets.QFrame()
        divider.setObjectName("divider")
        return divider

    def _section_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def set_context_label(self, text: str, *, tooltip: str = "") -> None:
        self.authority_label.setText(text)
        self.authority_label.setToolTip(tooltip)

    def set_model(self, model: CanvasInspectorModel) -> None:
        self._loading = True
        self._model = model
        try:
            self._populate_objects(model)
            self.breadcrumb_label.setText("  ›  ".join(model.breadcrumb))
            self.breadcrumb_label.setToolTip(model.target.path)
            self.selection_detail.setText(
                f"{model.target.object_type} · {model.target.display_name}"
            )
            self._populate_point(model.point_selection)
            self.direct_hint.setText(
                "Drag the selected annotation on the canvas. The release is "
                "committed through the same typed operation gateway."
                if model.direct_manipulation == "drag_annotation_on_canvas"
                else ""
            )
            self.direct_hint.setVisible(bool(self.direct_hint.text()))
            self._rebuild_fields(model)
        finally:
            self._loading = False
        self._update_dirty_state()

    def _populate_objects(self, model: CanvasInspectorModel) -> None:
        blocker = QtCore.QSignalBlocker(self.object_combo)
        self.object_combo.clear()
        selected_index = -1
        for index, item in enumerate(model.related_objects):
            self.object_combo.addItem(item.role_label, item.object_id)
            self.object_combo.setItemData(
                index,
                item.path,
                QtCore.Qt.ItemDataRole.ToolTipRole,
            )
            if item.object_id == model.target.object_id:
                selected_index = index
        self.object_combo.setCurrentIndex(selected_index)
        self.object_combo.setEnabled(self.object_combo.count() > 0)
        del blocker

    def _populate_point(self, point: dict[str, Any] | None) -> None:
        if not point:
            self.point_detail.setText("No data point selected")
            self.clear_point_button.setEnabled(False)
            return
        index = str(point.get("index") or "").strip()
        suffix = f" · point {index}" if index else ""
        self.point_detail.setText(
            f"{point.get('x_label')}: {float(point.get('x')):.6g}    "
            f"{point.get('y_label')}: {float(point.get('y')):.6g}{suffix}"
        )
        self.clear_point_button.setEnabled(True)

    def _clear_form(self) -> None:
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout is not None:
                self._delete_layout(child_layout)
        self._bindings.clear()

    def _delete_layout(self, layout: QtWidgets.QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                self._delete_layout(item.layout())
        layout.deleteLater()

    def _rebuild_fields(self, model: CanvasInspectorModel) -> None:
        self._clear_form()
        sections: dict[str, list[CanvasInspectorField]] = {}
        for field in model.fields:
            sections.setdefault(field.section, []).append(field)
        for section, fields in sections.items():
            group = QtWidgets.QGroupBox(section)
            group.setObjectName("inspectorSection")
            form = QtWidgets.QFormLayout(group)
            form.setContentsMargins(12, 12, 12, 12)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
            form.setFieldGrowthPolicy(
                QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
            )
            for field in fields:
                control = self._make_editor(field)
                label = QtWidgets.QLabel(field.label)
                label.setObjectName("fieldLabel")
                label.setToolTip(field.help_text)
                label.setBuddy(control)
                form.addRow(label, control)
                binding = _FieldBinding(
                    field=field,
                    widget=control,
                    current_value=json_safe(field.value),
                )
                if not field.read_only:
                    binding.current_value = json_safe(
                        field.coerce_input(self._editor_value(binding))
                    )
                self._bindings[field.field_id] = binding
            self.form_layout.addWidget(group)
        self.form_layout.addStretch(1)

    def _make_editor(self, field: CanvasInspectorField) -> QtWidgets.QWidget:
        if field.editor in {"dataset", "read_only"}:
            value = QtWidgets.QLabel(self._display_value(field))
            value.setObjectName("readOnlyValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            )
            value.setAccessibleName(f"{field.label}, read only")
            value.setToolTip(field.help_text or "Read-only exact-current value")
            return value
        if field.editor == "boolean":
            control = QtWidgets.QCheckBox()
            control.setChecked(bool(field.value))
            control.toggled.connect(
                lambda _checked, field_id=field.field_id: self._field_changed(
                    field_id
                )
            )
        elif field.editor == "choice":
            control = QtWidgets.QComboBox()
            control.addItems(field.choices)
            index = control.findText(str(field.value))
            control.setCurrentIndex(max(index, 0))
            control.currentIndexChanged.connect(
                lambda _index, field_id=field.field_id: self._field_changed(
                    field_id
                )
            )
        elif field.editor == "color":
            control = _ColorEditor(
                str(field.value),
                label=field.label,
            )
            control.valueChanged.connect(
                lambda field_id=field.field_id: self._field_changed(field_id)
            )
        elif field.editor == "integer":
            control = QtWidgets.QSpinBox()
            control.setRange(
                int(field.minimum if field.minimum is not None else -1_000_000),
                int(field.maximum if field.maximum is not None else 1_000_000),
            )
            control.setSingleStep(int(field.step or 1))
            control.setValue(int(field.value))
            control.valueChanged.connect(
                lambda _value, field_id=field.field_id: self._field_changed(
                    field_id
                )
            )
        elif field.editor in {"number", "scalar_list"}:
            control = QtWidgets.QDoubleSpinBox()
            control.setDecimals(field.decimals)
            control.setRange(
                float(field.minimum if field.minimum is not None else -1_000_000),
                float(field.maximum if field.maximum is not None else 1_000_000),
            )
            control.setSingleStep(float(field.step or 0.1))
            value = field.value
            if field.editor == "scalar_list":
                value = value[0] if isinstance(value, (list, tuple)) and value else 0.0
            control.setValue(float(value))
            control.valueChanged.connect(
                lambda _value, field_id=field.field_id: self._field_changed(
                    field_id
                )
            )
        else:
            control = QtWidgets.QLineEdit(self._display_value(field))
            control.setClearButtonEnabled(True)
            control.textChanged.connect(
                lambda _text, field_id=field.field_id: self._field_changed(
                    field_id
                )
            )
            control.returnPressed.connect(self._apply_clicked)
        control.setAccessibleName(field.label)
        control.setAccessibleDescription(field.help_text)
        control.setToolTip(field.help_text)
        control.setProperty("inspectorFieldId", field.field_id)
        return control

    def _display_value(self, field: CanvasInspectorField) -> str:
        value = field.value
        if field.editor == "float_list" and isinstance(value, (list, tuple)):
            return ", ".join(f"{float(item):g}" for item in value)
        if field.editor == "dataset" and isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        return str(value)

    def _object_changed(self, index: int) -> None:
        if self._loading or index < 0:
            return
        object_id = self.object_combo.itemData(index)
        if object_id:
            self.objectSelected.emit(str(object_id))

    def _field_changed(self, field_id: str) -> None:
        if self._loading:
            return
        binding = self._bindings.get(field_id)
        if binding is None:
            return
        if binding.field.immediate:
            try:
                value = binding.field.coerce_input(self._editor_value(binding))
            except ValueError as exc:
                self._show_validation(str(exc))
                return
            if json_safe(value) != binding.current_value:
                self.immediateRequested.emit(
                    {
                        "field_id": binding.field.field_id,
                        "setting_path": binding.field.setting_path,
                        "value": value,
                    }
                )
                return
        self._update_dirty_state()

    def _editor_value(self, binding: _FieldBinding) -> Any:
        widget = binding.widget
        if isinstance(widget, QtWidgets.QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentText()
        if isinstance(widget, QtWidgets.QSpinBox):
            return widget.value()
        if isinstance(widget, QtWidgets.QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, _ColorEditor):
            return widget.value()
        if isinstance(widget, QtWidgets.QLineEdit):
            return widget.text()
        return binding.current_value

    def collect_changes(self) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for binding in self._bindings.values():
            if binding.field.read_only or binding.field.immediate:
                continue
            value = binding.field.coerce_input(self._editor_value(binding))
            if json_safe(value) == binding.current_value:
                continue
            changes.append(
                {
                    "field_id": binding.field.field_id,
                    "setting_path": binding.field.setting_path,
                    "value": value,
                }
            )
        return changes

    def _apply_clicked(self) -> None:
        try:
            changes = self.collect_changes()
        except ValueError as exc:
            self._show_validation(str(exc))
            return
        if not changes:
            self._show_validation("No staged field changes.")
            return
        self.validation_label.hide()
        self.applyRequested.emit(changes)

    def revert_staged(self) -> None:
        if self._model is not None:
            self.set_model(self._model)
        self.validation_label.hide()

    def _update_dirty_state(self) -> None:
        dirty = False
        if not self._loading:
            try:
                dirty = bool(self.collect_changes())
            except ValueError:
                dirty = True
        self.apply_button.setEnabled(dirty)
        self.revert_button.setEnabled(dirty)

    def _show_validation(self, text: str) -> None:
        self.validation_label.setText(text)
        self.validation_label.show()

    def set_point_pick_active(self, active: bool) -> None:
        blocker = QtCore.QSignalBlocker(self.point_pick_button)
        self.point_pick_button.setChecked(bool(active))
        self.point_pick_button.setText(
            "Picking point · Esc to stop" if active else "Pick data point"
        )
        del blocker

    def set_structural_qa(self, report: dict[str, Any]) -> None:
        status = str(report.get("status") or "unknown")
        summary = report.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        failed = summary.get("failed_ids") or []
        warnings = summary.get("warning_ids") or []
        if status == "failed":
            self.qa_status.setText(
                "Structural QA failed: " + ", ".join(str(item) for item in failed)
            )
            self.qa_status.setProperty("qaState", "failed")
        elif status == "warning":
            self.qa_status.setText(
                "Structure passed. Artifact QA is stale until Export + QA."
                if warnings == ["artifact_qa_current"]
                else "Structure passed with attention: "
                + ", ".join(str(item) for item in warnings)
            )
            self.qa_status.setProperty("qaState", "warning")
        else:
            self.qa_status.setText("Structural QA passed for the current revision.")
            self.qa_status.setProperty("qaState", "passed")
        style = self.qa_status.style()
        style.unpolish(self.qa_status)
        style.polish(self.qa_status)

    @property
    def field_widgets(self) -> dict[str, QtWidgets.QWidget]:
        return {
            field_id: binding.widget
            for field_id, binding in self._bindings.items()
        }

    @property
    def has_staged_changes(self) -> bool:
        return self.apply_button.isEnabled()


__all__ = ["ContextualInspectorPanel"]
