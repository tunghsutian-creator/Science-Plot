from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.assistant_contract import (
    DataMappingConfirmation,
    DataMappingProposal,
)
from sciplot_core.canvas.model import (
    CanvasSession,
    CanvasTransaction,
)
from sciplot_core.canvas.operations import CanvasOperationBatch
from sciplot_core.canvas.provider import (
    ASSISTANT_MAX_INTENT_LENGTH,
    AssistantDataMappingState,
    AssistantProgressEvent,
    AssistantProviderDescriptor,
    AssistantRequest,
    AssistantRequestRecord,
    AssistantResponse,
)
from sciplot_core.data_mapping import (
    DATA_MAPPING_EXECUTION_FILENAME,
    create_data_mapping_confirmation,
    load_data_mapping_execution,
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

    @property
    def mapping_state(self) -> AssistantDataMappingState | None:
        record = self.request_record
        return record.parsed_mapping_state if record is not None else None

    @property
    def mapping_proposal(self) -> DataMappingProposal | None:
        record = self.request_record
        response = record.parsed_response if record is not None else None
        if response is None or response.proposal_kind != "data_mapping_proposal":
            return None
        return DataMappingProposal.from_dict(dict(response.proposal or {}))

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
            "explicit_selected_point_included": selection.get("data_point") is not None,
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
            baseline_structural_qa_summary=dict(session.structural_qa_summary),
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
                        "exported_revision": session_before["exported_revision"],
                        "session_state": session_before["state"],
                        "document_sha256": session_before["document_sha256"],
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
                understanding=("Stopped before a provider proposal could be accepted."),
                warnings=(
                    "A late provider response was discarded after cancellation.",
                ),
            )
        session_before = self.controller.session.to_dict()
        try:
            preview: dict[str, Any] | None = None
            if restored.status == "proposal" and restored.proposal_kind == (
                "canvas_operation_batch"
            ):
                batch = CanvasOperationBatch.from_dict(dict(restored.proposal or {}))
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

    def _set_mapping_state(
        self,
        state: AssistantDataMappingState,
        *,
        event: str,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        transaction = self._require_transaction()
        record = transaction.parsed_request_record
        if record is None:
            raise RuntimeError("No Assistant request is active.")
        session_before = self.controller.session.to_dict()
        record.set_mapping_state(state)
        transaction.set_request_record(record)
        transaction.status = "paused"
        transaction.updated_at = self._now()
        self.controller.session.set_state("needs_human_confirmation")
        return self._record_with_session_rollback(
            session_before,
            {
                "event": event,
                "provider": transaction.provider,
                "transaction_id": transaction.transaction_id,
                "request_id": record.parsed_request.request_id,
                "revision": self.controller.session.revision,
                "mapping_state": state.to_dict(),
                "evidence": json_safe(evidence or {}),
                "publication_document_changed": False,
                "raw_inputs_mutated": False,
            },
        )

    def begin_mapping_preview(self, *, source_root: Path) -> dict[str, Any]:
        state = self.mapping_state
        if state is None or state.status not in {
            "proposed",
            "source_required",
            "preview_ready",
        }:
            raise RuntimeError("Data mapping is not ready for source validation.")
        state.status = "previewing"
        state.source_root = str(source_root.expanduser().resolve())
        state.output_root = None
        state.preview = None
        state.confirmation = None
        state.execution_manifest = None
        state.execution_manifest_sha256 = None
        state.mapped_document = None
        state.mapped_document_sha256 = None
        state.last_error = None
        state.updated_at = self._now()
        return self._set_mapping_state(
            state,
            event="assistant_data_mapping_preview_started",
            evidence={"source_root": state.source_root},
        )

    def complete_mapping_preview(
        self,
        preview: dict[str, Any],
        *,
        output_root: Path,
    ) -> dict[str, Any]:
        state = self.mapping_state
        if state is None or state.status != "previewing":
            raise RuntimeError("No data-mapping preview is active.")
        state.status = "preview_ready"
        state.preview = dict(preview)
        state.output_root = str(output_root.expanduser().resolve())
        state.last_error = None
        state.updated_at = self._now()
        return self._set_mapping_state(
            state,
            event="assistant_data_mapping_preview_ready",
            evidence={
                "proposal_sha256": preview.get("proposal_sha256"),
                "base_request_sha256": preview.get("base_request_sha256"),
                "source_count": len(preview.get("sources") or []),
                "writes_performed": preview.get("writes_performed"),
                "raw_values_in_preview": preview.get("raw_values_in_preview"),
            },
        )

    def require_mapping_source(
        self,
        error: str,
        *,
        source_root: Path | None = None,
    ) -> dict[str, Any]:
        state = self.mapping_state
        if state is None or state.status not in {
            "proposed",
            "source_required",
            "previewing",
            "preview_ready",
        }:
            raise RuntimeError("Data mapping cannot request another source root.")
        state.status = "source_required"
        state.source_root = (
            str(source_root.expanduser().resolve())
            if source_root is not None
            else state.source_root
        )
        state.output_root = None
        state.preview = None
        state.confirmation = None
        state.execution_manifest = None
        state.execution_manifest_sha256 = None
        state.mapped_document = None
        state.mapped_document_sha256 = None
        state.last_error = str(error or "Select the folder containing the sources.")
        state.updated_at = self._now()
        return self._set_mapping_state(
            state,
            event="assistant_data_mapping_source_required",
            evidence={"error": state.last_error},
        )

    def confirm_mapping(
        self,
        *,
        confirmed_by: str,
    ) -> DataMappingConfirmation:
        state = self.mapping_state
        proposal = self.mapping_proposal
        if state is None or proposal is None or state.status != "preview_ready":
            raise RuntimeError("Data mapping has no verified preview to confirm.")
        if state.source_root is None:
            raise RuntimeError("Data mapping source root is missing.")
        if state.output_root is None:
            raise RuntimeError("Data mapping output root is missing.")
        request_path = Path(str(state.preview.get("base_request") or ""))
        receipt = create_data_mapping_confirmation(
            proposal,
            source_root=Path(state.source_root),
            request_path=request_path,
            output_root=Path(state.output_root),
            confirmed_by=confirmed_by,
        )
        state.status = "confirmed"
        state.confirmation = receipt.to_dict()
        state.last_error = None
        state.updated_at = self._now()
        self._set_mapping_state(
            state,
            event="assistant_data_mapping_confirmed",
            evidence={
                "confirmation_id": receipt.confirmation_id,
                "proposal_sha256": receipt.proposal_sha256,
                "base_request_sha256": receipt.base_request_sha256,
                "confirmation_source": "explicit_canvas_user_action",
            },
        )
        return receipt

    def begin_mapping_execution(self) -> dict[str, Any]:
        state = self.mapping_state
        if state is None or state.status != "confirmed":
            raise RuntimeError("Data mapping has no confirmed execution to start.")
        state.status = "executing"
        state.last_error = None
        state.updated_at = self._now()
        return self._set_mapping_state(
            state,
            event="assistant_data_mapping_execution_started",
            evidence={
                "confirmation_id": (state.confirmation or {}).get("confirmation_id"),
                "output_root": state.output_root,
            },
        )

    def fail_mapping_task(self, error: str) -> dict[str, Any]:
        state = self.mapping_state
        if state is None or state.status not in {"previewing", "executing"}:
            raise RuntimeError("No data-mapping task is active.")
        failed_stage = state.status
        state.status = "confirmed" if failed_stage == "executing" else "source_required"
        if failed_stage == "previewing":
            state.preview = None
            state.confirmation = None
            state.output_root = None
        state.last_error = str(error or "Data mapping task failed.")
        state.updated_at = self._now()
        return self._set_mapping_state(
            state,
            event="assistant_data_mapping_task_failed",
            evidence={"failed_stage": failed_stage, "error": state.last_error},
        )

    def complete_mapping_execution(
        self,
        execution: dict[str, Any],
        *,
        mapped_document: Path,
    ) -> dict[str, Any]:
        state = self.mapping_state
        proposal = self.mapping_proposal
        if state is None or proposal is None or state.status != "executing":
            raise RuntimeError("No confirmed data-mapping execution is active.")
        execution_root = Path(str(execution.get("output_root") or ""))
        manifest_path = execution_root / DATA_MAPPING_EXECUTION_FILENAME
        verified = load_data_mapping_execution(manifest_path)
        if verified.get("handoff_allowed") is not True:
            raise ValueError(
                "Executed mapping requires an explicit current confirmation before handoff."
            )
        receipt = DataMappingConfirmation.from_dict(dict(state.confirmation or {}))
        expected_execution_root = (
            Path(receipt.output_root) / proposal.proposal_id
        ).resolve()
        if execution_root.resolve() != expected_execution_root:
            raise ValueError("Executed mapping output path changed after confirmation.")
        if verified.get("proposal_sha256") != receipt.proposal_sha256:
            raise ValueError("Executed mapping proposal hash changed.")
        if verified.get("confirmation_id") != receipt.confirmation_id:
            raise ValueError("Executed mapping confirmation changed.")
        if verified.get("base_request_sha256") != proposal.base_request_sha256:
            raise ValueError("Executed mapping request binding changed.")
        if verified.get("raw_inputs_unchanged") is not True:
            raise ValueError("Executed mapping did not prove raw-input immutability.")
        document_path = mapped_document.expanduser().resolve()
        if document_path != expected_execution_root / "studio" / "document.vsz":
            raise ValueError("Mapped Canvas document path is not canonical.")
        if not document_path.is_file():
            raise FileNotFoundError(document_path)
        state.status = "executed"
        state.execution_manifest = str(manifest_path.resolve())
        state.execution_manifest_sha256 = file_sha256(manifest_path)
        state.mapped_document = str(document_path)
        state.mapped_document_sha256 = file_sha256(document_path)
        state.last_error = None
        state.updated_at = self._now()
        return self._set_mapping_state(
            state,
            event="assistant_data_mapping_execution_ready",
            evidence={
                "execution_manifest": state.execution_manifest,
                "execution_manifest_sha256": state.execution_manifest_sha256,
                "mapped_document": state.mapped_document,
                "mapped_document_sha256": state.mapped_document_sha256,
                "request_candidate": verified.get("request_candidate"),
                "raw_inputs_unchanged": verified.get("raw_inputs_unchanged"),
                "ready_to_use": verified.get("ready_to_use"),
            },
        )

    def accept_mapping_handoff(self) -> dict[str, Any]:
        transaction = self._require_transaction()
        record = transaction.parsed_request_record
        state = record.parsed_mapping_state if record is not None else None
        if record is None or state is None or state.status != "executed":
            raise RuntimeError("No verified mapped Canvas is ready to accept.")
        original_document_sha256 = self.ensure_original_document_unchanged()
        session_before = self.controller.session.to_dict()
        record.mark_proposal_outcome(accepted=True)
        transaction.set_request_record(record)
        self.controller.session.set_state("ai_proposing")
        return self._record_with_session_rollback(
            session_before,
            {
                "event": "assistant_data_mapping_handoff_opened",
                "provider": transaction.provider,
                "transaction_id": transaction.transaction_id,
                "request_id": record.parsed_request.request_id,
                "revision": self.controller.session.revision,
                "execution_manifest": state.execution_manifest,
                "execution_manifest_sha256": state.execution_manifest_sha256,
                "original_document_sha256": original_document_sha256,
                "publication_document_changed": False,
                "raw_inputs_mutated": False,
            },
        )

    def reject_mapping(self, *, reason: str) -> dict[str, Any]:
        transaction = self._require_transaction()
        record = transaction.parsed_request_record
        if record is None or record.parsed_mapping_state is None:
            raise RuntimeError("No data-mapping proposal is pending.")
        session_before = self.controller.session.to_dict()
        record.mark_proposal_outcome(accepted=False)
        transaction.set_request_record(record)
        transaction.status = "paused"
        transaction.updated_at = self._now()
        self.controller.session.set_state("ai_proposing")
        return self._record_with_session_rollback(
            session_before,
            {
                "event": "assistant_data_mapping_rejected",
                "provider": transaction.provider,
                "transaction_id": transaction.transaction_id,
                "request_id": record.parsed_request.request_id,
                "revision": self.controller.session.revision,
                "reason": str(reason or "").strip(),
                "publication_document_changed": False,
                "raw_inputs_mutated": False,
            },
        )

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
        self.ensure_original_document_unchanged()
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
        canonical_sha256 = self.ensure_original_document_unchanged()
        session_before = self.controller.session.to_dict()
        session = self.controller.session
        if unchanged and baseline_clean:
            session.saved_revision = session.revision
            session.exported_revision = (
                session.revision
                if transaction.baseline_exported_revision == transaction.base_revision
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
            or canonical_sha256 == transaction.baseline_document_sha256
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

    def ensure_original_document_unchanged(self) -> str | None:
        transaction = self._require_transaction()
        baseline = transaction.baseline_document_sha256
        if baseline is None:
            return None
        document_path = self.controller.document_path
        if not document_path.is_file():
            self._mark_conflict(
                "The exact-current VSZ disappeared during the Assistant turn."
            )
            raise ValueError("The original exact-current VSZ is missing.")
        current = file_sha256(document_path)
        if current != baseline:
            self._mark_conflict(
                "The exact-current VSZ changed outside the active Assistant turn."
            )
            raise ValueError(
                "The original exact-current VSZ changed; mapped handoff is blocked."
            )
        return current

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
            self._mark_conflict("A terminal transaction was persisted as active.")
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
        mapping_state = (
            request_record.parsed_mapping_state if request_record is not None else None
        )
        if mapping_state is not None and mapping_state.status in {
            "previewing",
            "executing",
        }:
            session_before = self.controller.session.to_dict()
            interrupted_stage = mapping_state.status
            mapping_state.status = (
                "confirmed" if interrupted_stage == "executing" else "source_required"
            )
            mapping_state.last_error = (
                "The deterministic mapping task was interrupted when Canvas "
                "closed. Retry uses the same verified proposal and confirmation."
            )
            mapping_state.updated_at = self._now()
            request_record.set_mapping_state(mapping_state)
            transaction.set_request_record(request_record)
            transaction.status = "paused"
            transaction.updated_at = self._now()
            self.controller.session.set_state("needs_human_confirmation")
            self._record_with_session_rollback(
                session_before,
                {
                    "event": "assistant_data_mapping_task_interrupted",
                    "provider": transaction.provider,
                    "transaction_id": transaction.transaction_id,
                    "request_id": request_record.parsed_request.request_id,
                    "revision": self.controller.session.revision,
                    "interrupted_stage": interrupted_stage,
                    "recovery_state": mapping_state.status,
                    "confirmation_preserved": (mapping_state.confirmation is not None),
                    "publication_document_changed": False,
                    "raw_inputs_mutated": False,
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
