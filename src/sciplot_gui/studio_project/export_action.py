"""Save, export, publish, and report the exact-current document."""

from __future__ import annotations

from typing import Any
from PyQt6 import QtWidgets
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_gui.studio_project_status import (
    _finalize_status,
)


class ExportActionMixin:
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
                save_receipt = self.save_or_commit_current_document(self.document_path)
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
                blocker = (
                    figure_blocker
                    or self._assistant_export_blocker()
                    or self._series_revision_export_blocker()
                )
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
                post_blocker = (
                    post_figure_blocker
                    or self._assistant_export_blocker()
                    or self._series_revision_export_blocker()
                )
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
