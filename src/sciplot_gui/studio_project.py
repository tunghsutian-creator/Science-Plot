from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core._utils import existing_file_sha256, json_safe
from sciplot_core._paths import resolved_path_is_within
from sciplot_core.studio import (
    _is_primary_figure_set_export_scope,
    _studio_figure_set_export_scope,
    atomic_save_veusz_document,
    export_studio_document,
    publish_standalone_export_receipt,
    publish_studio_export_run,
)

from .studio_project_status import (
    _bind_mapping_to_artifact_qa,
    _finalize_status,
    _live_document_payload,
    _qa_display_status,
    _read_json,
    _resolve_figure_set_export_scope as _resolve_status_figure_set_export_scope,
    _status_text,
    _validate_project_request_pair,
    _workflow_status,
    build_studio_project_status as _build_studio_project_status,
    export_result_message,
)


def _resolve_figure_set_export_scope(
    *,
    project_dir: Path,
    request: dict[str, Any],
    latest_run: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    return _resolve_status_figure_set_export_scope(
        project_dir=project_dir,
        request=request,
        latest_run=latest_run,
        _scope_builder=_studio_figure_set_export_scope,
    )


def build_studio_project_status(
    *,
    document_path: Path,
    document: Any,
    project_dir: Path | None,
    request_path: Path | None,
    render_sha256: str | None = None,
    audit_source: bool = False,
) -> dict[str, Any]:
    return _build_studio_project_status(
        document_path=document_path,
        document=document,
        project_dir=project_dir,
        request_path=request_path,
        render_sha256=render_sha256,
        audit_source=audit_source,
        _figure_set_scope_resolver=_resolve_figure_set_export_scope,
    )


class StudioProjectBridge(QtCore.QObject):
    """Read-only SciPlot status and exact-current export on one Veusz window."""

    statusChanged = QtCore.pyqtSignal(object)
    exportFinished = QtCore.pyqtSignal(object)

    def __init__(
        self,
        window: Any,
        document_path: Path,
        *,
        project_dir: Path | None,
        request_path: Path | None,
    ) -> None:
        _validate_project_request_pair(project_dir, request_path)
        super().__init__(window)
        self.window = window
        self.document = window.document
        self.plot = window.plot
        self.document_path = document_path.expanduser().resolve()
        self.project_dir = (
            project_dir.expanduser().resolve() if project_dir is not None else None
        )
        self.request_path = (
            request_path.expanduser().resolve() if request_path is not None else None
        )
        self.status_snapshot: dict[str, Any] = {}
        self._exporting = False
        self.export_action: QtGui.QAction | None = None
        self._bound_assistant_ids: set[int] = set()
        self.dock = self._build_dock()
        self.dock.hide()
        self.window.addDockWidget(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
            self.dock,
        )
        self.document.signalModified.connect(self._document_modified)
        self.dock.visibilityChanged.connect(self._dock_visibility_changed)
        self.refresh_button.clicked.connect(self.refresh_full)
        self.export_button.clicked.connect(self.export_current_document)
        self.figure_list.itemDoubleClicked.connect(
            lambda _item: self.open_selected_figure()
        )
        self.figure_list.currentItemChanged.connect(self._figure_selection_changed)
        self.open_figure_button.clicked.connect(self.open_selected_figure)
        self.open_pdf_button.clicked.connect(self.open_current_pdf)
        self.show_delivery_button.clicked.connect(self.show_current_delivery)
        self.reveal_vsz_button.clicked.connect(self.reveal_current_vsz)
        self.refresh()

    @property
    def mode(self) -> str:
        return "project" if self.project_dir is not None else "standalone_vsz"

    def _window_document_path(self) -> Path | None:
        filename = str(getattr(self.window, "filename", "") or "").strip()
        if not filename:
            return None
        try:
            return Path(filename).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return None

    def _document_context_blocker(self) -> str | None:
        current = self._window_document_path()
        if current == self.document_path:
            return None
        current_label = str(current) if current is not None else "an unsaved document"
        return (
            "This Veusz window now points to "
            f"{current_label}, but SciPlot Project remains bound to "
            f"{self.document_path}. Close this window and reopen the new VSZ "
            "so SciPlot can bind a fresh exact-current project context. The "
            "old project path will not be overwritten."
        )

    def _document_context_status(self, message: str) -> dict[str, Any]:
        status = dict(self.status_snapshot)
        workflow = (
            dict(status.get("workflow"))
            if isinstance(status.get("workflow"), dict)
            else {}
        )
        workflow.update(
            {
                "state": "document_context_changed",
                "audit_state": "blocked",
                "result_ready": False,
                "ready_to_use": False,
                "message": (
                    "The Veusz document context changed. Reopen this VSZ before "
                    "using prior results or exporting."
                ),
            }
        )
        qa = dict(status.get("qa")) if isinstance(status.get("qa"), dict) else {}
        for key in tuple(qa):
            if key == "current" or key.endswith("_current"):
                qa[key] = False
        qa.update(
            {
                "status": "stale_for_document_context",
                "ready_to_use": False,
                "current_document": False,
                "document_hash_current": False,
                "artifact_qa_current": False,
                "exports_current": False,
                "qa_report_current": False,
                "state": "document_context_changed",
            }
        )
        provenance = (
            dict(status.get("provenance"))
            if isinstance(status.get("provenance"), dict)
            else {}
        )
        for key in tuple(provenance):
            if (
                key == "current"
                or key == "complete"
                or key.endswith("_current")
                or key.endswith("_complete")
            ):
                provenance[key] = False
        provenance.update(
            {
                "status": "document_context_changed",
                "complete": False,
                "full_project_evidence_current": False,
                "primary_figure_evidence_current": False,
                "project_delivery_current": False,
                "delivery_scope_known": False,
            }
        )
        results = (
            dict(status.get("results"))
            if isinstance(status.get("results"), dict)
            else {}
        )
        for key, value in tuple(results.items()):
            target = dict(value) if isinstance(value, dict) else {}
            target["current"] = False
            target["available"] = False
            results[key] = target
        project = (
            dict(status.get("project"))
            if isinstance(status.get("project"), dict)
            else status.get("project")
        )
        if isinstance(project, dict):
            project["request_snapshot_current"] = False
        status.update(
            {
                "kind": "sciplot_studio_project_status",
                "version": 1,
                "mode": self.mode,
                "state": "document_context_changed",
                "ready_to_use": False,
                "workflow": workflow,
                "project": project,
                "qa": qa,
                "provenance": provenance,
                "results": results,
                "document_context": {
                    "state": "document_context_changed",
                    "bound_document": str(self.document_path),
                    "window_document": (
                        str(self._window_document_path())
                        if self._window_document_path() is not None
                        else None
                    ),
                    "message": message,
                },
            }
        )
        return status

    def handle_document_context_changed(self) -> dict[str, Any] | None:
        message = self._document_context_blocker()
        if message is None:
            return None
        status = self._document_context_status(message)
        self._publish_status(status)
        self.status_view.setPlainText(
            f"{_status_text(status)}\n\nDocument context changed: {message}"
        )
        return status

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

    @QtCore.pyqtSlot()
    @QtCore.pyqtSlot(bool)
    @QtCore.pyqtSlot(object)
    @QtCore.pyqtSlot(str)
    def _assistant_state_changed(self, _value: object = None) -> None:
        try:
            self._update_controls(self.status_snapshot)
        except RuntimeError:
            pass

    def _figure_set_entries(self) -> list[dict[str, Any]]:
        if self.project_dir is None:
            return []
        registry_path = self.project_dir / "studio" / "figure_set.json"
        try:
            registry = _read_json(registry_path)
        except (OSError, ValueError, json.JSONDecodeError):
            return []
        if registry.get("kind") != "sciplot_studio_figure_set":
            return []
        studio_root = (self.project_dir / "studio").resolve()
        primary_figure_id = str(registry.get("primary_figure_id") or "").strip()
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
            document = (
                studio_root / "document.vsz"
                if figure_id == primary_figure_id
                else studio_root / "figures" / f"{figure_id}.vsz"
            ).resolve()
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

    @QtCore.pyqtSlot()
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

    def _audit_failure_status(self, exc: Exception) -> dict[str, Any]:
        if self.status_snapshot:
            status = {
                **self.status_snapshot,
                "audit_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
            workflow = (
                dict(status.get("workflow"))
                if isinstance(status.get("workflow"), dict)
                else _workflow_status(status)
            )
            workflow["audit_state"] = "failed"
            status["workflow"] = workflow
        else:
            status = {
                "kind": "sciplot_studio_project_status",
                "version": 1,
                "mode": self.mode,
                "project": None,
                "document": _live_document_payload(
                    document_path=self.document_path,
                    document=self.document,
                    render_sha256=None,
                ),
                "source": {
                    "status": "audit_failed",
                    "path": None,
                    "audit_status": "audit_failed",
                },
                "mapping": {
                    "status": "audit_failed",
                    "coverage_status": "unknown",
                },
                "provenance": {
                    "status": "audit_failed",
                    "complete": False,
                    "full_project_evidence_current": False,
                },
                "qa": {
                    "status": "audit_failed",
                    "artifact_status": "not_run",
                    "artifact_qa_current": False,
                    "exports_current": False,
                    "evidence": None,
                },
                "audit_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        self.status_snapshot = status
        self.status_view.setPlainText(
            f"{_status_text(status)}\n\nAudit error: {type(exc).__name__}: {exc}"
        )
        self._update_controls(status)
        self.statusChanged.emit(status)
        return status

    def refresh(
        self,
        *,
        capture_render: bool = False,
        audit_source: bool = False,
    ) -> dict[str, Any]:
        context_status = self.handle_document_context_changed()
        if context_status is not None:
            return context_status
        render_sha256 = (
            self._current_render_sha256()
            if capture_render
            else self.status_snapshot.get("document", {}).get("live_render_sha256")
        )
        if self.status_snapshot:
            previous_revision = self.status_snapshot.get("document", {}).get("revision")
            if previous_revision != int(self.document.changeset):
                render_sha256 = None
        try:
            status = build_studio_project_status(
                document_path=self.document_path,
                document=self.document,
                project_dir=self.project_dir,
                request_path=self.request_path,
                render_sha256=render_sha256,
                audit_source=audit_source,
            )
        except Exception as exc:
            return self._audit_failure_status(exc)
        return self._publish_status(status)

    def _refresh_document_state(self) -> dict[str, Any]:
        context_status = self.handle_document_context_changed()
        if context_status is not None:
            return context_status
        if not self.status_snapshot:
            return self.refresh()
        previous_document = (
            self.status_snapshot.get("document")
            if isinstance(self.status_snapshot.get("document"), dict)
            else {}
        )
        previous_revision = previous_document.get("revision")
        current_revision = int(self.document.changeset)
        render_sha256 = (
            previous_document.get("live_render_sha256")
            if previous_revision == current_revision
            else None
        )
        live_document = _live_document_payload(
            document_path=self.document_path,
            document=self.document,
            render_sha256=(
                str(render_sha256) if isinstance(render_sha256, str) else None
            ),
            saved_sha256=(
                str(previous_document.get("saved_sha256"))
                if previous_document.get("saved_sha256")
                else None
            ),
        )
        status = {
            **self.status_snapshot,
            "document": live_document,
        }
        previous_qa = status.get("qa") if isinstance(status.get("qa"), dict) else {}
        qa = dict(previous_qa)
        if qa.get("evidence") is not None:
            evidence_hash = qa.get("evidence_document_sha256")
            document_hash_current = bool(
                live_document.get("modified") is False
                and live_document.get("saved_sha256")
                and evidence_hash
                and live_document.get("saved_sha256") == evidence_hash
            )
            current_document = bool(
                document_hash_current and qa.get("exports_current") is True
            )
            qa_status, artifact_qa_current = _qa_display_status(
                artifact_status=str(qa.get("artifact_status") or "not_run"),
                ready=qa.get("ready_to_use") is True,
                current_document=current_document,
                exports_current=qa.get("exports_current") is True,
            )
            qa.update(
                {
                    "status": qa_status,
                    "current_document": current_document,
                    "document_hash_current": document_hash_current,
                    "artifact_qa_current": artifact_qa_current,
                }
            )
        status["qa"] = qa
        if (
            status.get("mode") == "project"
            and status.get("document_scope") != "project_secondary_standalone_receipt"
        ):
            mapping = (
                status.get("mapping") if isinstance(status.get("mapping"), dict) else {}
            )
            mapping = _bind_mapping_to_artifact_qa(
                mapping,
                artifact_qa_current=qa.get("artifact_qa_current") is True,
            )
            status["mapping"] = mapping
            provenance = (
                dict(status.get("provenance"))
                if isinstance(status.get("provenance"), dict)
                else {}
            )
            mapping_current = mapping.get("status") in {
                "not_applied",
                "verified",
            }
            current_evidence = bool(
                provenance.get("run_evidence_complete") is True
                and provenance.get("source_current") is True
                and mapping_current
                and qa.get("artifact_qa_current") is True
            )
            figure_set_scope_status = str(
                provenance.get("figure_set_export_scope_status") or ""
            )
            full_figure_set_scope = bool(
                figure_set_scope_status in {"persisted", "recomputed_current_project"}
                and _is_primary_figure_set_export_scope(
                    provenance.get("figure_set_export_scope")
                )
            )
            full_project_scope = bool(
                figure_set_scope_status == "not_applicable"
                or full_figure_set_scope
            )
            delivery_scope_known = full_project_scope
            primary_current = bool(current_evidence and full_figure_set_scope)
            full_current = bool(current_evidence and full_project_scope)
            source = (
                status.get("source") if isinstance(status.get("source"), dict) else {}
            )
            audit_pending = bool(
                source.get("audit_status") == "not_computed"
                or mapping.get("status") == "audit_pending"
            )
            current_result_awaiting_audit = bool(
                provenance.get("run_evidence_complete") is True
                and qa.get("artifact_qa_current") is True
                and audit_pending
                and delivery_scope_known
            )
            provenance.update(
                {
                    "status": (
                        "unknown_or_incomplete_figure_set_scope"
                        if not delivery_scope_known
                        else "current_full_project_evidence"
                        if full_current
                        else "current_primary_figure_evidence"
                        if primary_current
                        else "audit_pending_for_current_project"
                        if current_result_awaiting_audit
                        else "incomplete_or_stale_project_evidence"
                    ),
                    "complete": full_current,
                    "full_project_evidence_current": full_current,
                    "primary_figure_evidence_current": primary_current,
                    "delivery_scope_known": delivery_scope_known,
                    "primary_figure_delivery_current": bool(
                        provenance.get("project_delivery_current") is True
                        and full_figure_set_scope
                    ),
                    "full_project_delivery_current": bool(
                        provenance.get("project_delivery_current") is True
                        and full_project_scope
                    ),
                    "audit_pending": current_result_awaiting_audit,
                    "artifact_qa_current": (qa.get("artifact_qa_current") is True),
                    "mapping_current": mapping_current,
                }
            )
            status["provenance"] = provenance
        results = (
            dict(status.get("results"))
            if isinstance(status.get("results"), dict)
            else {}
        )
        pdf = dict(results.get("pdf")) if isinstance(results.get("pdf"), dict) else {}
        pdf["current"] = bool(pdf.get("path") and qa.get("artifact_qa_current") is True)
        results["pdf"] = pdf
        delivery = (
            dict(results.get("delivery"))
            if isinstance(results.get("delivery"), dict)
            else {}
        )
        delivery["current"] = bool(
            delivery.get("path")
            and qa.get("artifact_qa_current") is True
            and status.get("provenance", {}).get("project_delivery_current") is True
            and status.get("provenance", {}).get("delivery_scope_known") is True
        )
        results["delivery"] = delivery
        status["results"] = results
        return self._publish_status(_finalize_status(status))

    @QtCore.pyqtSlot()
    def refresh_full(self) -> None:
        self.refresh(capture_render=True, audit_source=True)

    @QtCore.pyqtSlot(int)
    def _document_modified(self, _modified: int) -> None:
        if self._exporting:
            return
        try:
            self._refresh_document_state()
        except Exception as exc:
            self._audit_failure_status(exc)

    @QtCore.pyqtSlot(bool)
    def _dock_visibility_changed(self, visible: bool) -> None:
        if visible and not self._exporting:
            self._refresh_document_state()

    def _open_local_path(self, path: Path) -> bool:
        return bool(
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
        )

    def _open_result_target(
        self,
        key: str,
        *,
        reveal: bool = False,
    ) -> bool:
        results = (
            self.status_snapshot.get("results")
            if isinstance(self.status_snapshot.get("results"), dict)
            else {}
        )
        target = results.get(key) if isinstance(results.get(key), dict) else {}
        value = target.get("reveal_path") if reveal else target.get("path")
        if target.get("available") is not True or not isinstance(value, str):
            QtWidgets.QMessageBox.warning(
                self.window,
                "SciPlot result unavailable",
                "This result is not current and available yet.",
            )
            return False
        try:
            path = Path(value).expanduser().resolve()
            root_value = target.get("evidence_root")
            evidence_root = (
                Path(str(root_value)).expanduser().resolve()
                if isinstance(root_value, str) and root_value.strip()
                else None
            )
            within_root = bool(
                evidence_root is not None
                and resolved_path_is_within(path, evidence_root)
            )
            exists = path.is_dir() if reveal or key == "delivery" else path.is_file()
            expected_sha256 = str(target.get("sha256") or "").strip()
            hash_current = bool(
                not expected_sha256 or existing_file_sha256(path) == expected_sha256
            )
        except (OSError, RuntimeError, ValueError):
            exists = False
            within_root = False
            hash_current = False
            path = Path(value)
        if not (exists and within_root and hash_current):
            QtWidgets.QMessageBox.warning(
                self.window,
                "SciPlot result unavailable",
                "The result path is missing, changed, or outside its "
                f"validated root:\n{path}",
            )
            return False
        if self._open_local_path(path):
            return True
        QtWidgets.QMessageBox.warning(
            self.window,
            "SciPlot could not open the result",
            f"The operating system did not open:\n{path}",
        )
        return False

    @QtCore.pyqtSlot()
    def open_current_pdf(self) -> bool:
        return self._open_result_target("pdf")

    @QtCore.pyqtSlot()
    def show_current_delivery(self) -> bool:
        return self._open_result_target("delivery")

    @QtCore.pyqtSlot()
    def reveal_current_vsz(self) -> bool:
        return self._open_result_target("vsz", reveal=True)

    def _project_export(self) -> dict[str, Any]:
        assert self.project_dir is not None
        assert self.request_path is not None
        if self._figure_set_export_scope() != "project":
            raise RuntimeError(
                "Only the canonical project/studio/document.vsz may publish "
                "a project delivery receipt."
            )
        export_payload = export_studio_document(
            self.document_path,
            formats=["pdf", "tiff_300"],
        )
        exports = list(export_payload.get("exports") or [])
        export_document_sha256 = str(
            export_payload.get("document_sha256") or ""
        ).strip()
        run = publish_studio_export_run(
            project_dir=self.project_dir,
            request_path=self.request_path,
            document_path=self.document_path,
            exports=exports,
            export_document_sha256=export_document_sha256,
        )
        figure_set_export_scope = run.get("figure_set_export_scope")
        if (
            figure_set_export_scope is not None
            and not _is_primary_figure_set_export_scope(figure_set_export_scope)
        ):
            raise RuntimeError(
                "The project run returned a missing or malformed figure-set "
                "delivery scope, so SciPlot did not accept it as ready."
            )
        scope = (
            "full_figure_set_project_delivery"
            if _is_primary_figure_set_export_scope(figure_set_export_scope)
            else "project_delivery"
        )
        result = {
            "kind": "sciplot_studio_menu_export",
            "version": 1,
            "scope": scope,
            "status": "passed" if run.get("ready_to_use") is True else "failed",
            "state": run.get("state"),
            "ready_to_use": run.get("ready_to_use") is True,
            "export_payload": json_safe(export_payload),
            "exports": json_safe(run.get("exports") or exports),
            "studio_run": json_safe(run),
        }
        if isinstance(figure_set_export_scope, dict):
            result["figure_set_export_scope"] = json_safe(figure_set_export_scope)
        return result

    def _standalone_export(self) -> dict[str, Any]:
        if (
            self.project_dir is not None
            and self._figure_set_export_scope() == "standalone"
        ):
            artifact_root = (
                self.document_path.parent / "exports" / self.document_path.stem
            )
        else:
            artifact_root = self.document_path.parent / "exports"
        export_payload = export_studio_document(
            self.document_path,
            formats=["pdf", "tiff_300"],
            output_dir=artifact_root / "figures",
        )
        exports = list(export_payload.get("exports") or [])
        export_document_sha256 = str(
            export_payload.get("document_sha256") or ""
        ).strip()
        receipt = publish_standalone_export_receipt(
            document_path=self.document_path,
            requested_formats=["pdf", "tiff_300"],
            exports=exports,
            artifact_root=artifact_root,
            export_document_sha256=export_document_sha256,
        )
        return {
            "kind": "sciplot_studio_menu_export",
            "version": 1,
            "scope": "standalone_exact_current_export",
            "status": receipt.get("status"),
            "state": receipt.get("state"),
            "ready_to_use": receipt.get("export_ready") is True,
            "export_payload": json_safe(export_payload),
            "exports": json_safe(exports),
            "standalone_export": json_safe(receipt),
        }

    def _assistant_export_blocker(self) -> str | None:
        assistant = getattr(
            self.window,
            "_sciplot_assistant_bridge",
            None,
        )
        if assistant is None:
            return None
        try:
            runner = getattr(assistant, "runner", None)
            if runner is not None and bool(getattr(runner, "active", False)):
                return (
                    "Wait for the active SciPlot AI request to finish or stop "
                    "it before exporting."
                )
            pending = getattr(assistant, "pending_batch", None)
            if pending is None:
                pending = getattr(assistant, "_pending_batch", None)
            if pending is not None:
                return (
                    "Accept or reject the pending SciPlot AI proposal before exporting."
                )
        except Exception as exc:
            return (
                "SciPlot could not establish a safe AI transaction state: "
                f"{type(exc).__name__}: {exc}"
            )
        return None

    def _figure_set_export_scope(self) -> str:
        if self.project_dir is None:
            return "standalone"
        canonical_primary = (self.project_dir / "studio" / "document.vsz").resolve()
        return "project" if self.document_path == canonical_primary else "standalone"

    def _current_project_figure_set_scope(self) -> dict[str, Any] | None:
        if (
            self.project_dir is None
            or self.request_path is None
            or self._figure_set_export_scope() != "project"
        ):
            return None
        request = _read_json(self.request_path)
        scope = _studio_figure_set_export_scope(
            self.project_dir,
            request=request,
        )
        return dict(scope) if _is_primary_figure_set_export_scope(scope) else None

    def _figure_set_export_blocker(self) -> str | None:
        if (
            self.project_dir is None
            or self.request_path is None
            or self._figure_set_export_scope() != "project"
        ):
            return None
        try:
            request = _read_json(self.request_path)
            scope = _studio_figure_set_export_scope(
                self.project_dir,
                request=request,
            )
        except Exception as exc:
            return (
                "SciPlot could not establish the current figure-set delivery "
                f"scope: {type(exc).__name__}: {exc}"
            )
        if _is_primary_figure_set_export_scope(scope):
            return None
        if (
            scope is not None
            or (self.project_dir / "studio" / "figure_set.json").exists()
        ):
            return (
                "SciPlot cannot establish a complete all-figures figure-set "
                "scope from the current request and registry. Export is blocked "
                "until that scope is repaired."
            )
        return None

    def _project_delivery_scope(self) -> str:
        if self.mode == "project" and self._figure_set_export_scope() == "project":
            try:
                scope = self._current_project_figure_set_scope()
            except Exception:
                scope = None
            if _is_primary_figure_set_export_scope(scope):
                return "full_figure_set_project_delivery"
            return "project_delivery"
        return "standalone_exact_current_export"

    def _failed_export_payload(
        self,
        *,
        state: str,
        message: str,
        error_type: str = "RuntimeError",
        unaccepted_export: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "sciplot_studio_menu_export",
            "version": 1,
            "scope": self._project_delivery_scope(),
            "status": "failed",
            "state": state,
            "ready_to_use": False,
            "error": {
                "type": error_type,
                "message": message,
            },
        }
        if unaccepted_export is not None:
            payload["unaccepted_export"] = json_safe(unaccepted_export)
        return payload

    def _show_export_message(self, payload: dict[str, Any]) -> None:
        level, title, message = export_result_message(payload)
        if level == "information":
            QtWidgets.QMessageBox.information(self.window, title, message)
        else:
            QtWidgets.QMessageBox.warning(self.window, title, message)

    @QtCore.pyqtSlot()
    def export_current_document(
        self,
        *,
        show_dialog: bool = True,
    ) -> dict[str, Any]:
        if self._exporting:
            return self._failed_export_payload(
                state="export_in_progress",
                message=(
                    "An exact-current export is already in progress. Wait for "
                    "it to finish before starting another export."
                ),
            )
        context_blocker = self._document_context_blocker()
        figure_blocker = self._figure_set_export_blocker()
        blocker = context_blocker or figure_blocker
        if blocker is None:
            blocker = self._assistant_export_blocker()
        if blocker is not None:
            payload = self._failed_export_payload(
                state=(
                    "document_context_changed"
                    if context_blocker is not None
                    else "figure_set_scope_incomplete"
                    if figure_blocker is not None
                    else "assistant_transaction_pending"
                ),
                message=blocker,
            )
            if show_dialog:
                self._show_export_message(payload)
        else:
            self._exporting = True
            self._publish_status(
                _finalize_status(
                    self.status_snapshot,
                    exporting=True,
                )
            )
            QtWidgets.QApplication.processEvents()
            try:
                pre_save_revision = int(self.document.changeset)
                pre_save_modified = bool(self.document.isModified())
                context_blocker = self._document_context_blocker()
                if context_blocker is not None:
                    raise RuntimeError(context_blocker)
                save_receipt = atomic_save_veusz_document(
                    self.document,
                    self.document_path,
                )
                if (
                    save_receipt.get("status") != "passed"
                    or save_receipt.get("reopen_validated") is not True
                    or save_receipt.get("ready_for_export") is not True
                ):
                    raise RuntimeError(
                        "The Veusz document was saved atomically, but SciPlot "
                        "could not validate a secure-mode structural reopen. "
                        "Exact-current export is blocked until the document "
                        "contains only safely reopenable commands."
                    )
                export_revision = int(self.document.changeset)
                if bool(self.document.isModified()):
                    raise RuntimeError(
                        "The Veusz document remained modified after save."
                    )
                export_document_sha256 = existing_file_sha256(self.document_path)
                if not export_document_sha256:
                    raise RuntimeError(
                        "The saved Veusz document has no readable SHA-256."
                    )
                figure_blocker = self._figure_set_export_blocker()
                blocker = figure_blocker or self._assistant_export_blocker()
                context_blocker = self._document_context_blocker()
                if context_blocker is not None:
                    raise RuntimeError(context_blocker)
                if blocker is not None:
                    raise RuntimeError(blocker)
                accepted_export = (
                    self._project_export()
                    if self.mode == "project"
                    and self._figure_set_export_scope() == "project"
                    else self._standalone_export()
                )
                post_revision = int(self.document.changeset)
                post_modified = bool(self.document.isModified())
                post_document_sha256 = existing_file_sha256(self.document_path)
                post_figure_blocker = self._figure_set_export_blocker()
                post_blocker = post_figure_blocker or self._assistant_export_blocker()
                post_context_blocker = self._document_context_blocker()
                changed_during_export = bool(
                    post_revision != export_revision
                    or post_modified
                    or post_document_sha256 != export_document_sha256
                    or post_blocker is not None
                    or post_context_blocker is not None
                )
                if changed_during_export:
                    details = post_context_blocker or (
                        "The Veusz document or AI transaction state changed "
                        "while SciPlot was exporting. The written artifacts "
                        "were not accepted as current GUI evidence."
                    )
                    payload = self._failed_export_payload(
                        state=(
                            "document_context_changed"
                            if post_context_blocker is not None
                            else "document_changed_during_export"
                        ),
                        message=details,
                        unaccepted_export=accepted_export,
                    )
                else:
                    payload = {
                        **accepted_export,
                        "export_guard": {
                            "pre_save_revision": pre_save_revision,
                            "pre_save_modified": pre_save_modified,
                            "export_revision": export_revision,
                            "post_export_revision": post_revision,
                            "post_export_modified": post_modified,
                            "document_sha256": export_document_sha256,
                        },
                    }
            except Exception as exc:
                context_blocker = self._document_context_blocker()
                payload = self._failed_export_payload(
                    state=(
                        "document_context_changed"
                        if context_blocker is not None
                        else "export_exception"
                    ),
                    message=context_blocker or str(exc),
                    error_type=type(exc).__name__,
                )
                if show_dialog:
                    QtWidgets.QMessageBox.critical(
                        self.window,
                        "SciPlot export failed",
                        str(exc),
                    )
            else:
                if show_dialog:
                    self._show_export_message(payload)
        self._exporting = False
        if self.handle_document_context_changed() is None:
            self.refresh(capture_render=False, audit_source=False)
        self.exportFinished.emit(payload)
        return payload


def attach_studio_project(
    window: Any,
    document_path: Path,
    *,
    project_dir: Path | None = None,
    request_path: Path | None = None,
) -> StudioProjectBridge:
    _validate_project_request_pair(project_dir, request_path)
    existing = getattr(window, "_sciplot_project_bridge", None)
    if isinstance(existing, StudioProjectBridge):
        return existing
    bridge = StudioProjectBridge(
        window,
        document_path,
        project_dir=project_dir,
        request_path=request_path,
    )
    window._sciplot_project_bridge = bridge
    return bridge


__all__ = [
    "StudioProjectBridge",
    "attach_studio_project",
    "build_studio_project_status",
    "export_result_message",
]
