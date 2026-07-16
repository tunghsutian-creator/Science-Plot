from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.canvas.operations import CanvasOperation, CanvasOperationBatch
from sciplot_gui.document_controller import DocumentController
from sciplot_gui.theme import (
    CanvasThemeTokens,
    build_canvas_stylesheet,
    build_canvas_theme,
)
from sciplot_gui.workspace import CanvasWorkspace, export_canvas_workspace


class SciPlotCanvasWindow(QtWidgets.QMainWindow):
    """Adaptive SciPlot shell around the exact-current Veusz document."""

    def __init__(
        self,
        workspace: CanvasWorkspace,
        *,
        interactive: bool = True,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.interactive = interactive
        self.last_export: dict[str, Any] | None = None
        self._close_policy_override: str | None = None
        self._closed = False
        self._closing = False
        self._fit_scheduled = False
        self._canvas_only = False
        self._adaptive_floating = False
        self._applying_theme = False
        self._restoring_interface = False
        self._narrow_threshold = 980
        self.theme_tokens: CanvasThemeTokens | None = None
        self.setObjectName("sciplotCanvasWindow")
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_DeleteOnClose,
            self.interactive,
        )
        self.resize(1380, 860)
        self.setMinimumSize(760, 560)

        self.controller = DocumentController(
            document_path=workspace.document_path,
            session_path=workspace.session_path,
            journal_path=workspace.journal_path,
            project_id=workspace.project_id,
            parent=self,
        )
        self.plot_window = self.controller.adapter.plot_window
        self.plot_window.viewtoolbar.hide()

        self._build_toolbar()
        self._build_central_workspace()
        self._build_status_bar()
        self._build_menus()
        self._apply_theme()
        self._restore_interface_state()
        self._connect_canvas_signals()
        self._populate_text_targets()
        self._sync_ui()
        if self.controller.recovered_from_snapshot is not None:
            self.status_message.setText("Recovered unsaved Canvas work")
        elif self.controller.session.state == "ready":
            self.status_message.setText("Last export remains ready")

        self._view_state_timer = QtCore.QTimer(self)
        self._view_state_timer.setInterval(350)
        self._view_state_timer.timeout.connect(self._poll_view_state)
        self._view_state_timer.start()
        style_hints = QtGui.QGuiApplication.styleHints()
        if hasattr(style_hints, "colorSchemeChanged"):
            style_hints.colorSchemeChanged.connect(self._system_color_scheme_changed)
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def _action(
        self,
        text: str,
        shortcut: str | None,
        callback: Any,
        *,
        tooltip: str,
        object_name: str | None = None,
        accessible_name: str | None = None,
    ) -> QtGui.QAction:
        action = QtGui.QAction(text, self)
        action.setObjectName(object_name or "")
        if shortcut:
            action.setShortcut(QtGui.QKeySequence(shortcut))
        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)
        action.setProperty("sciplotAccessibleName", accessible_name or tooltip)
        action.triggered.connect(callback)
        return action

    def _bind_toolbar_accessibility(self, action: QtGui.QAction) -> None:
        widget = self.toolbar.widgetForAction(action)
        if widget is None:
            return
        name = str(action.property("sciplotAccessibleName") or action.toolTip())
        widget.setAccessibleName(name)
        widget.setAccessibleDescription(action.toolTip())

    def _build_toolbar(self) -> None:
        toolbar = QtWidgets.QToolBar("SciPlot Canvas", self)
        toolbar.setObjectName("sciplotToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.toolbar = toolbar

        title = QtWidgets.QLabel(self.workspace.document_path.stem)
        title.setObjectName("documentTitle")
        title.setMinimumWidth(150)
        title.setMaximumWidth(280)
        title.setText(
            title.fontMetrics().elidedText(
                self.workspace.document_path.stem,
                QtCore.Qt.TextElideMode.ElideMiddle,
                270,
            )
        )
        title.setToolTip(self.workspace.document_path.stem)
        toolbar.addWidget(title)
        self.document_title = title

        self.state_chip = QtWidgets.QLabel()
        self.state_chip.setObjectName("stateChip")
        toolbar.addWidget(self.state_chip)
        toolbar.addSeparator()

        self.save_action = self._action(
            "Save",
            "Ctrl+S",
            self._save_triggered,
            tooltip="Save the exact current VSZ",
            object_name="saveAction",
        )
        self.undo_action = self._action(
            "Undo",
            "Ctrl+Z",
            self._undo_triggered,
            tooltip="Undo one accepted Canvas batch",
            object_name="undoAction",
        )
        self.redo_action = self._action(
            "Redo",
            "Ctrl+Shift+Z",
            self._redo_triggered,
            tooltip="Redo one accepted Canvas batch",
            object_name="redoAction",
        )
        toolbar.addActions([self.save_action, self.undo_action, self.redo_action])
        for action in (self.save_action, self.undo_action, self.redo_action):
            self._bind_toolbar_accessibility(action)
        toolbar.addSeparator()

        self.previous_page_action = self._action(
            "‹",
            "Ctrl+PgUp",
            lambda: self._change_page(-1),
            tooltip="Previous page",
            object_name="previousPageAction",
            accessible_name="Previous page",
        )
        self.next_page_action = self._action(
            "›",
            "Ctrl+PgDown",
            lambda: self._change_page(1),
            tooltip="Next page",
            object_name="nextPageAction",
            accessible_name="Next page",
        )
        self.page_label = QtWidgets.QLabel()
        self.page_label.setObjectName("toolbarMeta")
        toolbar.addAction(self.previous_page_action)
        self._bind_toolbar_accessibility(self.previous_page_action)
        toolbar.addWidget(self.page_label)
        toolbar.addAction(self.next_page_action)
        self._bind_toolbar_accessibility(self.next_page_action)
        toolbar.addSeparator()

        self.zoom_out_action = self._action(
            "−",
            "Ctrl+-",
            lambda: self._set_zoom(self.controller.adapter.zoom_factor / 1.25),
            tooltip="Zoom out",
            object_name="zoomOutAction",
            accessible_name="Zoom out",
        )
        self.zoom_in_action = self._action(
            "+",
            "Ctrl++",
            lambda: self._set_zoom(self.controller.adapter.zoom_factor * 1.25),
            tooltip="Zoom in",
            object_name="zoomInAction",
            accessible_name="Zoom in",
        )
        self.zoom_page_action = self._action(
            "Fit",
            "Ctrl+0",
            self._zoom_to_page,
            tooltip="Fit the complete page",
            object_name="zoomFitAction",
        )
        self.zoom_100_action = self._action(
            "100%",
            "Ctrl+1",
            lambda: self._set_zoom(1.0),
            tooltip="Show the page at 1:1",
            object_name="zoomActualSizeAction",
        )
        self.zoom_label = QtWidgets.QLabel()
        self.zoom_label.setObjectName("toolbarMeta")
        toolbar.addActions(
            [
                self.zoom_out_action,
                self.zoom_in_action,
                self.zoom_page_action,
                self.zoom_100_action,
            ]
        )
        for action in (
            self.zoom_out_action,
            self.zoom_in_action,
            self.zoom_page_action,
            self.zoom_100_action,
        ):
            self._bind_toolbar_accessibility(action)
        toolbar.addWidget(self.zoom_label)

        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        toolbar.addWidget(spacer)

        self.export_action = self._action(
            "Export + QA",
            "Ctrl+E",
            self._export_triggered,
            tooltip="Save and export the exact current PDF/TIFF pair",
            object_name="exportAction",
        )
        self.advanced_action = self._action(
            "Advanced Editor",
            None,
            self._advanced_editor_triggered,
            tooltip="Open the canonical VSZ in the full Veusz recovery editor",
            object_name="advancedEditorAction",
        )
        self.inspector_action = self._action(
            "Show Inspector",
            "F9",
            self._toggle_inspector,
            tooltip="Show or hide the contextual inspector",
            object_name="inspectorAction",
        )
        self.inspector_action.setCheckable(True)
        self.canvas_only_action = self._action(
            "Canvas Only",
            None,
            self._toggle_canvas_only,
            tooltip="Hide application chrome and focus on the exact-current figure (Tab)",
            object_name="canvasOnlyAction",
        )
        self.canvas_only_action.setCheckable(True)
        self.high_contrast_action = self._action(
            "Increase Contrast",
            "Ctrl+Shift+H",
            self._toggle_high_contrast,
            tooltip="Increase contrast for SciPlot application chrome",
            object_name="highContrastAction",
        )
        self.high_contrast_action.setCheckable(True)
        self.close_action = self._action(
            "Close",
            "Ctrl+W",
            self.close,
            tooltip="Close the current SciPlot Canvas",
            object_name="closeAction",
        )
        toolbar.addAction(self.export_action)
        self._bind_toolbar_accessibility(self.export_action)

        more_menu = QtWidgets.QMenu(self)
        more_menu.addAction(self.inspector_action)
        more_menu.addAction(self.canvas_only_action)
        more_menu.addAction(self.high_contrast_action)
        more_menu.addSeparator()
        more_menu.addAction(self.advanced_action)
        more_button = QtWidgets.QToolButton(toolbar)
        more_button.setText("More")
        more_button.setToolTip("Additional Canvas and recovery actions")
        more_button.setAccessibleName("More Canvas actions")
        more_button.setAccessibleDescription(
            "Open inspector, Canvas-only, contrast, and recovery commands"
        )
        more_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        more_button.setMenu(more_menu)
        toolbar.addWidget(more_button)
        self.more_menu = more_menu
        self.more_button = more_button

    def _build_central_workspace(self) -> None:
        canvas_well = QtWidgets.QFrame(self)
        canvas_well.setObjectName("canvasWell")
        canvas_layout = QtWidgets.QVBoxLayout(canvas_well)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        self.recovery_banner = QtWidgets.QFrame(canvas_well)
        self.recovery_banner.setObjectName("recoveryBanner")
        recovery_layout = QtWidgets.QHBoxLayout(self.recovery_banner)
        recovery_layout.setContentsMargins(0, 0, 0, 0)
        recovery_text = QtWidgets.QLabel(
            "Recovered unsaved Canvas work. Save to make this state canonical."
        )
        recovery_text.setObjectName("recoveryText")
        recovery_text.setAccessibleName("Recovered unsaved Canvas work")
        recovery_text.setAccessibleDescription(
            "Save to make the recovered state canonical."
        )
        recovery_layout.addWidget(recovery_text)
        recovery_layout.addStretch(1)
        canvas_layout.addWidget(self.recovery_banner)
        canvas_layout.addWidget(self.plot_window, 1)

        inspector = QtWidgets.QFrame()
        inspector.setObjectName("inspector")
        inspector.setMinimumWidth(280)
        inspector.setMaximumWidth(720)
        inspector_layout = QtWidgets.QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(22, 20, 22, 20)
        inspector_layout.setSpacing(10)

        inspector_title = QtWidgets.QLabel("Figure")
        inspector_title.setObjectName("inspectorTitle")
        inspector_title.setAccessibleName("Figure inspector")
        inspector_layout.addWidget(inspector_title)
        context = (
            "SciPlot project"
            if self.workspace.has_project_delivery
            else "Standalone VSZ"
        )
        path_label = QtWidgets.QLabel(f"{context} · exact-current authority")
        path_label.setObjectName("muted")
        path_label.setWordWrap(True)
        path_label.setToolTip(str(self.workspace.document_path))
        inspector_layout.addWidget(path_label)
        inspector_layout.addWidget(self._divider())

        inspector_layout.addWidget(self._section_label("CURRENT SELECTION"))
        self.selection_name = QtWidgets.QLabel("Click an item on the figure")
        self.selection_name.setObjectName("value")
        self.selection_name.setWordWrap(True)
        self.selection_type = QtWidgets.QLabel("No object selected")
        self.selection_type.setObjectName("muted")
        self.selection_path = QtWidgets.QLabel("")
        self.selection_path.setObjectName("muted")
        self.selection_path.setWordWrap(True)
        inspector_layout.addWidget(self.selection_name)
        inspector_layout.addWidget(self.selection_type)
        inspector_layout.addWidget(self.selection_path)
        inspector_layout.addWidget(self._divider())

        inspector_layout.addWidget(self._section_label("VISIBLE TEXT"))
        self.text_target_combo = QtWidgets.QComboBox()
        self.text_target_combo.setAccessibleName("Visible figure text target")
        self.text_target_combo.setAccessibleDescription(
            "Choose a bounded visible label from the exact-current figure."
        )
        self.text_target_combo.setToolTip(
            "Bounded list of visible labels; this is not the Veusz object tree."
        )
        self.text_target_combo.currentIndexChanged.connect(self._text_target_changed)
        self.text_value_edit = QtWidgets.QLineEdit()
        self.text_value_edit.setAccessibleName("Selected figure text")
        self.text_value_edit.setAccessibleDescription(
            "Edit the selected visible label before applying it to the live canvas."
        )
        self.text_value_edit.setPlaceholderText("Select a visible label")
        self.text_value_edit.returnPressed.connect(self._apply_text_triggered)
        self.apply_text_button = QtWidgets.QPushButton("Apply to live canvas")
        self.apply_text_button.setAccessibleName("Apply text to live canvas")
        self.apply_text_button.clicked.connect(self._apply_text_triggered)
        inspector_layout.addWidget(self.text_target_combo)
        inspector_layout.addWidget(self.text_value_edit)
        inspector_layout.addWidget(self.apply_text_button)
        inspector_layout.addWidget(self._divider())

        inspector_layout.addWidget(self._section_label("EXPORT READINESS"))
        self.qa_status = QtWidgets.QLabel("Not exported in this Canvas session.")
        self.qa_status.setObjectName("muted")
        self.qa_status.setWordWrap(True)
        inspector_layout.addWidget(self.qa_status)
        inspector_layout.addStretch(1)

        contract_note = QtWidgets.QLabel(
            "Exact-current VSZ remains the visual authority. "
            "Advanced Editor is a recovery route."
        )
        contract_note.setObjectName("muted")
        contract_note.setWordWrap(True)
        inspector_layout.addWidget(contract_note)

        inspector_dock = QtWidgets.QDockWidget("Inspector", self)
        inspector_dock.setObjectName("inspectorDock")
        inspector_dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        inspector_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        inspector_dock.setMinimumWidth(280)
        inspector_dock.setMaximumWidth(720)
        inspector_dock.setWidget(inspector)
        inspector_dock.setAccessibleName("Contextual figure inspector")
        docked_title_bar = QtWidgets.QWidget(inspector_dock)
        docked_title_bar.setFixedHeight(0)
        inspector_dock.setTitleBarWidget(docked_title_bar)
        inspector_dock.visibilityChanged.connect(self._inspector_visibility_changed)
        inspector_dock.topLevelChanged.connect(self._inspector_top_level_changed)

        self.setCentralWidget(canvas_well)
        self.addDockWidget(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
            inspector_dock,
        )
        inspector_dock.resize(
            self.controller.session.interface.inspector_width,
            self.height(),
        )
        self.canvas_well = canvas_well
        self.inspector_dock = inspector_dock
        self.inspector = inspector

    def _build_status_bar(self) -> None:
        status = QtWidgets.QStatusBar(self)
        self.setStatusBar(status)
        self.status_message = QtWidgets.QLabel("Canvas ready")
        self.selection_status = QtWidgets.QLabel("Selection: none")
        self.coordinate_status = QtWidgets.QLabel("Coordinates: —")
        self.status_message.setAccessibleName("Canvas status")
        self.selection_status.setAccessibleName("Current Canvas selection")
        self.coordinate_status.setAccessibleName("Current plot coordinates")
        status.addWidget(self.status_message, 1)
        status.addPermanentWidget(self.selection_status)
        status.addPermanentWidget(self.coordinate_status)

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.close_action)

        edit_menu = menu_bar.addMenu("Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)

        view_menu = menu_bar.addMenu("View")
        view_menu.addAction(self.previous_page_action)
        view_menu.addAction(self.next_page_action)
        view_menu.addSeparator()
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_page_action)
        view_menu.addAction(self.zoom_100_action)
        view_menu.addSeparator()
        view_menu.addAction(self.inspector_action)
        view_menu.addAction(self.canvas_only_action)
        view_menu.addAction(self.high_contrast_action)

        document_menu = menu_bar.addMenu("Document")
        document_menu.addAction(self.advanced_action)

        self.file_menu = file_menu
        self.edit_menu = edit_menu
        self.view_menu = view_menu
        self.document_menu = document_menu

    def _divider(self) -> QtWidgets.QFrame:
        divider = QtWidgets.QFrame()
        divider.setObjectName("divider")
        return divider

    def _section_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _apply_theme(self) -> None:
        if self._applying_theme:
            return
        self._applying_theme = True
        try:
            application = QtWidgets.QApplication.instance()
            palette = application.palette() if application is not None else self.palette()
            self.theme_tokens = build_canvas_theme(
                palette,
                high_contrast=self.controller.session.interface.high_contrast,
            )
            self.setStyleSheet(build_canvas_stylesheet(self.theme_tokens))
            if hasattr(self, "state_chip"):
                style = self.state_chip.style()
                style.unpolish(self.state_chip)
                style.polish(self.state_chip)
        finally:
            self._applying_theme = False

    def _system_color_scheme_changed(self, *_: Any) -> None:
        self._apply_theme()

    def _restore_interface_state(self) -> None:
        interface = self.controller.session.interface
        self._restoring_interface = True
        try:
            self.high_contrast_action.setChecked(interface.high_contrast)
            self.inspector_action.setChecked(interface.inspector_visible)
            self.inspector_dock.resize(interface.inspector_width, self.height())
            self.inspector_dock.setVisible(interface.inspector_visible)
            self.canvas_only_action.setChecked(False)
        finally:
            self._restoring_interface = False
        QtCore.QTimer.singleShot(0, self._apply_adaptive_layout)

    def _toggle_high_contrast(self, checked: bool) -> None:
        self.controller.update_interface_state(high_contrast=bool(checked))
        self._apply_theme()
        self.status_message.setText(
            "Increased contrast enabled"
            if checked
            else "Using system contrast"
        )

    def _inspector_visibility_changed(self, visible: bool) -> None:
        if (
            self._restoring_interface
            or self._canvas_only
            or self._closing
            or self._closed
        ):
            return
        blocker = QtCore.QSignalBlocker(self.inspector_action)
        self.inspector_action.setChecked(bool(visible))
        del blocker
        self.controller.update_interface_state(inspector_visible=bool(visible))

    def _inspector_top_level_changed(self, floating: bool) -> None:
        if floating:
            self.inspector_dock.setTitleBarWidget(None)
        else:
            title_bar = QtWidgets.QWidget(self.inspector_dock)
            title_bar.setFixedHeight(0)
            self.inspector_dock.setTitleBarWidget(title_bar)
        if not floating:
            self._adaptive_floating = False
        elif self.width() >= self._narrow_threshold:
            self._adaptive_floating = False
        if floating and self.width() < self._narrow_threshold:
            QtCore.QTimer.singleShot(0, self._place_floating_inspector)

    def _place_floating_inspector(self) -> None:
        if (
            self._closed
            or not self.inspector_dock.isVisible()
            or not self.inspector_dock.isFloating()
        ):
            return
        preferred = self.controller.session.interface.inspector_width
        width = min(max(preferred, 300), max(self.width() - 80, 300))
        toolbar_height = self.toolbar.height() if self.toolbar.isVisible() else 0
        status_height = self.statusBar().height() if self.statusBar().isVisible() else 0
        height = max(self.height() - toolbar_height - status_height - 24, 420)
        top_left = self.mapToGlobal(
            QtCore.QPoint(
                max(self.width() - width - 18, 12),
                toolbar_height + 8,
            )
        )
        self.inspector_dock.resize(width, height)
        self.inspector_dock.move(top_left)
        self.inspector_dock.raise_()

    def _apply_adaptive_layout(self) -> None:
        if self._closed:
            return
        narrow = self.width() < self._narrow_threshold
        self.document_title.setMaximumWidth(220 if narrow else 280)
        self.selection_status.setVisible(not narrow and not self._canvas_only)
        self.coordinate_status.setVisible(not narrow and not self._canvas_only)
        if self._canvas_only:
            return
        should_show = self.controller.session.interface.inspector_visible
        if not should_show:
            self.inspector_dock.hide()
            return
        if narrow:
            if not self.inspector_dock.isFloating():
                self._adaptive_floating = True
                self.inspector_dock.setFloating(True)
            self.inspector_dock.show()
            self._place_floating_inspector()
            return
        if self.inspector_dock.isFloating() and self._adaptive_floating:
            self.inspector_dock.setFloating(False)
            self.addDockWidget(
                QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
                self.inspector_dock,
            )
        self.inspector_dock.show()
        self.inspector_dock.resize(
            self.controller.session.interface.inspector_width,
            self.height(),
        )

    def _toggle_canvas_only(self, checked: bool) -> None:
        self._set_canvas_only(bool(checked))

    def _set_canvas_only(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._canvas_only == enabled:
            return
        self._canvas_only = enabled
        blocker = QtCore.QSignalBlocker(self.canvas_only_action)
        self.canvas_only_action.setChecked(enabled)
        del blocker
        self.toolbar.setVisible(not enabled)
        self.menuBar().setVisible(not enabled)
        self.statusBar().setVisible(not enabled)
        dock_blocker = QtCore.QSignalBlocker(self.inspector_dock)
        if enabled:
            self.inspector_dock.hide()
        else:
            self.inspector_dock.setVisible(
                self.controller.session.interface.inspector_visible
            )
        del dock_blocker
        if enabled:
            self.plot_window.setFocus(QtCore.Qt.FocusReason.ShortcutFocusReason)
        else:
            self.status_message.setText("Canvas-only mode exited")
            self._apply_adaptive_layout()

    def _connect_canvas_signals(self) -> None:
        self.plot_window.sigWidgetClicked.connect(self._on_widget_clicked)
        self.plot_window.sigAxisValuesFromMouse.connect(self._on_axis_values)
        self.plot_window.sigUpdatePage.connect(self._on_page_updated)

    def _populate_text_targets(self, selected_id: str | None = None) -> None:
        selected_id = selected_id or self.controller.session.selection.primary_object_id
        targets = self.controller.visible_text_targets()
        blocker = QtCore.QSignalBlocker(self.text_target_combo)
        self.text_target_combo.clear()
        selected_index = -1
        for index, target in enumerate(targets):
            label = str(target.get("value") or "").strip()
            display = label or str(target.get("display_name") or target["path"])
            display = f"{target['object_type']} · {display}"
            self.text_target_combo.addItem(display, target)
            if target.get("object_id") == selected_id:
                selected_index = index
        del blocker
        if selected_index < 0 and targets:
            selected_index = 0
        self.text_target_combo.setCurrentIndex(selected_index)
        self.text_target_combo.setEnabled(bool(targets))
        self.text_value_edit.setEnabled(bool(targets))
        self.apply_text_button.setEnabled(bool(targets))
        if selected_index >= 0:
            self._text_target_changed(selected_index)
        else:
            self.text_value_edit.clear()

    def _text_target_changed(self, index: int) -> None:
        if index < 0:
            return
        target = self.text_target_combo.itemData(index)
        if not isinstance(target, dict):
            return
        self.controller.select_object_id(str(target["object_id"]))
        current_value = self.controller.adapter.setting_value(
            str(target["setting_path"])
        )
        self.text_value_edit.setText(str(current_value))
        if self.controller.session.active_inspector != "visible_text":
            self.controller.update_interface_state(active_inspector="visible_text")
        self._sync_selection_ui()

    def select_text_target(self, object_id: str) -> dict[str, Any]:
        for index in range(self.text_target_combo.count()):
            target = self.text_target_combo.itemData(index)
            if isinstance(target, dict) and target.get("object_id") == object_id:
                self.text_target_combo.setCurrentIndex(index)
                return target
        raise ValueError(f"Visible text target not found: {object_id}")

    def apply_selected_text(self, value: str) -> dict[str, Any]:
        target = self.text_target_combo.currentData()
        if not isinstance(target, dict):
            raise ValueError("No visible text target is selected.")
        setting_path = str(target["setting_path"])
        current_value = self.controller.adapter.setting_value(setting_path)
        batch = CanvasOperationBatch(
            base_revision=self.controller.session.revision,
            provider="user",
            rationale="Update visible figure text from the SciPlot Canvas.",
            operations=(
                CanvasOperation.set_setting(
                    target_id=str(target["object_id"]),
                    setting_path=setting_path,
                    value=value,
                    expected_value=current_value,
                    require_expected_value=True,
                ),
            ),
        )
        entry = self.controller.apply_batch(batch)
        self._populate_text_targets(str(target["object_id"]))
        self.status_message.setText("Applied one typed Canvas operation")
        self._sync_ui()
        return entry

    def save_document(self) -> Path:
        path = self.controller.save()
        self.recovery_banner.hide()
        self.status_message.setText(f"Saved {path.name}")
        self._sync_ui()
        return path

    def undo_document(self) -> dict[str, Any]:
        entry = self.controller.undo(provider="user")
        self._populate_text_targets()
        self.status_message.setText("Undid one Canvas batch")
        self._sync_ui()
        return entry

    def redo_document(self) -> dict[str, Any]:
        entry = self.controller.redo(provider="user")
        self._populate_text_targets()
        self.status_message.setText("Redid one Canvas batch")
        self._sync_ui()
        return entry

    def export_current(self) -> dict[str, Any]:
        if self.controller.session.dirty:
            self.save_document()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            payload = export_canvas_workspace(self.workspace)
            self.controller.record_export_result(payload)
            self.last_export = payload
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if payload.get("ready_to_use") is True:
            self.qa_status.setText(
                "Passed exact-current PDF/TIFF export, QA, and "
                + (
                    "project delivery."
                    if payload.get("scope") == "project_delivery"
                    else "standalone artifact checks."
                )
            )
            self.status_message.setText("Export and QA passed")
        else:
            self.qa_status.setText(
                f"Export needs attention: {payload.get('state') or 'failed'}"
            )
            self.status_message.setText("Export or QA needs repair")
        self._sync_ui()
        return payload

    def set_close_policy_for_test(self, policy: str | None) -> None:
        if policy not in {None, "save", "keep_recovery", "cancel"}:
            raise ValueError(f"Unsupported close policy: {policy!r}")
        self._close_policy_override = policy

    def _save_triggered(self) -> None:
        self._run_ui_action("Save failed", self.save_document)

    def _undo_triggered(self) -> None:
        self._run_ui_action("Undo failed", self.undo_document)

    def _redo_triggered(self) -> None:
        self._run_ui_action("Redo failed", self.redo_document)

    def _apply_text_triggered(self) -> None:
        self._run_ui_action(
            "Text update failed",
            lambda: self.apply_selected_text(self.text_value_edit.text()),
        )

    def _export_triggered(self) -> None:
        result = self._run_ui_action("Export failed", self.export_current)
        if (
            result is not None
            and self.interactive
            and result.get("ready_to_use") is True
        ):
            QtWidgets.QMessageBox.information(
                self,
                "SciPlot export ready",
                "The exact-current VSZ, PDF/TIFF pair, QA, and available "
                "delivery package are ready.",
            )

    def _advanced_editor_triggered(self) -> None:
        def launch() -> None:
            if self.controller.session.dirty:
                if not self.interactive:
                    raise RuntimeError(
                        "Save the dirty Canvas before opening Advanced Editor."
                    )
                choice = QtWidgets.QMessageBox.question(
                    self,
                    "Save before Advanced Editor?",
                    "Advanced Editor opens the canonical VSZ. Save the current "
                    "Canvas state first?",
                    QtWidgets.QMessageBox.StandardButton.Save
                    | QtWidgets.QMessageBox.StandardButton.Cancel,
                    QtWidgets.QMessageBox.StandardButton.Save,
                )
                if choice != QtWidgets.QMessageBox.StandardButton.Save:
                    return
                self.save_document()
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "sciplot_core.cli",
                    "studio",
                    str(self.workspace.document_path),
                    "--advanced-editor",
                ],
                cwd=str(
                    self.workspace.project_dir or self.workspace.document_path.parent
                ),
                start_new_session=True,
            )
            self.status_message.setText("Advanced Editor launched")

        self._run_ui_action("Could not open Advanced Editor", launch)

    def _toggle_inspector(self, checked: bool) -> None:
        checked = bool(checked)
        self.controller.update_interface_state(inspector_visible=checked)
        if self._canvas_only:
            self._set_canvas_only(False)
        self.inspector_dock.setVisible(checked)
        if checked:
            self._apply_adaptive_layout()
        self.status_message.setText(
            "Inspector shown" if checked else "Inspector hidden · F9 to restore"
        )

    def _run_ui_action(self, title: str, callback: Any) -> Any:
        try:
            return callback()
        except Exception as exc:
            self.status_message.setText(str(exc))
            if not self.interactive:
                raise
            QtWidgets.QMessageBox.critical(self, title, str(exc))
            return None

    def _change_page(self, delta: int) -> None:
        page = self.controller.set_page(
            self.controller.adapter.current_page + int(delta)
        )
        self.status_message.setText(f"Page {page + 1}")
        self._sync_ui()

    def _set_zoom(self, zoom: float) -> None:
        self.controller.set_zoom_factor(zoom)
        self._sync_ui()

    def _zoom_to_page(self) -> None:
        self.controller.zoom_to_page()
        self._sync_ui()

    def _on_widget_clicked(self, widget: Any, mode: str) -> None:
        selected = self.controller.select_widget_path(str(widget.path), mode=str(mode))
        if selected is not None:
            selected_id = str(selected["object_id"])
            for index in range(self.text_target_combo.count()):
                target = self.text_target_combo.itemData(index)
                if isinstance(target, dict) and target.get("object_id") == selected_id:
                    blocker = QtCore.QSignalBlocker(self.text_target_combo)
                    self.text_target_combo.setCurrentIndex(index)
                    del blocker
                    self.text_value_edit.setText(
                        str(
                            self.controller.adapter.setting_value(
                                str(target["setting_path"])
                            )
                        )
                    )
                    break
        self._sync_selection_ui()

    def _on_axis_values(self, values: dict[Any, Any]) -> None:
        if not values:
            self.coordinate_status.setText("Coordinates: —")
            return
        pairs = [
            f"{getattr(axis, 'name', axis)}={float(value):.5g}"
            for axis, value in values.items()
        ]
        self.coordinate_status.setText("Coordinates: " + ", ".join(pairs[:3]))

    def _on_page_updated(self, page_index: int) -> None:
        if hasattr(self, "controller"):
            self.controller.sync_view_state()
            self._sync_page_ui()

    def _poll_view_state(self) -> None:
        if self._closed:
            return
        session = self.controller.session
        adapter = self.controller.adapter
        if (
            session.current_page != adapter.current_page
            or abs(session.viewport.zoom - adapter.zoom_factor) > 1e-9
        ):
            self.controller.sync_view_state()
            self._sync_page_ui()
        if (
            not self._canvas_only
            and self.inspector_dock.isVisible()
            and not self.inspector_dock.isFloating()
        ):
            width = self.inspector_dock.width()
            if (
                280 <= width <= 720
                and abs(session.interface.inspector_width - width) >= 3
            ):
                self.controller.update_interface_state(inspector_width=width)

    def _sync_selection_ui(self) -> None:
        selected = self.controller.selected_object
        if selected is None:
            self.selection_name.setText("Click an item on the figure")
            self.selection_type.setText("No object selected")
            self.selection_path.clear()
            self.selection_status.setText("Selection: none")
            return
        display_name = str(selected.get("display_name") or "Unnamed")
        object_type = str(selected.get("object_type") or "object")
        path = str(selected.get("path") or "")
        self.selection_name.setText(display_name)
        self.selection_type.setText(object_type)
        self.selection_path.setText(path)
        self.selection_status.setText(f"Selection: {object_type} · {display_name}")

    def _sync_page_ui(self) -> None:
        page = self.controller.adapter.current_page
        count = self.controller.adapter.page_count
        self.page_label.setText(f"Page {page + 1} / {max(count, 1)}")
        self.previous_page_action.setEnabled(page > 0)
        self.next_page_action.setEnabled(page + 1 < count)
        self.zoom_label.setText(
            f"{round(self.controller.adapter.zoom_factor * 100):d}%"
        )

    def _sync_ui(self) -> None:
        session = self.controller.session
        state_text = session.state.replace("_", " ")
        self.state_chip.setText(state_text)
        self.state_chip.setAccessibleName(f"Document state: {state_text}")
        self.state_chip.setAccessibleDescription(
            "Current exact-current Canvas lifecycle state"
        )
        if self.state_chip.property("canvasState") != session.state:
            self.state_chip.setProperty("canvasState", session.state)
            style = self.state_chip.style()
            style.unpolish(self.state_chip)
            style.polish(self.state_chip)
        self.save_action.setEnabled(session.dirty)
        self.undo_action.setEnabled(self.controller.adapter.can_undo)
        self.redo_action.setEnabled(self.controller.adapter.can_redo)
        self.recovery_banner.setVisible(
            self.controller.recovered_from_snapshot is not None and session.dirty
        )
        dirty_marker = " •" if session.dirty else ""
        self.setWindowTitle(
            f"{self.workspace.document_path.stem}{dirty_marker} — SciPlot Canvas"
        )
        if self.last_export is None and session.exported_revision is not None:
            if session.exported_revision == session.revision:
                self.qa_status.setText(
                    f"Revision {session.revision} was exported and passed its "
                    "recorded QA gate."
                )
            else:
                self.qa_status.setText(
                    f"Last passing export was revision {session.exported_revision}; "
                    f"current revision {session.revision} requires re-export."
                )
        self._sync_page_ui()
        self._sync_selection_ui()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "inspector_dock"):
            QtCore.QTimer.singleShot(0, self._apply_adaptive_layout)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() in {
            QtCore.QEvent.Type.ApplicationPaletteChange,
            QtCore.QEvent.Type.PaletteChange,
        }:
            self._apply_theme()

    def _tab_preserves_focus_navigation(self, watched: Any) -> bool:
        return isinstance(
            watched,
            (
                QtWidgets.QAbstractButton,
                QtWidgets.QAbstractItemView,
                QtWidgets.QAbstractSlider,
                QtWidgets.QAbstractSpinBox,
                QtWidgets.QComboBox,
                QtWidgets.QLineEdit,
                QtWidgets.QMenuBar,
            ),
        )

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if (
            event.key() == QtCore.Qt.Key.Key_Tab
            and event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier
        ):
            self._set_canvas_only(not self._canvas_only)
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_Escape and self._canvas_only:
            self._set_canvas_only(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched: Any, event: QtCore.QEvent) -> bool:
        if (
            not self._closed
            and event.type() == QtCore.QEvent.Type.KeyPress
            and isinstance(event, QtGui.QKeyEvent)
            and (
                watched is self
                or (
                    isinstance(watched, QtWidgets.QWidget)
                    and self.isAncestorOf(watched)
                )
            )
        ):
            if (
                event.key() == QtCore.Qt.Key.Key_Tab
                and event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier
            ):
                if self._tab_preserves_focus_navigation(watched):
                    watched.focusNextPrevChild(True)
                    event.accept()
                    return True
                self._set_canvas_only(not self._canvas_only)
                event.accept()
                return True
            if event.key() == QtCore.Qt.Key.Key_Escape and self._canvas_only:
                self._set_canvas_only(False)
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if not self._fit_scheduled:
            self._fit_scheduled = True
            QtCore.QTimer.singleShot(0, self._initial_fit)
        QtCore.QTimer.singleShot(0, self._apply_adaptive_layout)

    def _initial_fit(self) -> None:
        if not self._closed and self.controller.adapter.zoom_factor == 1.0:
            self.controller.zoom_to_page()
            self._sync_ui()

    def _prompt_close_policy(self) -> str:
        message = QtWidgets.QMessageBox(self)
        message.setWindowTitle("Unsaved SciPlot Canvas")
        message.setText("The current Canvas contains accepted unsaved edits.")
        message.setInformativeText(
            "Save them to the canonical VSZ, or close while retaining the "
            "verified recovery snapshot."
        )
        save_button = message.addButton(
            "Save and Close", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        recovery_button = message.addButton(
            "Keep Recovery and Close",
            QtWidgets.QMessageBox.ButtonRole.ActionRole,
        )
        cancel_button = message.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        message.setDefaultButton(save_button)
        message.exec()
        clicked = message.clickedButton()
        if clicked is save_button:
            return "save"
        if clicked is recovery_button:
            return "keep_recovery"
        if clicked is cancel_button:
            return "cancel"
        return "cancel"

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._closed:
            event.accept()
            return
        policy = self._close_policy_override
        self._close_policy_override = None
        if self.controller.session.dirty:
            if policy is None:
                policy = (
                    self._prompt_close_policy() if self.interactive else "keep_recovery"
                )
            if policy == "cancel":
                event.ignore()
                return
            try:
                if policy == "save":
                    self.save_document()
                elif policy == "keep_recovery":
                    self.controller.keep_recovery_on_close(provider="user")
                else:
                    raise ValueError(f"Unsupported close policy: {policy!r}")
            except Exception as exc:
                if self.interactive:
                    QtWidgets.QMessageBox.critical(
                        self, "Could not close SciPlot Canvas", str(exc)
                    )
                    event.ignore()
                    return
                raise
        self._closing = True
        self._view_state_timer.stop()
        inspector_width = self.inspector_dock.width()
        if 280 <= inspector_width <= 720:
            self.controller.update_interface_state(inspector_width=inspector_width)
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        self.controller.close()
        self._closed = True
        event.accept()


__all__ = ["SciPlotCanvasWindow"]
