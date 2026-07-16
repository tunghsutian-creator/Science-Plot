from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_gui.annotation_overlay import AnnotationOverlayController
from sciplot_gui.document_controller import DocumentController
from sciplot_gui.inspectors import ContextualInspectorPanel, ReviewInspectorPanel
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
        self._point_pick_active = False
        self._review_refreshing = False
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
            annotations_path=workspace.annotations_path,
            journal_path=workspace.journal_path,
            project_id=workspace.project_id,
            parent=self,
        )
        self.plot_window = self.controller.adapter.plot_window
        self.plot_window.viewtoolbar.hide()
        self._structural_qa_timer = QtCore.QTimer(self)
        self._structural_qa_timer.setSingleShot(True)
        self._structural_qa_timer.setInterval(400)
        self._structural_qa_timer.timeout.connect(self._run_structural_qa)

        self._build_toolbar()
        self._build_central_workspace()
        self._build_status_bar()
        self._build_menus()
        self._apply_theme()
        self._restore_interface_state()
        self._connect_canvas_signals()
        self._refresh_contextual_inspector()
        self._refresh_review_layer()
        self._sync_ui()
        self._schedule_structural_qa(delay_ms=0)
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
        toolbar.addSeparator()

        self.review_action = self._action(
            "Review",
            "Ctrl+Shift+R",
            self._review_action_triggered,
            tooltip="Open the non-exported review layer",
            object_name="reviewAction",
        )
        self.review_action.setCheckable(True)
        toolbar.addAction(self.review_action)
        self._bind_toolbar_accessibility(self.review_action)

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
        self.point_pick_action = self._action(
            "Pick Data Point",
            "Ctrl+Shift+P",
            self._point_pick_action_triggered,
            tooltip="Pick and persist the nearest plotted data point",
            object_name="pointPickAction",
        )
        self.point_pick_action.setCheckable(True)
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
        more_menu.addAction(self.point_pick_action)
        more_menu.addAction(self.review_action)
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

        inspector = ContextualInspectorPanel()
        context = (
            "SciPlot project"
            if self.workspace.has_project_delivery
            else "Standalone VSZ"
        )
        inspector.set_context_label(
            f"{context} · exact-current authority",
            tooltip=str(self.workspace.document_path),
        )
        inspector.objectSelected.connect(self._inspector_object_selected)
        inspector.applyRequested.connect(self._apply_inspector_changes)
        inspector.immediateRequested.connect(self._apply_inspector_immediate)
        inspector.pointPickToggled.connect(self._set_point_pick_active)
        inspector.clearPointRequested.connect(self._clear_data_point_selection)

        review_panel = ReviewInspectorPanel()
        review_panel.toolChanged.connect(self._set_review_tool)
        review_panel.annotationSelected.connect(
            self._review_annotation_selection_requested
        )
        review_panel.updateRequested.connect(self._update_review_annotation)
        review_panel.promoteRequested.connect(self._promote_review_annotation)
        review_panel.removeRequested.connect(self._remove_review_annotation)

        inspector_tabs = QtWidgets.QTabWidget(self)
        inspector_tabs.setObjectName("inspectorTabs")
        inspector_tabs.setDocumentMode(True)
        inspector_tabs.addTab(inspector, "Edit")
        inspector_tabs.addTab(review_panel, "Review")
        inspector_tabs.setAccessibleName("Figure editing and review workspaces")
        inspector_tabs.currentChanged.connect(self._inspector_tab_changed)

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
        inspector_dock.setWidget(inspector_tabs)
        inspector_dock.setAccessibleName("Figure editing and review inspector")
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
        self.inspector_panel = inspector
        self.review_panel = review_panel
        self.inspector_tabs = inspector_tabs
        self.review_overlay = AnnotationOverlayController(
            self.plot_window,
            parent=self,
        )
        self.review_overlay.geometryCreated.connect(
            self._create_review_annotation
        )
        self.review_overlay.geometryMoved.connect(
            self._move_review_annotation
        )
        self.review_overlay.annotationSelected.connect(
            self._review_annotation_selection_requested
        )
        self.review_overlay.toolCancelled.connect(
            lambda: self._set_review_tool("select")
        )

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
        edit_menu.addSeparator()
        edit_menu.addAction(self.point_pick_action)

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
        view_menu.addAction(self.review_action)
        view_menu.addAction(self.canvas_only_action)
        view_menu.addAction(self.high_contrast_action)

        review_menu = menu_bar.addMenu("Review")
        review_menu.addAction(self.review_action)
        review_menu.addSeparator()
        self.review_tool_actions: dict[str, QtGui.QAction] = {}
        for tool, label in (
            ("select", "Select Review Mark"),
            ("text", "Draw Note"),
            ("arrow", "Draw Arrow"),
            ("rectangle", "Draw Rectangle"),
            ("ellipse", "Draw Ellipse"),
            ("freehand", "Draw Freehand"),
        ):
            action = self._action(
                label,
                None,
                lambda _checked=False, selected=tool: self._set_review_tool(
                    selected
                ),
                tooltip=label,
                object_name=f"review{tool.title()}Action",
            )
            review_menu.addAction(action)
            self.review_tool_actions[tool] = action
        review_menu.addSeparator()
        self.promote_review_action = self._action(
            "Promote Selected Review Mark",
            None,
            self._promote_selected_review,
            tooltip="Promote the selected review mark into the figure document",
            object_name="promoteReviewAction",
        )
        self.remove_review_action = self._action(
            "Remove Selected Review Mark",
            None,
            self._remove_selected_review,
            tooltip="Remove the selected non-exported review mark",
            object_name="removeReviewAction",
        )
        review_menu.addAction(self.promote_review_action)
        review_menu.addAction(self.remove_review_action)

        document_menu = menu_bar.addMenu("Document")
        document_menu.addAction(self.advanced_action)

        self.file_menu = file_menu
        self.edit_menu = edit_menu
        self.view_menu = view_menu
        self.review_menu = review_menu
        self.document_menu = document_menu

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
            self.controller.adapter.set_display_surface(
                canvas_color=self.theme_tokens.canvas_well,
            )
            if hasattr(self, "state_chip"):
                style = self.state_chip.style()
                style.unpolish(self.state_chip)
                style.polish(self.state_chip)
            if hasattr(self, "plot_window"):
                self._sync_selection_visual()
            if hasattr(self, "review_overlay"):
                self.review_overlay.set_selection_color(self.theme_tokens.focus)
                self._refresh_review_layer()
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
            active_index = (
                1
                if self.controller.session.active_inspector == "review"
                else 0
            )
            self.inspector_tabs.setCurrentIndex(active_index)
            self.review_action.setChecked(active_index == 1)
        finally:
            self._restoring_interface = False
        if self.controller.session.active_inspector is None:
            self.controller.update_interface_state(active_inspector="contextual")
        QtCore.QTimer.singleShot(0, self._apply_adaptive_layout)

    def _review_action_triggered(self, checked: bool) -> None:
        if checked:
            if not self._open_review_workspace():
                blocker = QtCore.QSignalBlocker(self.review_action)
                self.review_action.setChecked(False)
                del blocker
        else:
            self.inspector_tabs.setCurrentIndex(0)

    def _open_review_workspace(self) -> bool:
        if self._canvas_only:
            self._set_canvas_only(False)
        if not self.inspector_dock.isVisible():
            self.controller.update_interface_state(inspector_visible=True)
            self.inspector_dock.show()
        self.inspector_tabs.setCurrentIndex(1)
        self._apply_adaptive_layout()
        return self.inspector_tabs.currentIndex() == 1

    def _inspector_tab_changed(self, index: int) -> None:
        if self._restoring_interface:
            return
        next_name = "review" if index == 1 else "contextual"
        previous_name = self.controller.session.active_inspector or "contextual"
        if (
            previous_name != next_name
            and not self._resolve_staged_fields(
                f"switch to the {next_name} workspace"
            )
        ):
            blocker = QtCore.QSignalBlocker(self.inspector_tabs)
            self.inspector_tabs.setCurrentIndex(
                1 if previous_name == "review" else 0
            )
            del blocker
            return
        self.controller.update_interface_state(active_inspector=next_name)
        blocker = QtCore.QSignalBlocker(self.review_action)
        self.review_action.setChecked(next_name == "review")
        del blocker
        if next_name == "review":
            self.controller.adapter.clear_selection_visual()
            self.status_message.setText(
                "Review layer active · marks do not export until promoted"
            )
        else:
            self._sync_selection_visual()

    def _set_review_tool(self, tool: str) -> None:
        if self._point_pick_active:
            self._set_point_pick_active(False)
        if not self._open_review_workspace():
            return
        self.review_panel.set_tool(tool)
        self.review_overlay.set_tool(tool)
        self.status_message.setText(
            "Select or move a review mark"
            if tool == "select"
            else f"Draw {tool} review marks · Esc to stop"
        )

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
        self.plot_window.sigPointPicked.connect(self._on_point_picked)

    def _refresh_contextual_inspector(self) -> None:
        model = self.controller.contextual_inspector()
        self.inspector_panel.set_model(model)
        structural = self.controller.session.structural_qa_summary
        if structural:
            self.inspector_panel.set_structural_qa(structural)
        self._sync_selection_ui()

    def _inspector_object_selected(self, object_id: str) -> None:
        def select() -> None:
            if not self._resolve_staged_fields("select another object"):
                self._refresh_contextual_inspector()
                return
            self.controller.select_object_id(object_id)
            self._refresh_contextual_inspector()
            self.status_message.setText("Selected a bounded Canvas object")

        self._run_ui_action("Selection failed", select)

    def _selected_object_id(self) -> str:
        selected_id = self.controller.session.selection.primary_object_id
        if selected_id is None:
            raise RuntimeError("No Canvas object is selected.")
        return selected_id

    def _resolve_staged_fields(self, action: str) -> bool:
        contextual_staged = self.inspector_panel.has_staged_changes
        review_staged = self.review_panel.has_staged_changes
        if not contextual_staged and not review_staged:
            return True
        if not self.interactive:
            raise RuntimeError(
                f"Apply or revert staged inspector or review fields before "
                f"you {action}."
            )
        message = QtWidgets.QMessageBox(self)
        message.setWindowTitle("Staged Canvas changes")
        message.setText(
            f"Apply the staged fields before you {action}?"
        )
        message.setInformativeText(
            "Figure edits become typed document operations. Review edits stay "
            "in the non-exported annotation sidecar."
        )
        apply_button = message.addButton(
            "Apply Changes",
            QtWidgets.QMessageBox.ButtonRole.AcceptRole,
        )
        revert_button = message.addButton(
            "Revert Fields",
            QtWidgets.QMessageBox.ButtonRole.DestructiveRole,
        )
        cancel_button = message.addButton(
            QtWidgets.QMessageBox.StandardButton.Cancel
        )
        message.setDefaultButton(apply_button)
        message.exec()
        clicked = message.clickedButton()
        if clicked is apply_button:
            try:
                contextual_changes = (
                    self.inspector_panel.collect_changes()
                    if contextual_staged
                    else []
                )
                review_id = self.review_panel.selected_annotation_id
                review_changes = (
                    self.review_panel.collect_changes()
                    if review_staged
                    else None
                )
            except ValueError as exc:
                self.status_message.setText(str(exc))
                return False
            if contextual_changes:
                result = self._run_ui_action(
                    "Inspector update failed",
                    lambda: self.apply_contextual_changes(
                        contextual_changes,
                        rationale=(
                            f"Apply staged inspector changes before {action}."
                        ),
                    ),
                )
                if result is None:
                    return False
            if review_changes is not None:
                if review_id is None:
                    return False
                result = self._run_ui_action(
                    "Review update failed",
                    lambda: self._apply_review_annotation_update(
                        review_id,
                        review_changes,
                    ),
                )
                if result is None:
                    return False
            return True
        if clicked is revert_button:
            self.inspector_panel.revert_staged()
            self.review_panel.revert_staged()
            return True
        if clicked is cancel_button:
            return False
        return False

    def apply_contextual_changes(
        self,
        changes: list[dict[str, Any]],
        *,
        provider: str = "user_inspector",
        rationale: str = "Edit a bounded scientific figure property.",
    ) -> dict[str, Any]:
        entry = self.controller.apply_setting_changes(
            target_id=self._selected_object_id(),
            changes=changes,
            provider=provider,
            rationale=rationale,
        )
        self._refresh_contextual_inspector()
        self._refresh_review_layer()
        self._schedule_structural_qa()
        self.status_message.setText(
            f"Applied {len(changes)} typed Canvas "
            + ("operation" if len(changes) == 1 else "operations")
        )
        self._sync_ui()
        return entry

    def _apply_inspector_changes(self, changes: Any) -> None:
        self._run_ui_action(
            "Inspector update failed",
            lambda: self.apply_contextual_changes(
                list(changes),
                rationale="Apply staged contextual inspector changes.",
            ),
        )

    def _apply_inspector_immediate(self, change: Any) -> None:
        result = self._run_ui_action(
            "Inspector update failed",
            lambda: self.apply_contextual_changes(
                [dict(change)],
                rationale="Apply an immediate contextual inspector change.",
            ),
        )
        if result is None:
            self._refresh_contextual_inspector()

    def _refresh_review_layer(
        self,
        *,
        selected_id: str | None = None,
    ) -> None:
        if self._review_refreshing or self._closed:
            return
        self._review_refreshing = True
        try:
            page = self.controller.session.current_page
            page_annotations = [
                annotation
                for annotation in self.controller.review_annotations
                if annotation.page_index == page
                and annotation.state != "removed"
            ]
            active_entries = [
                (
                    annotation,
                    self.controller.adapter.review_geometry_to_scene(
                        annotation,
                        self.controller.session,
                    ),
                )
                for annotation in page_annotations
                if annotation.state == "review_only"
            ]
            self.review_panel.set_annotations(
                page_annotations,
                selected_id=selected_id,
            )
            self.review_overlay.set_annotations(active_entries)
            current_id = (
                selected_id or self.review_panel.selected_annotation_id
            )
            if current_id is not None:
                self.review_overlay.select_annotation(current_id)
            selected = (
                self.controller.review_annotation(current_id)
                if current_id is not None
                else None
            )
            promotable = bool(selected is not None and selected.promotable)
            removable = bool(
                selected is not None and selected.state == "review_only"
            )
            if hasattr(self, "promote_review_action"):
                self.promote_review_action.setEnabled(promotable)
                self.remove_review_action.setEnabled(removable)
        finally:
            self._review_refreshing = False

    def _review_annotation_selection_requested(
        self,
        annotation_id: str,
    ) -> None:
        previous = self.review_panel.selected_annotation_id
        if (
            previous != annotation_id
            and not self._resolve_staged_fields(
                "select another review mark"
            )
        ):
            self.review_panel.select_annotation(previous)
            self.review_overlay.select_annotation(previous)
            return
        self._open_review_workspace()
        self.review_panel.select_annotation(annotation_id)
        self.review_overlay.select_annotation(annotation_id)
        annotation = self.controller.review_annotation(annotation_id)
        self.status_message.setText(
            f"Selected review {annotation.shape} · "
            f"{annotation.coordinate_space} anchor"
        )
        self._refresh_review_layer(selected_id=annotation_id)

    def _create_review_annotation(
        self,
        shape: str,
        scene_geometry: Any,
    ) -> None:
        def create() -> Any:
            text = ""
            if shape == "text":
                if self.interactive:
                    text, accepted = QtWidgets.QInputDialog.getText(
                        self,
                        "Review note",
                        "Note text",
                        text="Review note",
                    )
                    if not accepted:
                        return None
                else:
                    text = "Review note"
            annotation = self.controller.create_review_annotation_from_scene(
                shape=str(shape),
                scene_geometry=dict(scene_geometry),
                coordinate_space=self.review_panel.coordinate_space,
                text=text,
                style=self.review_panel.drawing_style,
            )
            self._refresh_review_layer(selected_id=annotation.annotation_id)
            self.review_panel.select_annotation(annotation.annotation_id)
            self.review_overlay.select_annotation(annotation.annotation_id)
            self.status_message.setText(
                f"Added non-exported review {annotation.shape}"
            )
            return annotation

        self._run_ui_action("Could not add review annotation", create)

    def _move_review_annotation(
        self,
        annotation_id: str,
        scene_geometry: Any,
    ) -> None:
        def move() -> Any:
            annotation = self.controller.move_review_annotation_from_scene(
                annotation_id,
                dict(scene_geometry),
            )
            self._refresh_review_layer(selected_id=annotation.annotation_id)
            self.status_message.setText("Moved review mark without changing the VSZ")
            return annotation

        self._run_ui_action("Could not move review annotation", move)

    def _apply_review_annotation_update(
        self,
        annotation_id: str,
        payload: dict[str, Any],
    ) -> Any:
        annotation = self.controller.update_review_annotation(
            annotation_id,
            text=str(payload.get("text") or ""),
            style=dict(payload.get("style") or {}),
        )
        self._refresh_review_layer(selected_id=annotation.annotation_id)
        self.status_message.setText(
            "Updated the non-exported review annotation"
        )
        return annotation

    def _update_review_annotation(
        self,
        annotation_id: str,
        payload: Any,
    ) -> None:
        self._run_ui_action(
            "Could not update review annotation",
            lambda: self._apply_review_annotation_update(
                annotation_id,
                dict(payload),
            ),
        )

    def _promote_review_annotation(self, annotation_id: str) -> None:
        def promote() -> Any:
            if not self._resolve_staged_fields("promote the review mark"):
                return None
            entry = self.controller.promote_review_annotation(annotation_id)
            promoted = self.controller.review_annotation(annotation_id)
            if promoted.promoted_object_id is None:
                raise RuntimeError(
                    "The promoted annotation has no stable native object ID."
                )
            self.controller.select_object_id(promoted.promoted_object_id)
            self._refresh_review_layer(selected_id=annotation_id)
            self._refresh_contextual_inspector()
            self.inspector_tabs.setCurrentIndex(0)
            self._schedule_structural_qa()
            self._sync_ui()
            self.status_message.setText(
                "Promoted review mark into the editable figure document"
            )
            return entry

        self._run_ui_action("Could not promote review annotation", promote)

    def _remove_review_annotation(self, annotation_id: str) -> None:
        def remove() -> Any:
            annotation = self.controller.remove_review_annotation(annotation_id)
            self._refresh_review_layer()
            self.status_message.setText("Removed the review mark")
            return annotation

        self._run_ui_action("Could not remove review annotation", remove)

    def _promote_selected_review(self) -> None:
        annotation_id = self.review_panel.selected_annotation_id
        if annotation_id is None:
            self.status_message.setText(
                "Select a review mark before promoting it."
            )
            return
        self._promote_review_annotation(annotation_id)

    def _remove_selected_review(self) -> None:
        annotation_id = self.review_panel.selected_annotation_id
        if annotation_id is None:
            self.status_message.setText(
                "Select a review mark before removing it."
            )
            return
        self._remove_review_annotation(annotation_id)

    def _point_pick_action_triggered(self, checked: bool) -> None:
        self._set_point_pick_active(bool(checked))

    def _set_point_pick_active(self, active: bool) -> None:
        active = bool(active)
        if active:
            self.review_overlay.set_tool("select")
            self.review_panel.set_tool("select")
            self.inspector_tabs.setCurrentIndex(0)
        self.controller.set_interaction_mode("pick" if active else "select")
        self._point_pick_active = active
        action_blocker = QtCore.QSignalBlocker(self.point_pick_action)
        self.point_pick_action.setChecked(active)
        del action_blocker
        self.inspector_panel.set_point_pick_active(active)
        self.status_message.setText(
            "Pick a plotted data point · Esc to stop"
            if active
            else "Data-point picker stopped"
        )

    def _on_point_picked(self, pickinfo: Any) -> None:
        def apply_pick() -> None:
            point = self.controller.select_data_point(pickinfo)
            self._set_point_pick_active(False)
            self._refresh_contextual_inspector()
            self.status_message.setText(
                f"Selected {point['x_label']}={point['x']:.5g}, "
                f"{point['y_label']}={point['y']:.5g}"
            )

        self._run_ui_action("Could not select data point", apply_pick)

    def _clear_data_point_selection(self) -> None:
        def clear() -> None:
            self.controller.clear_data_point_selection()
            self._refresh_contextual_inspector()
            self.status_message.setText("Cleared the selected data point")

        self._run_ui_action("Could not clear data point", clear)

    def _apply_direct_manipulation(
        self,
        widget_path: str,
        changes: list[dict[str, Any]],
        rationale: str,
    ) -> dict[str, Any]:
        selected = self.controller.select_widget_path(widget_path)
        if selected is None:
            raise RuntimeError(
                "The directly manipulated object no longer resolves."
            )
        return self.apply_contextual_changes(
            changes,
            provider="user_direct_manipulation",
            rationale=rationale,
        )

    def _direct_manipulation_requested(
        self,
        widget_path: str,
        changes: list[dict[str, Any]],
        rationale: str,
    ) -> None:
        result = self._run_ui_action(
            "Direct manipulation failed",
            lambda: self._apply_direct_manipulation(
                widget_path,
                changes,
                rationale,
            ),
        )
        if result is None:
            self.controller.adapter.force_redraw()
            self._refresh_contextual_inspector()

    def _sync_selection_visual(self) -> None:
        if (
            hasattr(self, "inspector_tabs")
            and self.inspector_tabs.currentIndex() == 1
        ):
            self.controller.adapter.clear_selection_visual()
            return
        selected = self.controller.selected_object
        path = str(selected.get("path")) if selected is not None else None
        color = self.theme_tokens.focus if self.theme_tokens is not None else "#308cc6"
        self.controller.adapter.show_selection_visual(
            path,
            color=color,
            direct_callback=self._direct_manipulation_requested,
        )

    def _schedule_structural_qa(self, *, delay_ms: int = 400) -> None:
        if self._closed:
            return
        self._structural_qa_timer.start(max(int(delay_ms), 0))

    def _run_structural_qa(self) -> dict[str, Any] | None:
        if self._closed:
            return None
        report = self._run_ui_action(
            "Structural QA failed",
            self.controller.run_structural_qa,
        )
        if isinstance(report, dict):
            self.inspector_panel.set_structural_qa(report)
        return report

    def select_text_target(self, object_id: str) -> dict[str, Any]:
        for target in self.controller.visible_text_targets():
            if target.get("object_id") == object_id:
                self.controller.select_object_id(object_id)
                self._refresh_contextual_inspector()
                return target
        raise ValueError(f"Visible text target not found: {object_id}")

    def apply_selected_text(self, value: str) -> dict[str, Any]:
        targets = self.controller.visible_text_targets()
        selected_id = self.controller.session.selection.primary_object_id
        target = next(
            (
                candidate
                for candidate in targets
                if candidate.get("object_id") == selected_id
            ),
            targets[0] if targets else None,
        )
        if target is None:
            raise ValueError("No visible text target is available.")
        self.controller.select_object_id(str(target["object_id"]))
        return self.apply_contextual_changes(
            [
                {
                    "setting_path": str(target["setting_path"]),
                    "value": value,
                }
            ],
            provider="user",
            rationale="Update visible figure text from the SciPlot Canvas.",
        )

    def save_document(self) -> Path:
        if (
            self.inspector_panel.has_staged_changes
            or self.review_panel.has_staged_changes
        ):
            raise RuntimeError(
                "Apply or revert staged inspector or review fields before saving."
            )
        path = self.controller.save()
        self.recovery_banner.hide()
        self.status_message.setText(f"Saved {path.name}")
        self._sync_ui()
        self._schedule_structural_qa()
        return path

    def undo_document(self) -> dict[str, Any]:
        entry = self.controller.undo(provider="user")
        self._refresh_contextual_inspector()
        self._refresh_review_layer()
        self.status_message.setText("Undid one Canvas batch")
        self._sync_ui()
        self._schedule_structural_qa()
        return entry

    def redo_document(self) -> dict[str, Any]:
        entry = self.controller.redo(provider="user")
        self._refresh_contextual_inspector()
        self._refresh_review_layer()
        self.status_message.setText("Redid one Canvas batch")
        self._sync_ui()
        self._schedule_structural_qa()
        return entry

    def export_current(self) -> dict[str, Any]:
        if (
            self.inspector_panel.has_staged_changes
            or self.review_panel.has_staged_changes
        ):
            raise RuntimeError(
                "Apply or revert staged inspector or review fields before "
                "Export + QA."
            )
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
            self.status_message.setText("Export and QA passed")
        else:
            self.status_message.setText("Export or QA needs repair")
        report = self.controller.run_structural_qa()
        self.inspector_panel.set_structural_qa(report)
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
        if not self._resolve_staged_fields("change pages"):
            return
        page = self.controller.set_page(
            self.controller.adapter.current_page + int(delta)
        )
        self._refresh_contextual_inspector()
        self._refresh_review_layer()
        self.status_message.setText(f"Page {page + 1}")
        self._sync_ui()
        self._schedule_structural_qa()

    def _set_zoom(self, zoom: float) -> None:
        self.controller.set_zoom_factor(zoom)
        self._refresh_review_layer()
        self._sync_ui()

    def _zoom_to_page(self) -> None:
        self.controller.zoom_to_page()
        self._refresh_review_layer()
        self._sync_ui()

    def _on_widget_clicked(self, widget: Any, mode: str) -> None:
        if not self._resolve_staged_fields("select another object"):
            self._refresh_contextual_inspector()
            return
        selected = self.controller.select_widget_path(str(widget.path), mode=str(mode))
        if selected is not None:
            self._refresh_contextual_inspector()
            self.status_message.setText(
                f"Selected {selected['object_type']} · "
                f"{selected['display_name']}"
            )
        else:
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
            self._refresh_review_layer()

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
            self._refresh_review_layer()
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
        if (
            hasattr(self, "inspector_tabs")
            and self.inspector_tabs.currentIndex() == 1
            and self.review_panel.selected_annotation_id is not None
        ):
            annotation = self.controller.review_annotation(
                self.review_panel.selected_annotation_id
            )
            self.selection_status.setText(
                f"Review: {annotation.shape} · {annotation.coordinate_space}"
            )
            self.controller.adapter.clear_selection_visual()
            return
        selected = self.controller.selected_object
        if selected is None:
            self.selection_status.setText("Selection: none")
            self.controller.adapter.clear_selection_visual()
            return
        display_name = str(selected.get("display_name") or "Unnamed")
        object_type = str(selected.get("object_type") or "object")
        self.selection_status.setText(f"Selection: {object_type} · {display_name}")
        self._sync_selection_visual()

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
        review_count = len(self.controller.active_review_annotations())
        self.review_action.setText(
            f"Review · {review_count}" if review_count else "Review"
        )
        self.review_action.setToolTip(
            f"{review_count} non-exported review mark"
            + ("" if review_count == 1 else "s")
            + " on this page"
        )
        dirty_marker = " •" if session.dirty else ""
        self.setWindowTitle(
            f"{self.workspace.document_path.stem}{dirty_marker} — SciPlot Canvas"
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
        if event.key() == QtCore.Qt.Key.Key_Escape and self._point_pick_active:
            self._set_point_pick_active(False)
            event.accept()
            return
        if (
            event.key() == QtCore.Qt.Key.Key_Escape
            and self.review_overlay.tool != "select"
        ):
            self._set_review_tool("select")
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
            if (
                event.key() == QtCore.Qt.Key.Key_Escape
                and self._point_pick_active
            ):
                self._set_point_pick_active(False)
                event.accept()
                return True
            if (
                event.key() == QtCore.Qt.Key.Key_Escape
                and self.review_overlay.tool != "select"
            ):
                self._set_review_tool("select")
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
        if (
            self.inspector_panel.has_staged_changes
            or self.review_panel.has_staged_changes
        ):
            if self.interactive:
                if not self._resolve_staged_fields("close the Canvas"):
                    self._refresh_contextual_inspector()
                    self._refresh_review_layer()
                    event.ignore()
                    return
            else:
                self.inspector_panel.revert_staged()
                self.review_panel.revert_staged()
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
        self._structural_qa_timer.stop()
        inspector_width = self.inspector_dock.width()
        if 280 <= inspector_width <= 720:
            self.controller.update_interface_state(inspector_width=inspector_width)
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        self.review_overlay.close()
        self.controller.close()
        self._closed = True
        event.accept()


__all__ = ["SciPlotCanvasWindow"]
