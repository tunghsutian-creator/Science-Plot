"""Build and update the native SciPlot Project dock controls."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from PyQt6 import QtCore, QtGui, QtWidgets
from sciplot_core.studio import read_studio_figure_set
from sciplot_gui.studio_project_status import (
    _status_text,
)


class DockMixin:
    def _build_dock(self) -> QtWidgets.QDockWidget:
        dock = QtWidgets.QDockWidget("SciPlot Project", self.window)
        dock.setObjectName("sciplotStudioProjectDock")
        dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        body = QtWidgets.QWidget(dock)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        intro = QtWidgets.QLabel(
            "Read-only project, source, mapping, and exact-current QA status. "
            "All editing remains in Veusz."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.figure_group = QtWidgets.QGroupBox("Figures")
        figure_layout = QtWidgets.QVBoxLayout(self.figure_group)
        self.figure_list = QtWidgets.QListWidget()
        self.figure_list.setObjectName("sciplotStudioFigureList")
        self.figure_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.figure_list.setMinimumHeight(0)
        self.figure_list.setMaximumHeight(60)
        self.open_figure_button = QtWidgets.QPushButton("Open selected figure")
        self.open_figure_button.setToolTip(
            "Open the selected independent single-page VSZ in another "
            "integrated SciPlot Veusz window."
        )
        figure_layout.addWidget(self.figure_list)
        figure_layout.addWidget(self.open_figure_button)
        self.figure_group.hide()
        layout.addWidget(self.figure_group)

        self.status_view = QtWidgets.QPlainTextEdit()
        self.status_view.setReadOnly(True)
        self.status_view.setLineWrapMode(
            QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self.status_view.setMinimumWidth(320)
        layout.addWidget(self.status_view, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("Refresh Audit")
        self.export_button = QtWidgets.QPushButton("Save && Export PDF/TIFF")
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.export_button, 1)
        layout.addLayout(buttons)

        result_buttons = QtWidgets.QHBoxLayout()
        self.open_pdf_button = QtWidgets.QPushButton("Open PDF")
        self.show_delivery_button = QtWidgets.QPushButton("Show Delivery")
        self.reveal_vsz_button = QtWidgets.QPushButton("Reveal VSZ")
        self.open_pdf_button.setToolTip(
            "Open the current PDF that passed exact-current artifact QA."
        )
        self.show_delivery_button.setToolTip(
            "Show the current portable project delivery directory."
        )
        self.reveal_vsz_button.setToolTip(
            "Reveal the directory containing the authoritative Veusz document."
        )
        result_buttons.addWidget(self.open_pdf_button)
        result_buttons.addWidget(self.show_delivery_button)
        result_buttons.addWidget(self.reveal_vsz_button)
        layout.addLayout(result_buttons)
        dock.setWidget(body)
        return dock

    def _current_render_sha256(self) -> str | None:
        assistant = getattr(self.window, "_sciplot_assistant_bridge", None)
        if assistant is not None and hasattr(assistant, "current_render_sha256"):
            try:
                digest = assistant.current_render_sha256()
            except Exception:
                return None
            normalized = str(digest or "").strip().casefold()
            if len(normalized) == 64 and all(
                character in "0123456789abcdef" for character in normalized
            ):
                return normalized
        # The native plot pixmap can lag the Veusz document queue. Without the
        # assistant's revision-checked capture, no render digest is asserted.
        return None

    def _publish_status(self, status: dict[str, Any]) -> dict[str, Any]:
        self.status_snapshot = status
        self._populate_figure_list()
        self.status_view.setPlainText(_status_text(status))
        self._update_controls(status)
        self.statusChanged.emit(status)
        return status

    def bind_export_action(self, action: QtGui.QAction) -> None:
        self.export_action = action
        self._update_controls(self.status_snapshot)

    def bind_assistant(self, assistant: Any) -> None:
        identity = id(assistant)
        if identity in self._bound_assistant_ids:
            return
        self._bound_assistant_ids.add(identity)
        runner = getattr(assistant, "runner", None)
        active_changed = getattr(runner, "activeChanged", None)
        if active_changed is not None:
            active_changed.connect(self._assistant_state_changed)
        for name in (
            "requestSubmitted",
            "proposalReady",
            "proposalApplied",
            "requestRejected",
        ):
            signal = getattr(assistant, name, None)
            if signal is not None:
                signal.connect(self._assistant_state_changed)
        self._assistant_state_changed()

    def _assistant_state_changed(self, _value: object = None) -> None:
        try:
            self._update_controls(self.status_snapshot)
        except RuntimeError:
            pass

    def _figure_set_entries(self) -> list[dict[str, Any]]:
        if self.project_dir is None:
            return []
        registry = read_studio_figure_set(self.project_dir)
        if registry is None:
            return []
        studio_root = (self.project_dir / "studio").resolve()
        entries: list[dict[str, Any]] = []
        for value in registry.get("figures", []):
            if not isinstance(value, dict):
                continue
            figure_id = str(value.get("figure_id") or "").strip()
            if (
                not figure_id
                or Path(figure_id).name != figure_id
                or figure_id in {".", ".."}
            ):
                continue
            document_value = value.get("document")
            if not isinstance(document_value, str) or not document_value.strip():
                continue
            document = Path(document_value).expanduser().resolve()
            try:
                document.relative_to(studio_root)
            except ValueError:
                continue
            entries.append({**value, "document": str(document)})
        return sorted(
            entries,
            key=lambda item: (
                int(item.get("order") or 0),
                str(item.get("figure_id") or ""),
            ),
        )

    def _populate_figure_list(self) -> None:
        entries = self._figure_set_entries()
        selected_path = None
        selected = self.figure_list.currentItem()
        if selected is not None:
            selected_path = selected.data(QtCore.Qt.ItemDataRole.UserRole)
        self.figure_list.clear()
        current_item: QtWidgets.QListWidgetItem | None = None
        restored_item: QtWidgets.QListWidgetItem | None = None
        for entry in entries:
            title = str(entry.get("title") or entry.get("figure_id") or "Figure")
            status = str(entry.get("status") or "unavailable")
            suffix = "" if status == "ready" else f" — {status}"
            item = QtWidgets.QListWidgetItem(f"{title}{suffix}")
            document = str(entry["document"])
            item.setData(QtCore.Qt.ItemDataRole.UserRole, document)
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, status)
            if status != "ready" or not Path(document).is_file():
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled)
                unavailable = entry.get("unavailable")
                if isinstance(unavailable, dict):
                    item.setToolTip(str(unavailable.get("message") or status))
            elif Path(document).resolve() == self.document_path:
                current_item = item
                item.setText(f"{title} (current)")
            if document == selected_path:
                restored_item = item
            self.figure_list.addItem(item)
        self.figure_group.setVisible(bool(entries))
        chosen = restored_item or current_item
        if chosen is not None:
            self.figure_list.setCurrentItem(chosen)
        enabled = bool(
            chosen is not None
            and chosen.data(QtCore.Qt.ItemDataRole.UserRole + 1) == "ready"
        )
        self.open_figure_button.setEnabled(enabled)

    def _figure_selection_changed(self, current: Any, _previous: Any) -> None:
        self.open_figure_button.setEnabled(
            bool(
                not self._exporting
                and self._document_context_blocker() is None
                and current is not None
                and current.data(QtCore.Qt.ItemDataRole.UserRole + 1) == "ready"
            )
        )

    def open_selected_figure(self) -> bool:
        item = self.figure_list.currentItem()
        if item is None:
            return False
        value = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(value, str) or not value.strip():
            return False
        document = Path(value).expanduser().resolve()
        if (
            item.data(QtCore.Qt.ItemDataRole.UserRole + 1) != "ready"
            or not document.is_file()
        ):
            QtWidgets.QMessageBox.warning(
                self.window,
                "SciPlot figure unavailable",
                "This planned metric has no valid saved VSZ. SciPlot did not "
                "substitute another metric.",
            )
            return False
        if document == self.document_path:
            self.window.raise_()
            self.window.activateWindow()
            return True
        created = type(self.window).CreateWindow(str(document))
        return created is not None

    def _update_controls(self, status: dict[str, Any]) -> None:
        workflow = (
            status.get("workflow") if isinstance(status.get("workflow"), dict) else {}
        )
        exporting = bool(self._exporting or workflow.get("state") == "exporting")
        context_blocker = self._document_context_blocker()
        context_changed = context_blocker is not None
        self.refresh_button.setEnabled(not exporting and not context_changed)
        figure_blocker = self._figure_set_export_blocker()
        assistant_blocker = self._assistant_export_blocker()
        export_blocker = context_blocker or figure_blocker or assistant_blocker
        export_tooltip_blocker = (
            "An exact-current export is already in progress."
            if exporting
            else export_blocker
        )
        export_enabled = bool(not exporting and export_blocker is None)
        self.export_button.setEnabled(export_enabled)
        self.figure_list.setEnabled(not exporting and not context_changed)
        selected_figure = self.figure_list.currentItem()
        self.open_figure_button.setEnabled(
            bool(
                not exporting
                and not context_changed
                and selected_figure is not None
                and selected_figure.data(QtCore.Qt.ItemDataRole.UserRole + 1) == "ready"
            )
        )
        if self.export_action is not None:
            self.export_action.setEnabled(export_enabled)
            self.export_action.setToolTip(
                export_tooltip_blocker
                or "Save the current Veusz document, export PDF/TIFF, and run "
                "SciPlot artifact QA."
            )
        if self._figure_set_entries():
            if self._figure_set_export_scope() == "standalone":
                self.export_button.setText("Save && Export this figure")
                self.export_button.setToolTip(
                    export_tooltip_blocker
                    or "Export this independent secondary VSZ with its own "
                    "standalone exact-current PDF/TIFF receipt. It will not "
                    "modify the primary G-prime project receipt."
                )
            else:
                self.export_button.setText("Save && Export primary G′")
                self.export_button.setToolTip(
                    export_tooltip_blocker
                    or "Export the primary G-prime document and publish the "
                    "project delivery receipt."
                )
        else:
            self.export_button.setText("Save && Export PDF/TIFF")
            self.export_button.setToolTip(
                export_tooltip_blocker
                or "Save the current Veusz document, export PDF/TIFF, and run "
                "SciPlot artifact QA."
            )
        results = (
            status.get("results") if isinstance(status.get("results"), dict) else {}
        )
        for key, button in (
            ("pdf", self.open_pdf_button),
            ("delivery", self.show_delivery_button),
            ("vsz", self.reveal_vsz_button),
        ):
            target = results.get(key) if isinstance(results.get(key), dict) else {}
            button.setEnabled(
                bool(
                    not exporting
                    and not context_changed
                    and target.get("available") is True
                )
            )
