"""Submit requests and translate provider progress and typed responses."""

from __future__ import annotations

import json
from typing import Any
from sciplot_core.assistant_operations import VeuszSettingOperationBatch
from sciplot_core.assistant_provider import (
    AssistantRequest,
    AssistantResponse,
    ProviderFacts,
)


def provider_facts_text(facts: ProviderFacts | None) -> str:
    if facts is None:
        return ""
    lines = [f"Provider usage status: {facts.usage_status}"]
    if facts.response_id is not None:
        lines.append(f"Provider response: {facts.response_id}")
    if facts.model is not None:
        lines.append(f"Provider-reported model: {facts.model}")
    if facts.terminal_status is not None:
        lines.append(f"Provider terminal status: {facts.terminal_status}")
    usage = facts.usage
    lines.append(
        "Provider-reported counters: " + json.dumps(usage, sort_keys=True)
        if usage is not None
        else "Usage amounts are unknown; they are not recorded as zero."
    )
    return "\n".join(lines)


class RequestFlowMixin:
    def _ask_from_ui(self) -> None:
        try:
            self.submit_intent(self.intent_edit.toPlainText())
        except Exception as exc:
            self._show_error(str(exc))

    def submit_intent(self, intent: str) -> AssistantRequest:
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self.handle_document_context_changed()
            raise RuntimeError(context_blocker)
        if self.runner.active:
            raise RuntimeError("An Assistant request is already running.")
        self.reject_pending(
            silent=True,
            reason_code="superseded_by_new_request",
        )
        request = self.build_request(intent)
        capabilities = request.context["editing_capabilities"]["allowed_operations"]
        self._pending_request = request
        self._pending_capabilities = {
            (str(item["target_id"]), str(item["setting_path"])): dict(item)
            for item in capabilities
        }
        if request.disclosure == "visual":
            self.proposal_view.setPlainText(
                "Sending selected-object properties and the current page image…\n"
                f"PNG SHA-256: {request.visual_preview['sha256']}"
            )
            self.status_label.setText(
                "AI is inspecting the current page for a bounded selected-object proposal."
            )
        else:
            self.proposal_view.setPlainText(
                "Sending selected-object properties only. No image is sent.\n"
                f"Local snapshot SHA-256: {request.visual_preview['sha256']}"
            )
            self.status_label.setText("AI is inspecting selected-object properties only.")
        try:
            self._record_history(status="submitted", request=request)
        except Exception:
            self._clear_pending()
            raise RuntimeError(
                "The Assistant request was not sent because its local history "
                "could not be written."
            ) from None
        try:
            self.runner.submit(request)
        except Exception:
            try:
                self._record_history(
                    status="failed",
                    request=request,
                    reason_code="request_submit_failed",
                )
            except Exception:
                pass
            finally:
                self._clear_pending()
            raise
        self.requestSubmitted.emit(request)
        return request

    def _cancel_request(self) -> None:
        try:
            self.runner.cancel()
            self.status_label.setText("Stopping the Assistant request…")
        except Exception as exc:
            self._show_error(str(exc))

    def _provider_progress(self, event: Any) -> None:
        if self._document_context_blocker() is not None:
            return
        self.status_label.setText(str(getattr(event, "message", "AI is working…")))

    def _provider_response(self, response: AssistantResponse) -> None:
        request = self._request_for_provider_result(response.request_id)
        if request is None:
            self._unbound_provider_result()
            return
        if getattr(self, "_window_closing", False):
            try:
                self._record_history(
                    status="cancelled", request=request, response=response,
                    reason_code="window_closed",
                )
            except Exception:
                self.requestRejected.emit("Local Assistant history could not be finalized.")
            finally:
                self._clear_pending()
            return
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self._reject_stale(
                context_blocker,
                reason_code="document_context_changed",
                response=response,
                request=request,
            )
            return
        if self._pending_request is None:
            self._reject_stale(
                "Assistant response has no active request.",
                reason_code="no_active_request",
                response=response,
                request=request,
            )
            return
        if not self._request_targets_current_selection(request):
            self._reject_stale(
                "The selected Veusz object changed while AI was inspecting it. "
                "The old-object proposal was discarded; ask again for the "
                "current selection.",
                reason_code="selected_object_changed",
                response=response,
            )
            return
        if int(self.document.changeset) != request.base_revision:
            self._reject_stale(
                "The Veusz document changed while AI was inspecting it. "
                "The stale proposal was discarded; ask again to use the "
                "current rendered page.",
                reason_code="document_revision_changed",
                response=response,
            )
            return
        self._pending_response = response
        if response.status != "proposal":
            self._pending_batch = None
            self.apply_button.setEnabled(False)
            self.reject_button.setEnabled(False)
            self.status_label.setText(response.understanding)
            self.proposal_view.setPlainText(self._response_text(response, batch=None))
            try:
                self._record_history(
                    status=self._terminal_history_status(response.status),
                    request=request,
                    response=response,
                )
            except Exception:
                self.status_label.setText(
                    f"{response.understanding} Local Assistant history could "
                    "not be finalized."
                )
            finally:
                self._clear_pending()
            return
        if response.proposal_kind != "veusz_setting_operation_batch":
            self._reject_stale(
                "The Assistant returned an unsupported proposal.",
                reason_code="unsupported_proposal_kind",
                response=response,
            )
            return
        try:
            batch = VeuszSettingOperationBatch.from_dict(dict(response.proposal or {}))
            self._prepare_native_operations(batch, request=request)
        except Exception as exc:
            self._reject_stale(
                f"Unsafe Assistant proposal rejected: {exc}",
                reason_code="typed_validation_failed",
                response=response,
            )
            return
        self._pending_batch = batch
        self.proposal_view.setPlainText(self._response_text(response, batch=batch))
        self.apply_button.setEnabled(True)
        self.reject_button.setEnabled(True)
        self.status_label.setText("A bounded proposal is ready.")
        try:
            self._record_history(
                status="proposal_ready",
                request=request,
                response=response,
                batch=batch,
            )
        except Exception:
            message = (
                "The bounded proposal was not retained because its local "
                "Assistant history could not be written."
            )
            self._clear_pending()
            self.status_label.setText(message)
            self.proposal_view.setPlainText(message)
            self.requestRejected.emit(message)
            return
        self.proposalReady.emit(batch)
        if self.auto_apply.isChecked():
            self.accept_pending()

    def _response_text(
        self,
        response: AssistantResponse,
        *,
        batch: VeuszSettingOperationBatch | None,
    ) -> str:
        lines = [response.understanding]
        if response.warnings:
            lines.extend(
                ["", "Warnings:", *[f"• {item}" for item in response.warnings]]
            )
        if batch is not None:
            lines.extend(["", "Proposed changes:"])
            for operation in batch.operations:
                capability = self._pending_capabilities.get(
                    (
                        operation.target_id,
                        str(operation.arguments.get("setting_path") or ""),
                    ),
                    {},
                )
                label = capability.get("label") or operation.arguments.get(
                    "setting_path"
                )
                lines.append(
                    f"• {label}: {operation.arguments.get('expected_value')!r} "
                    f"→ {operation.arguments.get('value')!r}"
                )
        facts_text = provider_facts_text(response.provider_facts)
        if facts_text:
            lines.extend(["", facts_text])
        return "\n".join(lines)
