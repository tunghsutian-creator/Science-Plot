from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.canvas.composition import (
    COMPOSITION_LEGEND_POLICIES,
    composite_layout_ids,
    composition_layout,
)
from sciplot_core.composition_workspace import CompositionWorkspace
from sciplot_gui.composition_board import CompositionBoard
from sciplot_gui.composition_controller import (
    CompositionAuthorityConflict,
    CompositionController,
    CompositionTransactionResult,
)
from sciplot_gui.theme import (
    CanvasThemeTokens,
    build_canvas_stylesheet,
    build_canvas_theme,
)
from sciplot_gui.veusz_canvas import VeuszCanvasAdapter


class SciPlotCompositionWindow(QtWidgets.QMainWindow):
    """Drag-first M4 workspace with an exact-current native Veusz preview."""

    def __init__(
        self,
        workspace: CompositionWorkspace,
        *,
        interactive: bool = True,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.interactive = interactive
        self.controller = CompositionController(workspace, parent=self)
        self.theme_tokens: CanvasThemeTokens | None = None
        self.preview_adapter: VeuszCanvasAdapter | None = None
        self.last_transaction: CompositionTransactionResult | None = None
        self.last_export: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.drop_count = 0
        self._syncing_controls = False
        self._initializing = True
        self._preview_fit_scheduled = False
        self._child_canvas_windows: list[QtWidgets.QMainWindow] = []
        self.setObjectName("sciplotCompositionWindow")
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_DeleteOnClose,
            interactive,
        )
        self.resize(1480, 860)
        self.setMinimumSize(900, 620)
        self.setWindowTitle(f"{self.controller.project.name} — SciPlot Composition")

        self._build_toolbar()
        self._build_workspace()
        self._build_status_bar()
        self._connect_signals()
        self._apply_theme()
        self._sync_project_ui()
        self._initialize_documents()
        self._initializing = False

    def _action(
        self,
        text: str,
        shortcut: str | None,
        callback: Any,
        *,
        tooltip: str,
        object_name: str,
    ) -> QtGui.QAction:
        action = QtGui.QAction(text, self)
        action.setObjectName(object_name)
        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)
        if shortcut:
            action.setShortcut(QtGui.QKeySequence(shortcut))
        action.triggered.connect(callback)
        return action

    def _build_toolbar(self) -> None:
        toolbar = QtWidgets.QToolBar("Composition", self)
        toolbar.setObjectName("sciplotToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.toolbar = toolbar

        self.document_title = QtWidgets.QLabel(self.controller.project.name)
        self.document_title.setObjectName("documentTitle")
        self.document_title.setMinimumWidth(180)
        self.document_title.setMaximumWidth(310)
        toolbar.addWidget(self.document_title)
        self.state_chip = QtWidgets.QLabel()
        self.state_chip.setObjectName("stateChip")
        toolbar.addWidget(self.state_chip)
        toolbar.addSeparator()

        variant_label = QtWidgets.QLabel("Variant")
        variant_label.setObjectName("toolbarMeta")
        toolbar.addWidget(variant_label)
        self.variant_combo = QtWidgets.QComboBox()
        self.variant_combo.setObjectName("compositionVariantPicker")
        self.variant_combo.setAccessibleName("Composition variant")
        self.variant_combo.setMinimumWidth(120)
        toolbar.addWidget(self.variant_combo)
        self.duplicate_variant_action = self._action(
            "+",
            "Ctrl+Shift+D",
            lambda: self._duplicate_variant(),
            tooltip="Duplicate the active composition as an independent variant",
            object_name="duplicateCompositionVariantAction",
        )
        toolbar.addAction(self.duplicate_variant_action)
        toolbar.addSeparator()

        self.undo_action = self._action(
            "Undo",
            "Ctrl+Z",
            self._undo,
            tooltip="Undo the last accepted composition operation",
            object_name="undoAction",
        )
        self.redo_action = self._action(
            "Redo",
            "Ctrl+Shift+Z",
            self._redo,
            tooltip="Redo the last undone composition operation",
            object_name="redoAction",
        )
        toolbar.addActions([self.undo_action, self.redo_action])
        self.export_action = self._action(
            "Export + QA",
            "Ctrl+Shift+E",
            self._export_delivery,
            tooltip="Export exact-current PDF/TIFF and build a verified delivery",
            object_name="exportCompositionAction",
        )
        toolbar.addAction(self.export_action)
        toolbar.addSeparator()

        layout_label = QtWidgets.QLabel("Layout")
        layout_label.setObjectName("toolbarMeta")
        toolbar.addWidget(layout_label)
        self.layout_combo = QtWidgets.QComboBox()
        self.layout_combo.setObjectName("compositionLayoutPicker")
        self.layout_combo.setAccessibleName("Composition layout")
        for layout_id in composite_layout_ids():
            layout = composition_layout(layout_id)
            self.layout_combo.addItem(layout.label, layout_id)
        self.layout_combo.setMinimumWidth(205)
        toolbar.addWidget(self.layout_combo)

        height_label = QtWidgets.QLabel("Height")
        height_label.setObjectName("toolbarMeta")
        toolbar.addWidget(height_label)
        self.height_spin = QtWidgets.QDoubleSpinBox()
        self.height_spin.setObjectName("compositionHeightPicker")
        self.height_spin.setAccessibleName("Composition height in millimetres")
        self.height_spin.setRange(20.0, 170.0)
        self.height_spin.setDecimals(1)
        self.height_spin.setSingleStep(1.0)
        self.height_spin.setSuffix(" mm")
        self.height_spin.setKeyboardTracking(False)
        toolbar.addWidget(self.height_spin)

        legend_label = QtWidgets.QLabel("Legend")
        legend_label.setObjectName("toolbarMeta")
        toolbar.addWidget(legend_label)
        self.legend_combo = QtWidgets.QComboBox()
        self.legend_combo.setObjectName("compositionLegendPicker")
        self.legend_combo.setAccessibleName("Composition legend policy")
        legend_labels = {
            "auto": "Auto",
            "shared_when_equivalent": "Share when equivalent",
            "per_panel": "Per panel",
        }
        for policy in sorted(COMPOSITION_LEGEND_POLICIES):
            self.legend_combo.addItem(legend_labels[policy], policy)
        self.legend_combo.setMinimumWidth(145)
        toolbar.addWidget(self.legend_combo)
        toolbar.addSeparator()

        self.compile_action = self._action(
            "Rebuild",
            "Ctrl+R",
            self._compile_current,
            tooltip="Compile native Veusz page, grid, graphs, and panel labels",
            object_name="compileCompositionAction",
        )
        self.edit_action = self._action(
            "Edit Composite",
            "Ctrl+E",
            self._open_composite_canvas,
            tooltip="Open the exact-current composite in SciPlot Canvas",
            object_name="editCompositionAction",
        )
        toolbar.addActions([self.compile_action, self.edit_action])

    def _build_workspace(self) -> None:
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setObjectName("compositionSplitView")
        splitter.setChildrenCollapsible(False)

        board_frame = QtWidgets.QFrame()
        board_frame.setObjectName("canvasWell")
        board_layout = QtWidgets.QVBoxLayout(board_frame)
        board_layout.setContentsMargins(18, 14, 18, 18)
        board_layout.setSpacing(8)
        board_header = QtWidgets.QHBoxLayout()
        board_copy = QtWidgets.QVBoxLayout()
        self.board_title = QtWidgets.QLabel("Arrange on 183 mm")
        self.board_title.setObjectName("sectionTitle")
        self.board_subtitle = QtWidgets.QLabel(
            "Drag modules between exact slots; source VSZ files stay immutable."
        )
        self.board_subtitle.setObjectName("sectionSubtitle")
        self.board_subtitle.setWordWrap(True)
        board_copy.addWidget(self.board_title)
        board_copy.addWidget(self.board_subtitle)
        board_header.addLayout(board_copy, 1)
        self.geometry_label = QtWidgets.QLabel()
        self.geometry_label.setObjectName("stateChip")
        board_header.addWidget(self.geometry_label, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        board_layout.addLayout(board_header)
        self.board = CompositionBoard(parent=board_frame)
        board_layout.addWidget(self.board, 1)

        preview_frame = QtWidgets.QFrame()
        preview_frame.setObjectName("inspectorPanel")
        preview_layout = QtWidgets.QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(16, 14, 16, 16)
        preview_layout.setSpacing(8)
        preview_title = QtWidgets.QLabel("Exact native composite")
        preview_title.setObjectName("sectionTitle")
        self.preview_subtitle = QtWidgets.QLabel(
            "Live Veusz document preview • native vectors and text"
        )
        self.preview_subtitle.setObjectName("sectionSubtitle")
        self.preview_subtitle.setWordWrap(True)
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(self.preview_subtitle)
        self.preview_host = QtWidgets.QMainWindow()
        self.preview_host.setObjectName("canvasWell")
        self.preview_placeholder = QtWidgets.QLabel()
        self.preview_placeholder.setObjectName("emptyState")
        self.preview_placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_placeholder.setWordWrap(True)
        self.preview_stack = QtWidgets.QStackedWidget()
        self.preview_stack.setContentsMargins(8, 8, 8, 8)
        self.preview_stack.addWidget(self.preview_placeholder)
        self.preview_host.setCentralWidget(self.preview_stack)
        preview_layout.addWidget(self.preview_host, 1)

        splitter.addWidget(board_frame)
        splitter.addWidget(preview_frame)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([860, 560])
        self.splitter = splitter
        self.setCentralWidget(splitter)

    def _build_status_bar(self) -> None:
        status = QtWidgets.QStatusBar(self)
        self.setStatusBar(status)
        self.status_message = QtWidgets.QLabel("Composition workspace ready")
        self.selection_message = QtWidgets.QLabel("No module selected")
        self.revision_message = QtWidgets.QLabel()
        status.addWidget(self.status_message, 1)
        status.addPermanentWidget(self.selection_message)
        status.addPermanentWidget(self.revision_message)

    def _connect_signals(self) -> None:
        self.board.dropRequested.connect(self._drop_module)
        self.board.selectedModuleChanged.connect(self._module_selected)
        self.variant_combo.currentIndexChanged.connect(self._variant_changed)
        self.layout_combo.currentIndexChanged.connect(self._layout_changed)
        self.height_spin.editingFinished.connect(self._height_changed)
        self.legend_combo.currentIndexChanged.connect(self._legend_changed)
        self.controller.historyChanged.connect(self._history_changed)
        self.controller.compileStarted.connect(self._compile_started)
        self.controller.compileFinished.connect(self._compile_finished)
        self.controller.errorRaised.connect(self._controller_error)

    def _initialize_documents(self) -> None:
        try:
            previews = self.controller.load_source_previews()
            self.board.refresh(self.controller.project, previews)
            status = self.controller.authority_status()
            if self.controller.variant.ready_to_compile and not status.get(
                "document_exists"
            ):
                self.controller.ensure_compiled()
            self._refresh_native_preview()
            self.status_message.setText("Drag a module to rearrange the composition")
        except Exception as exc:
            self._show_error(str(exc), modal=False)

    def _apply_theme(self) -> None:
        self.theme_tokens = build_canvas_theme(self.palette())
        self.setStyleSheet(build_canvas_stylesheet(self.theme_tokens))
        canvas_color = QtGui.QColor(self.theme_tokens.canvas_well)
        dark_canvas = canvas_color.lightnessF() < 0.5
        self.board_title.setStyleSheet(
            f"color: {'#f7f9fb' if dark_canvas else self.theme_tokens.text};"
        )
        self.board_subtitle.setStyleSheet(
            f"color: {'#c9d1d9' if dark_canvas else self.theme_tokens.muted_text};"
        )
        self.board.set_theme(self.theme_tokens)
        if self.preview_adapter is not None:
            self.preview_adapter.set_display_surface(
                canvas_color=self.theme_tokens.canvas_well,
            )

    def _sync_project_ui(self) -> None:
        project = self.controller.project
        variant = project.active_variant
        self._syncing_controls = True
        try:
            self.variant_combo.clear()
            for candidate in project.variants:
                self.variant_combo.addItem(candidate.name, candidate.variant_id)
            variant_index = self.variant_combo.findData(variant.variant_id)
            self.variant_combo.setCurrentIndex(variant_index)
            layout_index = self.layout_combo.findData(variant.layout.layout_id)
            self.layout_combo.setCurrentIndex(layout_index)
            self.height_spin.setValue(variant.layout.canvas_height_mm)
            legend_index = self.legend_combo.findData(variant.legend_policy)
            self.legend_combo.setCurrentIndex(legend_index)
        finally:
            self._syncing_controls = False
        self.board.refresh(project, self.controller.source_previews)
        self.geometry_label.setText(f"183 × {variant.layout.canvas_height_mm:g} mm")
        self.state_chip.setText(variant.state.replace("_", " "))
        self.state_chip.setProperty("canvasState", variant.state)
        self.state_chip.style().unpolish(self.state_chip)
        self.state_chip.style().polish(self.state_chip)
        self.revision_message.setText(f"Revision {variant.revision}")
        self.undo_action.setEnabled(self.controller.can_undo)
        self.redo_action.setEnabled(self.controller.can_redo)
        self.edit_action.setEnabled(
            self.workspace.variant_document_path(variant.variant_id).is_file()
        )
        self.export_action.setEnabled(self.edit_action.isEnabled())

    def _close_preview_adapter(self) -> None:
        if self.preview_adapter is None:
            return
        adapter = self.preview_adapter
        self.preview_adapter = None
        self.preview_stack.removeWidget(adapter.plot_window)
        adapter.close()
        adapter.plot_window.setParent(None)
        adapter.plot_window.deleteLater()

    def _refresh_native_preview(self) -> None:
        self._close_preview_adapter()
        variant = self.controller.variant
        document = self.workspace.variant_document_path(variant.variant_id)
        if variant.compiled_document_ref is None or not document.is_file():
            self.preview_placeholder.setText(
                "The arrangement is a draft. Fill every publication slot to "
                "compile a new exact-current native composite."
            )
            self.preview_placeholder.show()
            self.preview_stack.setCurrentWidget(self.preview_placeholder)
            self.preview_subtitle.setText(
                "Draft model • previous compiled authority is preserved on disk"
            )
            return
        self.preview_placeholder.hide()
        self.preview_adapter = VeuszCanvasAdapter(
            document,
            parent=self.preview_host,
        )
        self.preview_adapter.plot_window.viewtoolbar.hide()
        self.preview_stack.addWidget(self.preview_adapter.plot_window)
        self.preview_stack.setCurrentWidget(self.preview_adapter.plot_window)
        if self.theme_tokens is not None:
            self.preview_adapter.set_display_surface(
                canvas_color=self.theme_tokens.canvas_well,
            )
        self.preview_adapter.zoom_to_page()
        self._schedule_preview_fit()
        authority = self.controller.authority_status()
        if authority.get("manual_edit_detected"):
            self.preview_subtitle.setText(
                "Exact-current manually edited VSZ • regeneration is protected"
            )
        else:
            self.preview_subtitle.setText(
                "Live Veusz document preview • native vectors and text"
            )

    def _schedule_preview_fit(self) -> None:
        if self._preview_fit_scheduled or self.preview_adapter is None:
            return
        self._preview_fit_scheduled = True
        QtCore.QTimer.singleShot(0, self._fit_native_preview)

    def _fit_native_preview(self) -> None:
        self._preview_fit_scheduled = False
        if self.preview_adapter is None:
            return
        try:
            self.preview_adapter.zoom_to_page()
        except RuntimeError:
            return

    def _run_transaction(self, batch: Any) -> CompositionTransactionResult | None:
        try:
            result = self.controller.apply_batch(batch)
        except CompositionAuthorityConflict:
            if not self.interactive:
                raise
            choice = QtWidgets.QMessageBox.warning(
                self,
                "Composite contains manual edits",
                "This exact-current VSZ has changed since compilation. SciPlot "
                "will never overwrite it silently. Archive the edited document "
                "and regenerate before applying this layout change?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel,
            )
            if choice != QtWidgets.QMessageBox.StandardButton.Yes:
                self.status_message.setText(
                    "Layout change cancelled; manual edits preserved"
                )
                return None
            result = self.controller.apply_batch(
                batch,
                regenerate_edited=True,
            )
        except Exception as exc:
            self._show_error(str(exc))
            return None
        self.last_transaction = result
        self._sync_project_ui()
        self._refresh_native_preview()
        return result

    def _drop_module(self, module_id: str, slot_ref: object) -> None:
        normalized = str(slot_ref) if slot_ref is not None else None
        batch = self.controller.placement_batch(module_id, normalized)
        result = self._run_transaction(batch)
        if result is None:
            self._sync_project_ui()
            return
        self.drop_count += 1
        change = result.receipt["changes"][0]
        occupant = change.get("swapped_module_id")
        suffix = f"; swapped with {occupant}" if occupant else ""
        self.status_message.setText(
            f"Placed {module_id} in {normalized or 'the module tray'}{suffix}"
        )

    def _layout_changed(self, _index: int) -> None:
        if self._syncing_controls or self._initializing:
            return
        layout_id = str(self.layout_combo.currentData())
        if layout_id == self.controller.variant.layout.layout_id:
            return
        self._run_transaction(self.controller.layout_batch(layout_id))

    def _variant_changed(self, _index: int) -> None:
        if self._syncing_controls or self._initializing:
            return
        variant_id = str(self.variant_combo.currentData())
        if variant_id == self.controller.project.active_variant_id:
            return
        try:
            self.controller.activate_variant(variant_id)
            document = self.workspace.variant_document_path(variant_id)
            if self.controller.variant.ready_to_compile and not document.is_file():
                self.controller.ensure_compiled()
            self._sync_project_ui()
            self._refresh_native_preview()
            self.status_message.setText(
                f"Activated composition variant {self.controller.variant.name}"
            )
        except Exception as exc:
            self._show_error(str(exc))

    def _duplicate_variant(self, name: str | None = None) -> None:
        suggested = name or f"Variant {len(self.controller.project.variants) + 1}"
        if name is None and self.interactive:
            value, accepted = QtWidgets.QInputDialog.getText(
                self,
                "Duplicate composition variant",
                "Variant name",
                text=suggested,
            )
            if not accepted:
                return
            suggested = value.strip()
        if not suggested:
            self._show_error("Composition variant name cannot be empty.")
            return
        try:
            self.controller.create_variant(suggested)
            if self.controller.variant.ready_to_compile:
                self.controller.ensure_compiled()
            self._sync_project_ui()
            self._refresh_native_preview()
            self.status_message.setText(
                f"Created independent variant {self.controller.variant.name}"
            )
        except Exception as exc:
            self._show_error(str(exc))

    def _height_changed(self) -> None:
        if self._syncing_controls or self._initializing:
            return
        height = float(self.height_spin.value())
        if abs(height - self.controller.variant.layout.canvas_height_mm) <= 1e-6:
            return
        self._run_transaction(self.controller.height_batch(height))

    def _legend_changed(self, _index: int) -> None:
        if self._syncing_controls or self._initializing:
            return
        policy = str(self.legend_combo.currentData())
        if policy == self.controller.variant.legend_policy:
            return
        self._run_transaction(self.controller.legend_policy_batch(policy))

    def _compile_current(self) -> None:
        try:
            status = self.controller.authority_status()
            self.controller.ensure_compiled(
                regenerate_edited=bool(status.get("manual_edit_detected")),
            )
            self._sync_project_ui()
            self._refresh_native_preview()
        except Exception as exc:
            self._show_error(str(exc))

    def _undo(self) -> None:
        try:
            self.last_transaction = self.controller.undo()
            self._sync_project_ui()
            self._refresh_native_preview()
            self.status_message.setText("Composition operation undone")
        except Exception as exc:
            self._show_error(str(exc))

    def _redo(self) -> None:
        try:
            self.last_transaction = self.controller.redo()
            self._sync_project_ui()
            self._refresh_native_preview()
            self.status_message.setText("Composition operation redone")
        except Exception as exc:
            self._show_error(str(exc))

    def _history_changed(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)

    def _module_selected(self, module_id: str) -> None:
        module = self.controller.project.source_module(module_id)
        placement = self.controller.variant.placement(module_id)
        self.selection_message.setText(
            f"{module.title} • {placement.slot_ref or 'module tray'}"
        )

    def _compile_started(self, _variant_id: str) -> None:
        self.status_message.setText("Compiling native Veusz composite…")
        self.compile_action.setEnabled(False)

    def _compile_finished(self, result: dict[str, Any]) -> None:
        self.compile_action.setEnabled(True)
        state = "already current" if result.get("idempotent") else "rebuilt"
        self.status_message.setText(f"Native composite {state}")

    def _controller_error(self, message: str) -> None:
        self.last_error = message
        self.compile_action.setEnabled(True)

    def _show_error(self, message: str, *, modal: bool = True) -> None:
        self.last_error = message
        self.status_message.setText(message)
        if modal and self.interactive:
            QtWidgets.QMessageBox.critical(self, "SciPlot Composition", message)

    def _open_composite_canvas(self) -> None:
        document = self.workspace.variant_document_path(
            self.controller.variant.variant_id
        )
        if not document.is_file():
            self._show_error("Compile the composite before opening it for editing.")
            return
        try:
            from sciplot_gui.main_window import SciPlotCanvasWindow
            from sciplot_gui.workspace import resolve_canvas_workspace

            canvas_workspace = resolve_canvas_workspace(document)
            child = SciPlotCanvasWindow(canvas_workspace)
            child.setWindowTitle(
                f"{self.controller.project.name} — Exact Composite Canvas"
            )
            child.destroyed.connect(
                lambda _object=None, child=child: self._composite_canvas_closed(child)
            )
            self._child_canvas_windows.append(child)
            child.show()
            child.raise_()
            self.status_message.setText(
                "Editing exact-current composite in SciPlot Canvas"
            )
        except Exception as exc:
            self._show_error(str(exc))

    def _export_delivery(self) -> None:
        try:
            from sciplot_core.composition_delivery import (
                export_composition_delivery,
            )

            self.status_message.setText("Exporting exact-current PDF/TIFF and QA…")
            self.export_action.setEnabled(False)
            QtWidgets.QApplication.processEvents()
            self.last_export = export_composition_delivery(self.workspace)
            if self.last_export.get("ready_to_use") is True:
                self.status_message.setText("Composition delivery is ready to use")
            else:
                self.status_message.setText(
                    "Composition delivery needs repair; inspect QA report"
                )
        except Exception as exc:
            self._show_error(str(exc))
        finally:
            self.export_action.setEnabled(True)

    def _composite_canvas_closed(self, closed: QtWidgets.QMainWindow) -> None:
        self._child_canvas_windows = [
            window for window in self._child_canvas_windows if window is not closed
        ]
        self.controller.reload()
        self._sync_project_ui()
        self._refresh_native_preview()
        authority = self.controller.authority_status()
        if authority.get("manual_edit_detected"):
            self.status_message.setText(
                "Manual composite edits preserved as exact-current authority"
            )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._close_preview_adapter()
        super().closeEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._schedule_preview_fit()


__all__ = ["SciPlotCompositionWindow"]
