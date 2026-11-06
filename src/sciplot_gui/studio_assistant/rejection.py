"""Reject, fail, cancel, and shut down assistant requests safely."""

from __future__ import annotations

from typing import Any, cast
from PyQt6 import QtWidgets
from sciplot_core.assistant_operations import VeuszSettingOperationBatch
from sciplot_core.assistant_provider import (
    AssistantRequest,
    AssistantResponse,
    ProviderFacts,
)
from sciplot_gui.studio_assistant.request_flow import provider_facts_text


class RejectionMixin:
    def _unbound_provider_result(self) -> None:
        message = (
            "Assistant result ignored: no matching in-flight request. "
            "Provider usage was not attached to another request."
        )
        self.status_label.setText(message)
        self.proposal_view.setPlainText(message)
        self.requestRejected.emit(message)

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
        request: AssistantRequest | None = None,
    ) -> None:
        request = request or self._pending_request
        response = response or self._pending_response
        history_failed = False
        if request is not None:
            try:
                self._record_history(
                    status="rejected",
                    request=request,
                    response=response,
                    batch=batch or self._pending_batch,
                    reason_code=reason_code,
                )
            except Exception:
                history_failed = True
        self._clear_pending()
        if history_failed:
            message = f"{message} Local Assistant history could not be finalized."
        self.status_label.setText(message)
        facts_text = provider_facts_text(response.provider_facts) if response is not None else ""
        self.proposal_view.setPlainText(
            f"{message}\n\n{facts_text}" if facts_text else message
        )
        self.requestRejected.emit(message)

    def _provider_failed(self, payload: Any) -> None:
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        request = self._request_for_provider_result(request_id)
        if request is None:
            self._unbound_provider_result()
            return
        error = payload.get("error") if isinstance(payload, dict) else str(payload)
        facts = cast(ProviderFacts | None, payload.get("provider_facts"))
        history_failed = False
        if request is not None:
            try:
                self._record_history(
                    status="failed",
                    request=request,
                    provider_facts=facts,
                    reason_code="provider_failed",
                )
            except Exception:
                history_failed = True
        self._clear_pending()
        if getattr(self, "_window_closing", False):
            return
        message = f"Assistant request failed: {error}"
        if history_failed:
            message += " Local Assistant history could not be finalized."
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            message = f"{context_blocker} {message}"
        self.status_label.setText(message)
        facts_text = provider_facts_text(facts)
        self.proposal_view.setPlainText(
            f"{message}\n\n{facts_text}" if facts_text else message
        )
        self.requestRejected.emit(message)

    def _runner_active_changed(self, active: bool) -> None:
        if getattr(self, "_window_closing", False):
            return
        self.disclosure_combo.setEnabled(not active)
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
        self._window_closing = True
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
