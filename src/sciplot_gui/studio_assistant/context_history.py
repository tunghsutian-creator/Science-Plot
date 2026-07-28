"""Track document context, selection state, and durable proposal history."""

from __future__ import annotations

from typing import Any
from sciplot_core.assistant_operations import VeuszSettingOperationBatch
from sciplot_core.assistant_provider import (
    AssistantRequest,
    AssistantResponse,
)
from sciplot_gui.studio_assistant_history import (
    append_assistant_history_event,
    build_assistant_history_event,
)
from sciplot_gui.window_context import resolved_window_document_path


class ContextHistoryMixin:
    @property
    def selected_widget(self) -> Any | None:
        return self._selected_widget

    @property
    def pending_batch(self) -> VeuszSettingOperationBatch | None:
        return self._pending_batch

    def _document_context_blocker(self) -> str | None:
        current = resolved_window_document_path(self.window)
        if current == self.document_path:
            return None
        current_label = str(current) if current is not None else "an unsaved document"
        return (
            "This Veusz window now points to "
            f"{current_label}, but SciPlot AI remains bound to "
            f"{self.document_path}. Close this window and reopen the new VSZ "
            "before asking AI so the exact-current document context can be "
            "rebuilt safely."
        )

    def handle_document_context_changed(self) -> str | None:
        message = self._document_context_blocker()
        if message is None:
            self._refresh_ask_button()
            return None
        if self.runner.active:
            try:
                self.runner.cancel()
            except Exception:
                pass
        if self._pending_request is not None:
            self._reject_stale(
                message,
                reason_code="document_context_changed",
            )
        else:
            self._clear_pending()
            self.status_label.setText(message)
            self.proposal_view.setPlainText(message)
            self.requestRejected.emit(message)
        self._refresh_ask_button()
        return message

    def _record_history(
        self,
        *,
        status: str,
        request: AssistantRequest,
        response: AssistantResponse | None = None,
        batch: VeuszSettingOperationBatch | None = None,
        operations: list[Any] | tuple[Any, ...] | None = None,
        reason_code: str | None = None,
        applied_revision: int | None = None,
        after_page_render_sha256: str | None = None,
        render_changed: bool | None = None,
        native_undo_label: str | None = None,
    ) -> dict[str, Any]:
        event = build_assistant_history_event(
            status=status,
            request=request,
            descriptor=self.runner.descriptor,
            response=response,
            batch=batch,
            operations=operations,
            reason_code=reason_code,
            applied_revision=applied_revision,
            after_page_render_sha256=after_page_render_sha256,
            render_changed=render_changed,
            native_undo_label=native_undo_label,
        )
        append_assistant_history_event(self.history_path, event)
        self.historyRecorded.emit(event)
        return event

    def _clear_pending(self) -> None:
        """Release request-owned image bytes after a terminal outcome."""

        self._pending_response = None
        self._pending_batch = None
        self._pending_request = None
        self._pending_capabilities = {}
        try:
            self.apply_button.setEnabled(False)
            self.reject_button.setEnabled(False)
        except RuntimeError:
            # Window destruction can delete child widgets before this bridge's
            # shutdown slot releases request-owned image bytes.
            pass
        self._refresh_ask_button()

    @staticmethod
    def _terminal_history_status(response_status: str) -> str:
        if response_status in {
            "cancelled",
            "needs_human_confirmation",
            "needs_rule_repair",
        }:
            return response_status
        return "failed"
