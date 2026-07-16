from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import uuid4

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.model import (
    CanvasSession,
    CanvasTransaction,
)
from sciplot_core.canvas.operations import CanvasOperationBatch
from sciplot_core.canvas.provider import (
    ASSISTANT_MAX_INTENT_LENGTH,
    AssistantProgressEvent,
    AssistantProviderDescriptor,
    AssistantRequest,
    AssistantRequestRecord,
    AssistantResponse,
)
from sciplot_gui.document_controller import DocumentController


class AssistantTransactionCoordinator:
    """Provider-neutral lifecycle for visible, reversible assistant edits."""

    def __init__(self, controller: DocumentController) -> None:
        self.controller = controller
        self.reconcile_on_open()

    @property
    def transaction(self) -> CanvasTransaction | None:
        return self.controller.session.active_transaction

    @property
    def active(self) -> bool:
        return self.transaction is not None

    @property
    def can_undo_batch(self) -> bool:
        transaction = self.transaction
        return bool(
            transaction is not None
            and transaction.status == "active"
            and transaction.pending_batch is None
            and transaction.active_batch_ids
            and self.controller.adapter.can_undo
        )

    @property
    def request_record(self) -> AssistantRequestRecord | None:
        transaction = self.transaction
        return transaction.parsed_request_record if transaction is not None else None

    def _require_transaction(self) -> CanvasTransaction:
        transaction = self.transaction
        if transaction is None:
            raise RuntimeError("No assistant transaction is active.")
        return transaction

    def _restore_session(self, payload: dict[str, Any]) -> None:
        self.controller.session = CanvasSession.from_dict(payload)
        self.controller.inventory = self.controller.adapter.bind_object_registry(
            self.controller.session
        )
        self.controller.persist()

    def _record_with_session_rollback(
        self,
        session_before: dict[str, Any],
        entry: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self.controller.record_journal_entry(entry)
        except Exception:
            self._restore_session(session_before)
            raise

    def context_summary(self) -> dict[str, Any]:
        """Return provider-safe structured context without raw dataset arrays."""

        session = self.controller.session
        selected = self.controller.selected_object
        inventory_counts = Counter(
            str(item.get("object_type") or "unknown")
            for item in self.controller.inventory
        )
        active_reviews = self.controller.active_review_annotations()
        selection = session.selection.to_dict()
        structural = (
            session.structural_qa_summary
            if isinstance(session.structural_qa_summary, dict)
            else {}
        )
        structural_summary = (
            structural.get("summary")
            if isinstance(structural.get("summary"), dict)
            else {}
        )
        artifact = session.qa_summary if isinstance(session.qa_summary, dict) else {}
        return {
            "kind": "sciplot_canvas_assistant_context",
            "version": 2,
            "project_id": session.project_id,
            "document_id": session.document_id,
            "revision": session.revision,
            "state": session.state,
            "page": session.current_page,
            "selection": selection,
            "selected_object": (
                {
                    "object_id": selected.get("object_id"),
                    "object_type": selected.get("object_type"),
                    "display_name": (
                        selected.get("display_name")
                        or selected.get("path")
                        or "Unnamed"
                    ),
                }
                if selected is not None
                else None
            ),
            "document_inventory": {
                "object_count": len(self.controller.inventory),
                "object_types": dict(sorted(inventory_counts.items())),
            },
            "review": {
                "active_count": len(active_reviews),
                "annotations": [
                    {
                        "annotation_id": annotation.annotation_id,
                        "shape": annotation.shape,
                        "coordinate_space": annotation.coordinate_space,
                        "target_object_id": annotation.target_object_id,
                        "text": annotation.text,
                    }
                    for annotation in active_reviews
                ],
            },
            "qa": {
                "structural_status": structural.get("status") or "not_run",
                "structural_failed_ids": list(
                    structural_summary.get("failed_ids") or []
                ),
                "structural_warning_ids": list(
                    structural_summary.get("warning_ids") or []
                ),
                "ready_for_artifact_qa": bool(
                    structural.get("ready_for_artifact_qa", False)
                ),
                "artifact_status": artifact.get("status") or "not_run",
                "ready_to_use": artifact.get("ready_to_use"),
            },
            "raw_dataset_arrays_included": False,
            "explicit_selected_point_included": selection.get("data_point")
            is not None,
        }

    def begin(
        self,
        *,
        provider: str,
        rationale: str,
    ) -> dict[str, Any]:
        if self.transaction is not None:
            raise RuntimeError("Resolve the current assistant transaction first.")
        provider_text = str(provider or "").strip()
        rationale_text = str(rationale or "").strip()
        if not provider_text:
            raise ValueError("Assistant transaction provider is required.")
        if not rationale_text:
            raise ValueError("Assistant transaction rationale is required.")
        transaction_id = str(uuid4())
        session_before = self.controller.session.to_dict()
        baseline = self.controller.create_transaction_baseline(transaction_id)
        session = self.controller.session
        transaction = CanvasTransaction(
            transaction_id=transaction_id,
            provider=provider_text,
            base_revision=session.revision,
            status="active",
            snapshot_path=str(baseline["snapshot_path"]),
            snapshot_sha256=str(baseline["snapshot_sha256"]),
            review_snapshot_path=str(baseline["review_snapshot_path"]),
            review_snapshot_sha256=str(baseline["review_snapshot_sha256"]),
            baseline_render_sha256=str(baseline["baseline_render_sha256"]),
            baseline_saved_revision=session.saved_revision,
            baseline_exported_revision=session.exported_revision,
            baseline_state=session.state,
            baseline_document_sha256=session.document_sha256,
            baseline_qa_summary=dict(session.qa_summary),
            baseline_structural_qa_summary=dict(
                session.structural_qa_summary
            ),
            baseline_page=session.current_page,
            baseline_viewport=session.viewport.to_dict(),
            current_revision=session.revision,
            rationale=rationale_text,
        )
        session.active_transaction = transaction
        session.set_state("ai_proposing")
        try:
            entry = self._record_with_session_rollback(
                session_before,
                {
                    "event": "assistant_transaction_started",
                    "provider": provider_text,
                    "transaction_id": transaction_id,
                    "revision": session.revision,
                    "rationale": rationale_text,
                    "baseline": {
                        **baseline,
                        "saved_revision": session_before["saved_revision"],
                        "exported_revision": session_before[
                            "exported_revision"
                        ],
                        "session_state": session_before["state"],
                        "document_sha256": session_before[
                            "document_sha256"
                        ],
                    },
                    "context": self.context_summary(),
                },
            )
        except Exception:
            for key in ("snapshot_path", "review_snapshot_path"):
                try:
                    self.controller._resolve_transaction_artifact(
                        str(baseline[key]),
                        transaction_id=transaction_id,
                    ).unlink(missing_ok=True)
                except Exception:
                    pass
            raise
        return {
            "transaction": transaction.to_dict(),
            "journal": entry,
            "context": self.context_summary(),
        }

    def start_request(
        self,
        *,
        descriptor: AssistantProviderDescriptor,
        intent: str,
    ) -> AssistantRequest:
        restored_descriptor = AssistantProviderDescriptor.from_dict(
            descriptor.to_dict()
        )
        intent_text = str(intent or "").strip()
        if not intent_text:
            raise ValueError("Describe the figure change before submitting.")
        if len(intent_text) > ASSISTANT_MAX_INTENT_LENGTH:
            raise ValueError(
                f"Assistant requests are limited to {ASSISTANT_MAX_INTENT_LENGTH} "
                "characters."
            )
        if self.transaction is None:
            self.begin(
                provider=restored_descriptor.provider_id,
                rationale=intent_text,
            )
        transaction = self._require_transaction()
        if transaction.provider != restored_descriptor.provider_id:
            raise ValueError(
                "The connected provider does not own the active Assistant turn."
            )
        if transaction.status != "active":
            raise RuntimeError("Resume the Assistant turn before asking again.")
        if transaction.pending_batch is not None:
            raise RuntimeError(
                "Accept or reject the current proposal before asking again."
            )
        if transaction.applying_batch_id is not None:
            raise RuntimeError("Wait for the current proposal to finish applying.")
        existing = transaction.parsed_request_record
        if existing is not None and existing.status not in {
            "applied",
            "rejected",
            "cancelled",
            "failed",
            "interrupted",
        }:
            raise RuntimeError("Resolve the current Assistant request first.")
        context = self.context_summary()
        request = AssistantRequest(
            transaction_id=transaction.transaction_id,
            provider_id=restored_descriptor.provider_id,
            intent=intent_text,
            base_revision=int(transaction.current_revision),
            context=context,
            allowed_proposal_kinds=restored_descriptor.proposal_kinds,
        )
        record = AssistantRequestRecord(request=request.to_dict())
        session_before = self.controller.session.to_dict()
        try:
            transaction.set_request_record(record)
            self.controller.session.set_state("ai_proposing")
            self.controller.record_journal_entry(
                {
                    "event": "assistant_request_submitted",
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "request_id": request.request_id,
                    "revision": self.controller.session.revision,
                    "descriptor": restored_descriptor.to_dict(),
                    "request": request.to_dict(),
                    "publication_document_changed": False,
                }
            )
        except Exception:
            self._restore_session(session_before)
            raise
        return request

    def record_progress(
        self,
        event: AssistantProgressEvent,
    ) -> dict[str, Any]:
        restored = AssistantProgressEvent.from_dict(event.to_dict())
        transaction = self._require_transaction()
        record = transaction.parsed_request_record
        if record is None:
            raise RuntimeError("No Assistant request is active.")
        session_before = self.controller.session.to_dict()
        try:
            record.append_event(restored)
            transaction.set_request_record(record)
            self.controller.session.set_state("ai_proposing")
            return self.controller.record_journal_entry(
                {
                    "event": "assistant_request_progress",
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "request_id": restored.request_id,
                    "revision": self.controller.session.revision,
                    "progress": restored.to_dict(),
                    "publication_document_changed": False,
                }
            )
        except Exception:
            self._restore_session(session_before)
            raise

    def request_cancel(self) -> dict[str, Any]:
        transaction = self._require_transaction()
        record = transaction.parsed_request_record
        if record is None:
            raise RuntimeError("No Assistant request is active.")
        session_before = self.controller.session.to_dict()
        try:
            record.request_cancel()
            transaction.set_request_record(record)
            return self.controller.record_journal_entry(
                {
                    "event": "assistant_request_cancel_requested",
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "request_id": record.parsed_request.request_id,
                    "revision": self.controller.session.revision,
                    "publication_document_changed": False,
                }
            )
        except Exception:
            self._restore_session(session_before)
            raise

    def complete_request(self, response: AssistantResponse) -> dict[str, Any]:
        restored = AssistantResponse.from_dict(response.to_dict())
        transaction = self._require_transaction()
        record = transaction.parsed_request_record
        if record is None:
            raise RuntimeError("No Assistant request is active.")
        request = record.parsed_request
        restored.validate_for_request(request)
        late_response_discarded = False
        if record.status == "cancel_requested" and restored.status != "cancelled":
            late_response_discarded = True
            restored = AssistantResponse(
                request_id=request.request_id,
                transaction_id=request.transaction_id,
                provider_id=request.provider_id,
                request_sha256=request.payload_sha256,
                status="cancelled",
                understanding=(
                    "Stopped before a provider proposal could be accepted."
                ),
                warnings=("A late provider response was discarded after cancellation.",),
            )
        session_before = self.controller.session.to_dict()
        try:
            preview: dict[str, Any] | None = None
            if restored.status == "proposal" and restored.proposal_kind == (
                "canvas_operation_batch"
            ):
                batch = CanvasOperationBatch.from_dict(
                    dict(restored.proposal or {})
                )
                preview = self.controller.preview_batch(batch)
                record.complete(restored)
                transaction.set_request_record(record)
                transaction.set_pending_batch(batch, preview)
                self.controller.session.set_state("ai_proposing")
                journal = self.controller.record_journal_entry(
                    {
                        "event": "assistant_batch_proposed",
                        "provider": transaction.provider,
                        "transaction_id": transaction.transaction_id,
                        "request_id": request.request_id,
                        "revision": self.controller.session.revision,
                        "request_sha256": record.request_sha256,
                        "response": restored.to_dict(),
                        "batch": batch.to_dict(),
                        "preview": preview,
                        "publication_document_changed": False,
                    }
                )
                return {
                    "response": restored.to_dict(),
                    "preview": preview,
                    "journal": journal,
                    "late_response_discarded": False,
                }

            record.complete(restored)
            transaction.set_request_record(record)
            if transaction.status == "active":
                transaction.set_paused(True)
            if restored.status == "needs_human_confirmation" or (
                restored.status == "proposal"
                and restored.proposal_kind == "data_mapping_proposal"
            ):
                self.controller.session.set_state("needs_human_confirmation")
            elif restored.status == "needs_rule_repair":
                self.controller.session.set_state("needs_rule_repair")
            else:
                self.controller.session.set_state("ai_proposing")
            event_name = (
                "assistant_response_discarded_after_cancel"
                if late_response_discarded
                else (
                    "assistant_data_mapping_proposed"
                    if restored.status == "proposal"
                    else "assistant_response_received"
                )
            )
            journal = self.controller.record_journal_entry(
                {
                    "event": event_name,
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "request_id": request.request_id,
                    "revision": self.controller.session.revision,
                    "request_sha256": record.request_sha256,
                    "response": restored.to_dict(),
                    "publication_document_changed": False,
                }
            )
            return {
                "response": restored.to_dict(),
                "preview": None,
                "journal": journal,
                "late_response_discarded": late_response_discarded,
            }
        except Exception:
            self._restore_session(session_before)
            raise

    def fail_request(self, error: str) -> dict[str, Any]:
        transaction = self._require_transaction()
        record = transaction.parsed_request_record
        if record is None:
            raise RuntimeError("No Assistant request is active.")
        session_before = self.controller.session.to_dict()
        try:
            record.fail(str(error or "Assistant provider failed."))
            transaction.set_request_record(record)
            if transaction.status == "active":
                transaction.set_paused(True)
            self.controller.session.set_state("needs_human_confirmation")
            return self.controller.record_journal_entry(
                {
                    "event": "assistant_request_failed",
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "request_id": record.parsed_request.request_id,
                    "revision": self.controller.session.revision,
                    "error": record.error,
                    "publication_document_changed": False,
                }
            )
        except Exception:
            self._restore_session(session_before)
            raise

    def propose(self, batch: CanvasOperationBatch) -> dict[str, Any]:
        transaction = self._require_transaction()
        if transaction.status != "active":
            raise RuntimeError("Resume the assistant transaction before proposing.")
        if transaction.current_revision != self.controller.session.revision:
            self._mark_conflict(
                "The document revision changed before proposal validation."
            )
            raise ValueError("Assistant proposal is stale.")
        restored = CanvasOperationBatch.from_dict(batch.to_dict())
        preview = self.controller.preview_batch(restored)
        session_before = self.controller.session.to_dict()
        transaction.set_pending_batch(restored, preview)
        self.controller.session.set_state("ai_proposing")
        self._record_with_session_rollback(
            session_before,
            {
                "event": "assistant_batch_proposed",
                "provider": restored.provider,
                "transaction_id": transaction.transaction_id,
                "revision": self.controller.session.revision,
                "batch": restored.to_dict(),
                "preview": preview,
                "publication_document_changed": False,
            },
        )
        return preview

    def pause(self) -> dict[str, Any]:
        transaction = self._require_transaction()
        session_before = self.controller.session.to_dict()
        transaction.set_paused(True)
        self.controller.session.set_state("ai_proposing")
        return self._record_with_session_rollback(
            session_before,
            {
                "event": "assistant_transaction_paused",
                "provider": transaction.provider,
                "transaction_id": transaction.transaction_id,
                "revision": self.controller.session.revision,
            },
        )

    def resume(self) -> dict[str, Any]:
        transaction = self._require_transaction()
        if transaction.current_revision != self.controller.session.revision:
            self._mark_conflict(
                "The document revision changed while the transaction was paused."
            )
            raise ValueError("Assistant transaction is stale after pause.")
        session_before = self.controller.session.to_dict()
        transaction.set_paused(False)
        self.controller.session.set_state("ai_proposing")
        return self._record_with_session_rollback(
            session_before,
            {
                "event": "assistant_transaction_resumed",
                "provider": transaction.provider,
                "transaction_id": transaction.transaction_id,
                "revision": self.controller.session.revision,
            },
        )

    def reject_pending(self, *, reason: str) -> dict[str, Any]:
        transaction = self._require_transaction()
        session_before = self.controller.session.to_dict()
        rejected_batch_id = transaction.reject_pending()
        return self._record_with_session_rollback(
            session_before,
            {
                "event": "assistant_batch_rejected",
                "provider": transaction.provider,
                "transaction_id": transaction.transaction_id,
                "batch_id": rejected_batch_id,
                "revision": self.controller.session.revision,
                "reason": str(reason or "").strip(),
                "publication_document_changed": False,
            },
        )

    def accept_pending(self) -> dict[str, Any]:
        transaction = self._require_transaction()
        if transaction.status != "active":
            raise RuntimeError("Resume the assistant transaction before accepting.")
        if transaction.current_revision != self.controller.session.revision:
            self._mark_conflict(
                "The document revision changed before proposal acceptance."
            )
            raise ValueError("Assistant proposal is stale.")
        if transaction.pending_batch is None:
            raise RuntimeError("The assistant transaction has no pending proposal.")
        batch = CanvasOperationBatch.from_dict(transaction.pending_batch)
        session_before_apply_marker = self.controller.session.to_dict()
        batch_id = transaction.begin_applying()
        self.controller.session.set_state("ai_applying")
        try:
            self._record_with_session_rollback(
                session_before_apply_marker,
                {
                    "event": "assistant_batch_apply_started",
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "batch_id": batch_id,
                    "revision": self.controller.session.revision,
                    "publication_document_changed": False,
                },
            )
            entry = self.controller.apply_batch(
                batch,
                transaction_id=transaction.transaction_id,
            )
        except Exception as exc:
            current = self.controller.session.active_transaction
            if (
                current is not None
                and current.transaction_id == transaction.transaction_id
                and current.applying_batch_id == batch_id
            ):
                current.applying_batch_id = None
                current.status = "paused"
                entry_time = self._now()
                current.updated_at = entry_time
                self.controller.session.set_state("ai_proposing")
                self.controller.record_journal_entry(
                    {
                        "event": "assistant_batch_apply_failed",
                        "provider": current.provider,
                        "transaction_id": current.transaction_id,
                        "batch_id": batch_id,
                        "revision": self.controller.session.revision,
                        "error": f"{type(exc).__name__}: {exc}",
                        "paused_for_review": True,
                        "recorded_at": entry_time,
                    }
                )
            raise
        qa = self.controller.run_structural_qa()
        return {
            "entry": entry,
            "structural_qa": qa,
            "transaction": self._require_transaction().to_dict(),
        }

    @staticmethod
    def _now() -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()

    def undo_last_batch(self) -> dict[str, Any]:
        transaction = self._require_transaction()
        return self.controller.undo(
            provider=transaction.provider,
            transaction_id=transaction.transaction_id,
        )

    def commit(self) -> dict[str, Any]:
        transaction = self._require_transaction()
        if transaction.status not in {"active", "paused"}:
            raise RuntimeError("The assistant transaction cannot be committed.")
        if transaction.pending_batch is not None:
            raise RuntimeError(
                "Accept or reject the pending proposal before committing."
            )
        if transaction.applying_batch_id is not None:
            raise RuntimeError("An applying proposal cannot be committed.")
        if transaction.current_revision != self.controller.session.revision:
            self._mark_conflict(
                "The document revision changed before transaction commit."
            )
            raise ValueError("Assistant transaction is stale at commit.")
        qa = self.controller.run_structural_qa()
        if qa.get("status") == "failed":
            session_before = self.controller.session.to_dict()
            transaction.set_paused(True)
            self.controller.session.set_state("needs_rule_repair")
            self._record_with_session_rollback(
                session_before,
                {
                    "event": "assistant_transaction_commit_blocked",
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "revision": self.controller.session.revision,
                    "structural_qa": json_safe(qa),
                },
            )
            raise RuntimeError(
                "Structural QA failed; repair or roll back the assistant turn."
            )

        session_before = self.controller.session.to_dict()
        terminal = CanvasTransaction.from_dict(transaction.to_dict())
        if terminal is None:
            raise RuntimeError("Could not serialize the assistant transaction.")
        terminal.status = "committed"
        terminal.pending_batch = None
        terminal.pending_preview = None
        terminal.applying_batch_id = None
        terminal.updated_at = self._now()
        render = self.controller.adapter.render_fingerprint()
        unchanged = render == transaction.baseline_render_sha256
        baseline_clean = (
            transaction.baseline_saved_revision == transaction.base_revision
        )
        session = self.controller.session
        if unchanged and baseline_clean:
            session.saved_revision = session.revision
            session.exported_revision = (
                session.revision
                if transaction.baseline_exported_revision
                == transaction.base_revision
                else transaction.baseline_exported_revision
            )
            session.qa_summary = dict(transaction.baseline_qa_summary)
        session.active_transaction = None
        if session.dirty:
            session.set_state("editing")
        elif (
            session.exported_revision == session.revision
            and session.qa_summary.get("ready_to_use") is True
        ):
            session.set_state("ready")
        else:
            session.set_state("canvas_ready")
        canonical_unchanged = bool(
            transaction.baseline_document_sha256 is None
            or (
                self.controller.document_path.is_file()
                and file_sha256(self.controller.document_path)
                == transaction.baseline_document_sha256
            )
        )
        return self._record_with_session_rollback(
            session_before,
            {
                "event": "assistant_transaction_committed",
                "provider": transaction.provider,
                "transaction_id": transaction.transaction_id,
                "revision": session.revision,
                "transaction": terminal.to_dict(),
                "structural_qa": json_safe(qa),
                "verification": {
                    "live_render_sha256": render,
                    "structural_qa_passed": qa.get("status") != "failed",
                    "canonical_vsz_unchanged_before_save": canonical_unchanged,
                    "raw_inputs_mutated": False,
                },
            },
        )

    def rollback(self, *, reason: str) -> dict[str, Any]:
        transaction = self._require_transaction()
        return self.controller.restore_transaction_baseline(
            transaction.transaction_id,
            outcome="rolled_back",
            reason=reason,
        )

    def reject_transaction(self, *, reason: str) -> dict[str, Any]:
        transaction = self._require_transaction()
        return self.controller.restore_transaction_baseline(
            transaction.transaction_id,
            outcome="rejected",
            reason=reason,
        )

    def _mark_conflict(self, reason: str) -> None:
        transaction = self._require_transaction()
        session_before = self.controller.session.to_dict()
        transaction.status = "conflict"
        transaction.applying_batch_id = None
        transaction.updated_at = self._now()
        self.controller.session.set_state("conflict")
        self._record_with_session_rollback(
            session_before,
            {
                "event": "assistant_transaction_conflict",
                "provider": transaction.provider,
                "transaction_id": transaction.transaction_id,
                "revision": self.controller.session.revision,
                "reason": reason,
            },
        )

    def reconcile_on_open(self) -> None:
        transaction = self.transaction
        if transaction is None:
            return
        if transaction.status in {"committed", "rejected", "rolled_back"}:
            self._mark_conflict(
                "A terminal transaction was persisted as active."
            )
            return
        if not transaction.baseline_complete:
            self._mark_conflict(
                "The persisted assistant transaction has no verified baseline."
            )
            return
        try:
            baseline = self.controller._resolve_transaction_artifact(
                str(transaction.snapshot_path),
                transaction_id=transaction.transaction_id,
            )
            review = self.controller._resolve_transaction_artifact(
                str(transaction.review_snapshot_path),
                transaction_id=transaction.transaction_id,
            )
            integrity_ok = bool(
                baseline.is_file()
                and file_sha256(baseline) == transaction.snapshot_sha256
                and review.is_file()
                and file_sha256(review) == transaction.review_snapshot_sha256
            )
        except Exception:
            integrity_ok = False
        if not integrity_ok:
            self._mark_conflict(
                "The persisted assistant transaction baseline failed integrity."
            )
            return
        if transaction.current_revision != self.controller.session.revision:
            self._mark_conflict(
                "The persisted assistant transaction revision does not match "
                "the recovered document."
            )
            return
        request_record = transaction.parsed_request_record
        if request_record is not None and request_record.provider_running:
            session_before = self.controller.session.to_dict()
            request_id = request_record.parsed_request.request_id
            request_record.interrupt(
                "The provider process was not active when the Canvas reopened."
            )
            transaction.set_request_record(request_record)
            transaction.status = "paused"
            transaction.updated_at = self._now()
            self.controller.session.set_state("ai_proposing")
            self._record_with_session_rollback(
                session_before,
                {
                    "event": "assistant_request_interrupted",
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "request_id": request_id,
                    "revision": self.controller.session.revision,
                    "error": request_record.error,
                    "paused_for_review": True,
                    "publication_document_changed": False,
                },
            )
            return
        if transaction.applying_batch_id is not None:
            session_before = self.controller.session.to_dict()
            interrupted_batch = transaction.applying_batch_id
            transaction.applying_batch_id = None
            transaction.status = "paused"
            transaction.updated_at = self._now()
            self.controller.session.set_state("ai_proposing")
            self._record_with_session_rollback(
                session_before,
                {
                    "event": "assistant_transaction_interrupted",
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "batch_id": interrupted_batch,
                    "revision": self.controller.session.revision,
                    "proposal_preserved": transaction.pending_batch is not None,
                    "paused_for_review": True,
                },
            )
            return
        self.controller.session.set_state("ai_proposing")
        self.controller.persist()


__all__ = ["AssistantTransactionCoordinator"]
