"""Reject, fail, cancel, and shut down assistant requests safely."""

from __future__ import annotations

from typing import Any
from PyQt6 import QtWidgets
from sciplot_core.assistant_operations import VeuszSettingOperationBatch
from sciplot_core.assistant_provider import (
    AssistantResponse,
)


class RejectionMixin:
    def reject_pending(
        self,
        *,
        silent: bool = False,
        reason_code: str = "user_rejected",
    ) -> None:
        had_proposal = self._pending_batch is not None
        request = self._pending_request
        response = self._pending_response
        batch = self._pending_batch
        history_failed = False
        if request is not None and had_proposal:
            try:
                self._record_history(
                    status="rejected",
                    request=request,
                    response=response,
                    batch=batch,
                    reason_code=reason_code,
                )
            except Exception:
                history_failed = True
        self._clear_pending()
        if had_proposal and not silent:
            message = "Proposal rejected; the Veusz document was unchanged."
            if history_failed:
                message += " Local Assistant history could not be finalized."
            self.status_label.setText(message)

    def _reject_stale(
        self,
        message: str,
        *,
        reason_code: str,
        response: AssistantResponse | None = None,
        batch: VeuszSettingOperationBatch | None = None,
    ) -> None:
        request = self._pending_request
        history_failed = False
        if request is not None:
            try:
                self._record_history(
                    status="rejected",
                    request=request,
                    response=response or self._pending_response,
                    batch=batch or self._pending_batch,
                    reason_code=reason_code,
                )
            except Exception:
                history_failed = True
        self._clear_pending()
        if history_failed:
            message = f"{message} Local Assistant history could not be finalized."
        self.status_label.setText(message)
        self.proposal_view.setPlainText(message)
        self.requestRejected.emit(message)

    def _provider_failed(self, payload: Any) -> None:
        if self._document_context_blocker() is not None:
            self.handle_document_context_changed()
            return
        error = payload.get("error") if isinstance(payload, dict) else str(payload)
        request = self._pending_request
        history_failed = False
        if request is not None:
            try:
                self._record_history(
                    status="failed",
                    request=request,
                    reason_code="provider_failed",
                )
            except Exception:
                history_failed = True
        self._clear_pending()
        message = f"Assistant request failed: {error}"
        if history_failed:
            message += " Local Assistant history could not be finalized."
        self.status_label.setText(message)
        self.proposal_view.setPlainText(message)
        self.requestRejected.emit(message)

    def _runner_active_changed(self, active: bool) -> None:
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self.status_label.setText(context_blocker)
            self.proposal_view.setPlainText(context_blocker)
            self._refresh_ask_button()
            return
        self._refresh_ask_button()
        descriptor = self.runner.descriptor
        self.cancel_button.setEnabled(
            bool(active and descriptor is not None and descriptor.supports_cancellation)
        )

    def _show_error(self, message: str) -> None:
        self.status_label.setText(message)
        QtWidgets.QMessageBox.warning(self.window, "SciPlot AI", message)

    def _shutdown(self) -> None:
        was_active = self.runner.active
        self.runner.shutdown(wait_ms=3000)
        request = self._pending_request
        if request is not None:
            try:
                self._record_history(
                    status=("cancelled" if was_active else "rejected"),
                    request=request,
                    response=self._pending_response,
                    batch=self._pending_batch,
                    reason_code="window_closed",
                )
            except Exception:
                pass
            self._clear_pending()
