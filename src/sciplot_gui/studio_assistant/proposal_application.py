"""Validate, preview, and apply accepted native Veusz setting operations."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.assistant_operations import VeuszSettingOperationBatch
from sciplot_core.assistant_provider import (
    AssistantRequest,
)


class ProposalApplicationMixin:
    def _prepare_native_operations(
        self,
        batch: VeuszSettingOperationBatch,
        *,
        request: AssistantRequest,
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        if batch.base_revision != request.base_revision:
            raise ValueError("proposal revision does not match the request")
        if int(self.document.changeset) != request.base_revision:
            raise ValueError("the Veusz document has changed")
        from veusz.document.operations import OperationSettingSet

        native: list[Any] = []
        prepared: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for operation in batch.operations:
            if operation.operation_type != "set_setting":
                raise ValueError(f"unsupported operation {operation.operation_type!r}")
            setting_path = str(operation.arguments["setting_path"])
            key = (operation.target_id, setting_path)
            capability = self._pending_capabilities.get(key)
            if capability is None:
                raise ValueError("proposal is outside the advertised setting catalog")
            if setting_path in seen_paths:
                raise ValueError("proposal contains the same setting twice")
            seen_paths.add(setting_path)
            if "expected_value" not in operation.arguments:
                raise ValueError("proposal is missing expected_value")
            setting = self.document.resolveSettingPath(None, setting_path)
            current = json_safe(setting.get())
            expected = json_safe(operation.arguments["expected_value"])
            if current != expected or current != capability["current_value"]:
                raise ValueError(f"{setting_path} no longer has its expected value")
            normalized = setting.normalize(operation.arguments["value"])
            native.append(OperationSettingSet(setting_path, normalized))
            prepared.append(
                {
                    "operation_id": operation.operation_id,
                    "operation_type": operation.operation_type,
                    "target_id": operation.target_id,
                    "setting_path": setting_path,
                    "old_value": current,
                    "new_value": json_safe(normalized),
                }
            )
        if not native:
            raise ValueError("proposal contains no applicable edits")
        return native, prepared

    def accept_pending(self) -> dict[str, Any] | None:
        context_blocker = self._document_context_blocker()
        if context_blocker is not None:
            self.handle_document_context_changed()
            return None
        batch = self._pending_batch
        request = self._pending_request
        if batch is None or request is None:
            return None
        if not self._request_targets_current_selection(request):
            self._reject_stale(
                "The selected Veusz object changed. The old-object proposal "
                "was discarded; ask again for the current selection.",
                reason_code="selected_object_changed",
                batch=batch,
            )
            return None
        try:
            native, prepared = self._prepare_native_operations(
                batch,
                request=request,
            )
        except Exception as exc:
            reason_code = (
                "document_revision_changed"
                if int(self.document.changeset) != request.base_revision
                else "typed_validation_failed"
            )
            self._reject_stale(
                f"Assistant proposal was not applied: {exc}",
                reason_code=reason_code,
                response=self._pending_response,
                batch=batch,
            )
            return None

        description = f"SciPlot AI · {batch.batch_id[:8]}"
        try:
            self._record_history(
                status="apply_started",
                request=request,
                response=self._pending_response,
                batch=batch,
                operations=prepared,
                native_undo_label=description,
            )
        except Exception:
            self.status_label.setText(
                "The proposal was not applied because its durable local "
                "Assistant history could not be written."
            )
            return None

        from veusz.document.operations import OperationMultiple

        before_render = request.visual_preview["sha256"]
        try:
            self.document.applyOperation(OperationMultiple(native, descr=description))
        except Exception as exc:
            try:
                self._record_history(
                    status="failed",
                    request=request,
                    response=self._pending_response,
                    batch=batch,
                    operations=prepared,
                    reason_code="apply_failed",
                    native_undo_label=description,
                )
            except Exception:
                pass
            self._clear_pending()
            message = f"Assistant proposal could not be applied: {exc}"
            self.status_label.setText(message)
            self.proposal_view.setPlainText(message)
            self.requestRejected.emit(message)
            return None

        applied_revision = int(self.document.changeset)
        after_render: str | None = None
        verification_error = False
        try:
            after_render = self.current_render_sha256()
        except Exception:
            verification_error = True

        terminal_status = "applied_unverified" if verification_error else "applied"
        render_changed = (
            before_render != after_render if after_render is not None else None
        )
        history_finalized = True
        try:
            self._record_history(
                status=terminal_status,
                request=request,
                response=self._pending_response,
                batch=batch,
                operations=prepared,
                reason_code=(
                    "after_render_verification_failed" if verification_error else None
                ),
                applied_revision=applied_revision,
                after_page_render_sha256=after_render,
                render_changed=render_changed,
                native_undo_label=description,
            )
        except Exception:
            history_finalized = False

        result = {
            "batch_id": batch.batch_id,
            "base_revision": batch.base_revision,
            "applied_revision": applied_revision,
            "before_render_sha256": before_render,
            "after_render_sha256": after_render,
            "render_changed": render_changed,
            "operations": prepared,
            "native_undo_description": description,
            "verification_status": terminal_status,
            "history_finalized": history_finalized,
        }
        current = self.proposal_view.toPlainText()
        self._clear_pending()
        if verification_error:
            self.status_label.setText(
                "Applied as one native Veusz Undo step, but the exact-current "
                "after-render hash could not be verified. Use Edit → Undo or "
                "inspect the current page before saving."
            )
            self.proposal_view.setPlainText(
                f"{current}\n\nApplied as one native Veusz Undo step; "
                "after-render verification is incomplete."
            )
        elif not history_finalized:
            self.status_label.setText(
                "Applied as one native Veusz Undo step, but the terminal "
                "Assistant history row could not be finalized."
            )
            self.proposal_view.setPlainText(
                f"{current}\n\nApplied as one native Veusz Undo step; "
                "history finalization is incomplete."
            )
        else:
            self.status_label.setText(
                "Applied to the live Veusz document. Use Edit → Undo to revert; "
                "save when satisfied."
            )
            self.proposal_view.setPlainText(
                f"{current}\n\nApplied as one native Veusz Undo step."
            )
        self.proposalApplied.emit(result)
        return result
