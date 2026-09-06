"""Review and apply bounded project revisions from the native Project dock."""

from __future__ import annotations

from copy import deepcopy
from functools import partial
from pathlib import Path
from typing import Any

from PyQt6 import QtWidgets

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_gui.studio_project.change_dialogs import (
    SourceUpdateDialog,
    confirm_project_change,
)
from sciplot_gui.studio_project.change_worker import (
    ProjectChangeCloseGuard,
    ProjectChangeProgress,
    ProjectChangeWorker,
)
from sciplot_gui.studio_project.services import project_change_service


class ProjectChangesMixin:
    def _build_project_change_controls(self, layout: QtWidgets.QVBoxLayout) -> None:
        buttons = QtWidgets.QHBoxLayout()
        self.recover_delivery_button = QtWidgets.QPushButton("Recover visible edits…")
        self.recover_delivery_button.setObjectName("sciplotRecoverDelivery")
        self.update_source_button = QtWidgets.QPushButton("Update source…")
        self.update_source_button.setObjectName("sciplotUpdateSource")
        buttons.addWidget(self.recover_delivery_button)
        buttons.addWidget(self.update_source_button)
        layout.addLayout(buttons)

    def _initialize_project_changes(self) -> None:
        self._project_change_busy = False
        self._project_change_preview: dict[str, Any] | None = None
        self._project_change_native_state: tuple[int, str | None] | None = None
        self._project_change_job: ProjectChangeWorker | None = None
        self._project_change_close_guard = ProjectChangeCloseGuard(
            self.window, lambda: self._project_change_busy
        )
        self.window.installEventFilter(self._project_change_close_guard)
        self.recover_delivery_button.clicked.connect(
            lambda: self.start_project_change_preview("delivery_recovery")
        )
        self.update_source_button.clicked.connect(self.select_project_source_update)

    def _project_change_blocker(self) -> str | None:
        if getattr(self, "_project_change_busy", False):
            return "A project preview or update is in progress. Wait for it to finish."
        if self.project_dir is None:
            return (
                "Open a managed SciPlot project to recover edits or update its source."
            )
        if self.document_path != self.project_dir / "studio" / "document.vsz":
            return "Open the primary managed document before changing the project."
        context = self._document_context_blocker()
        if context:
            return context
        if self._exporting:
            return "Wait for the current export before changing the project."
        if self.document.isModified():
            return "Save or undo the current Veusz edits before previewing a project change."
        assistant = self._assistant_export_blocker()
        if assistant:
            return "Finish or discard the pending AI work before changing the project."
        revision = self._series_revision_export_blocker()
        if revision:
            return "Commit or undo the sample revision before changing the project."
        for window in getattr(type(self.window), "windows", []):
            bridge = getattr(window, "_sciplot_project_bridge", None)
            if (
                window is not self.window
                and getattr(bridge, "project_dir", None) == self.project_dir
            ):
                return "Close the other windows for this project before updating it, so they cannot save an older revision."
        return None

    def _update_project_change_controls(self) -> None:
        blocker = self._project_change_blocker()
        for operation, button in (
            ("delivery_recovery", self.recover_delivery_button),
            ("source_update", self.update_source_button),
        ):
            available = (
                project_change_service(operation) is not None
                and project_change_service(operation, apply=True) is not None
            )
            button.setEnabled(blocker is None and available)
            button.setToolTip(
                blocker
                or (
                    "Preview changes before explicitly applying them."
                    if available
                    else "This integration does not provide project revision services."
                )
            )

    def _project_native_state(self) -> tuple[int, str | None]:
        return int(self.document.changeset), existing_file_sha256(self.document_path)

    def select_project_source_update(self) -> None:
        blocker = self._project_change_blocker()
        if blocker:
            self._project_change_message(blocker, show_dialog=True)
            return
        dialog = SourceUpdateDialog(self.window)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            source, worksheet = dialog.selection()
            self.start_project_change_preview(
                "source_update", source=source, worksheet=worksheet
            )

    def start_project_change_preview(
        self,
        operation: str,
        *,
        source: Path | None = None,
        worksheet: str | None = None,
        show_dialog: bool = True,
    ) -> bool:
        blocker = self._project_change_blocker()
        service = project_change_service(operation)
        if blocker or service is None:
            self._project_change_message(
                blocker or "Project revision service unavailable.",
                show_dialog=show_dialog,
            )
            return False
        if operation == "source_update" and source is None:
            self._project_change_message(
                "Select a source file or directory first.", show_dialog=show_dialog
            )
            return False
        self._project_change_preview = None
        self._project_change_native_state = self._project_native_state()
        call = (
            partial(service, self.project_dir, source, worksheet=worksheet)
            if operation == "source_update"
            else partial(service, self.project_dir)
        )
        self._start_project_change_job(operation, "preview", call, show_dialog)
        return True

    def apply_project_change_preview(self, *, show_dialog: bool = True) -> bool:
        blocker = self._project_change_blocker()
        preview = self._project_change_preview
        if (
            not blocker
            and self._project_native_state() != self._project_change_native_state
        ):
            blocker = (
                "The open document changed after preview. Preview and review it again."
            )
        if not blocker and (preview is None or preview.get("status") != "ready"):
            blocker = "A successful current preview is required before Apply."
        if blocker:
            self._project_change_message(blocker, show_dialog=show_dialog)
            return False
        operation = self._project_change_operation
        service = project_change_service(operation, apply=True)
        if service is None:
            self._project_change_message(
                "Project revision service unavailable.", show_dialog=show_dialog
            )
            return False
        call = partial(service, self.project_dir, deepcopy(preview))
        self._project_change_preview = None
        self._start_project_change_job(operation, "apply", call, show_dialog)
        return True

    def _start_project_change_job(
        self, operation: str, phase: str, call: Any, show_dialog: bool
    ) -> None:
        self._project_change_busy = True
        self._project_change_operation = operation
        self._project_change_phase = phase
        self._project_change_show_dialog = show_dialog
        self._project_change_progress = ProjectChangeProgress(
            f"SciPlot project — {phase.replace('_', ' ')}", self.window
        )
        self._project_change_progress.show()
        self._update_controls(self.status_snapshot)
        worker = ProjectChangeWorker(call, self)
        self._project_change_job = worker
        worker.finished.connect(self._finish_project_change_job)
        worker.start()

    def _finish_project_change_job(self) -> None:
        worker = self._project_change_job
        result = worker.result
        worker.deleteLater()
        self._project_change_job = None
        phase = self._project_change_phase
        show_dialog = self._project_change_show_dialog
        payload = result.get("payload", {})
        applied = phase == "apply" and payload.get("status") in {"recovered", "updated"}
        reload_error = None
        if applied:
            try:
                self._reopen_project_change_document(payload)
            except Exception as exc:
                # A successful filesystem transaction must never leave a stale
                # in-memory revision able to save over the adopted document.
                self.window.filename = ""
                self.document.clearHistory()
                self.document.wipe()
                self.window.updateTitlebar()
                reload_error = f"Project files were updated, but Veusz could not reopen them: {exc}. Reopen {self.document_path}. The old window has been cleared to prevent overwriting the update."
        self._project_change_progress.finish()
        self._project_change_progress.deleteLater()
        self._project_change_busy = False
        if not result.get("ok") or reload_error:
            message = reload_error or str(
                result.get("message") or "Project change failed."
            )
            self._project_change_message(message, show_dialog=show_dialog)
            self.projectChangeFinished.emit(
                {
                    "status": "reopen_failed" if applied else "failed",
                    "message": message,
                    "result": payload,
                }
            )
        elif phase == "preview":
            self._project_change_preview = deepcopy(payload)
            self.projectChangePreviewed.emit(payload)
            if show_dialog and confirm_project_change(
                self.window, self._project_change_operation, payload
            ):
                self.apply_project_change_preview(show_dialog=True)
        elif applied:
            self.refresh()
            self._refresh_series_revision()
            self._project_change_message(
                "Project revision adopted and reopened. Use Save && Export to refresh the visible delivery.",
                show_dialog=False,
            )
            self.projectChangeFinished.emit(payload)
        else:
            self._project_change_message(
                str(
                    payload.get("message")
                    or payload.get("reason")
                    or "Project change was blocked."
                ),
                show_dialog=show_dialog,
            )
            self.projectChangeFinished.emit(payload)
        self._update_controls(self.status_snapshot)

    def _reopen_project_change_document(self, payload: dict[str, Any]) -> None:
        target = Path(payload["document"]).expanduser().resolve()
        if target != self.document_path or not target.is_file():
            raise RuntimeError("The result did not identify the bound managed document")
        if not self.window.loadDocument(str(target)):
            raise RuntimeError("The native Veusz loader rejected the adopted document")
        self.window.filename = str(target)
        self.window.updateTitlebar()
        self.window.documentOpened.emit()
        self.status_snapshot = {}

    def _project_change_message(self, message: str, *, show_dialog: bool) -> None:
        self.status_view.appendPlainText("\nProject revision: " + message)
        if show_dialog:
            QtWidgets.QMessageBox.warning(
                self.window, "SciPlot project revision", message
            )
