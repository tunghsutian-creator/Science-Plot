from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.canvas.model import CanvasTransaction
from sciplot_core.canvas.provider import (
    ASSISTANT_MAX_INTENT_LENGTH,
    AssistantDataMappingState,
    AssistantProviderDescriptor,
    AssistantRequestRecord,
)

_MAX_REQUEST_LENGTH = ASSISTANT_MAX_INTENT_LENGTH


def _display_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "On" if value else "Off"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        text = ", ".join(_display_value(item) for item in value)
        return text if len(text) <= 64 else f"{text[:61]}…"
    if isinstance(value, dict):
        return f"{len(value)} settings"
    text = str(value)
    return text if len(text) <= 72 else f"{text[:69]}…"


def _allow_horizontal_shrink(widget: QtWidgets.QWidget) -> None:
    widget.setMinimumWidth(0)
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Policy.Ignored)
    widget.setSizePolicy(policy)


class AssistantTransactionPanel(QtWidgets.QWidget):
    """State-driven request, progress, and typed-proposal review surface."""

    requestSubmitted = QtCore.pyqtSignal(str)
    cancelRequestRequested = QtCore.pyqtSignal()
    pauseRequested = QtCore.pyqtSignal()
    resumeRequested = QtCore.pyqtSignal()
    acceptRequested = QtCore.pyqtSignal()
    rejectProposalRequested = QtCore.pyqtSignal()
    undoBatchRequested = QtCore.pyqtSignal()
    commitRequested = QtCore.pyqtSignal()
    rollbackRequested = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("assistantPanel")
        self.setAccessibleName("Assistant transaction inspector")
        self.setAccessibleDescription(
            "Ask for a scientific figure change, inspect provider progress, "
            "review typed proposals, and recover the exact starting document."
        )
        self._provider: AssistantProviderDescriptor | None = None
        self._transaction: CanvasTransaction | None = None
        self._request_record: AssistantRequestRecord | None = None
        self._can_undo = False
        self._busy = False
        self._mapping_active = False
        self._mapping_stage = ""
        self._mapping_message = ""
        self._trimming_request = False
        self._build()
        self.set_transaction(None, context={}, can_undo=False)

    def _build(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setObjectName("assistantScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        content = QtWidgets.QWidget(scroll)
        content.setObjectName("assistantContent")
        _allow_horizontal_shrink(content)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QtWidgets.QHBoxLayout()
        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(2)
        title = QtWidgets.QLabel("Assistant")
        title.setObjectName("inspectorTitle")
        subtitle = QtWidgets.QLabel("Typed help on the exact-current Canvas")
        subtitle.setObjectName("inspectorContext")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        self.state_chip = QtWidgets.QLabel("Idle")
        self.state_chip.setObjectName("assistantStateChip")
        self.state_chip.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.state_chip.setMinimumWidth(68)
        header.addWidget(self.state_chip, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        empty = QtWidgets.QFrame()
        empty.setObjectName("assistantEmptyCard")
        empty_layout = QtWidgets.QVBoxLayout(empty)
        empty_layout.setContentsMargins(14, 14, 14, 14)
        empty_layout.setSpacing(6)
        empty_title = QtWidgets.QLabel("AI is optional")
        empty_title.setObjectName("assistantCardTitle")
        empty_copy = QtWidgets.QLabel(
            "Canvas editing, review, QA, save, and export remain available "
            "without a provider. A connected provider can return only a typed "
            "DataMappingProposal or CanvasOperationBatch."
        )
        empty_copy.setObjectName("assistantBody")
        empty_copy.setWordWrap(True)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_copy)
        self.empty_card = empty
        layout.addWidget(empty)

        composer = QtWidgets.QFrame()
        composer.setObjectName("assistantComposerCard")
        composer_layout = QtWidgets.QVBoxLayout(composer)
        composer_layout.setContentsMargins(14, 12, 14, 12)
        composer_layout.setSpacing(8)
        composer_header = QtWidgets.QHBoxLayout()
        composer_title = QtWidgets.QLabel("Ask about this figure")
        composer_title.setObjectName("assistantCardTitle")
        self.connected_provider_label = QtWidgets.QLabel()
        self.connected_provider_label.setObjectName("assistantMeta")
        self.connected_provider_label.setMaximumWidth(140)
        self.connected_provider_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        composer_header.addWidget(composer_title)
        composer_header.addStretch(1)
        composer_header.addWidget(self.connected_provider_label)
        composer_layout.addLayout(composer_header)
        self.request_editor = QtWidgets.QPlainTextEdit()
        self.request_editor.setObjectName("assistantRequestEditor")
        self.request_editor.setAccessibleName("Assistant request")
        self.request_editor.setAccessibleDescription(
            "Describe one scientific figure change. Press Command or Control "
            "and Return to submit."
        )
        self.request_editor.setPlaceholderText(
            "For example: Rename the selected x-axis to frequency, use ω, and "
            "keep the current logarithmic scale."
        )
        self.request_editor.setTabChangesFocus(True)
        self.request_editor.setMinimumWidth(0)
        self.request_editor.setMinimumHeight(76)
        self.request_editor.setMaximumHeight(112)
        composer_layout.addWidget(self.request_editor)
        self.request_scope_label = QtWidgets.QLabel()
        self.request_scope_label.setObjectName("assistantMeta")
        self.request_scope_label.setWordWrap(True)
        composer_layout.addWidget(self.request_scope_label)
        composer_footer = QtWidgets.QHBoxLayout()
        self.request_count_label = QtWidgets.QLabel(f"0 / {_MAX_REQUEST_LENGTH}")
        self.request_count_label.setObjectName("assistantMeta")
        self.send_button = QtWidgets.QPushButton("Ask Assistant")
        self.send_button.setObjectName("assistantPrimaryButton")
        self.send_button.setAccessibleDescription(
            "Submit this intent with bounded Canvas context."
        )
        composer_footer.addWidget(self.request_count_label)
        composer_footer.addStretch(1)
        composer_footer.addWidget(self.send_button)
        composer_layout.addLayout(composer_footer)
        self.composer_card = composer
        layout.addWidget(composer)

        summary = QtWidgets.QFrame()
        summary.setObjectName("assistantCard")
        summary_layout = QtWidgets.QVBoxLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(7)
        summary_title = QtWidgets.QLabel("Current turn")
        summary_title.setObjectName("assistantCardTitle")
        summary_layout.addWidget(summary_title)
        self.provider_label = QtWidgets.QLabel()
        self.provider_label.setObjectName("assistantMeta")
        self.provider_label.setWordWrap(True)
        self.provider_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.revision_label = QtWidgets.QLabel()
        self.revision_label.setObjectName("assistantMeta")
        self.revision_label.setWordWrap(True)
        self.rationale_label = QtWidgets.QLabel()
        self.rationale_label.setObjectName("assistantBody")
        self.rationale_label.setWordWrap(True)
        summary_layout.addWidget(self.provider_label)
        summary_layout.addWidget(self.revision_label)
        summary_layout.addWidget(self.rationale_label)
        self.summary_card = summary
        layout.addWidget(summary)

        context_card = QtWidgets.QFrame()
        context_card.setObjectName("assistantCard")
        context_layout = QtWidgets.QVBoxLayout(context_card)
        context_layout.setContentsMargins(14, 12, 14, 12)
        context_layout.setSpacing(6)
        context_title = QtWidgets.QLabel("Shared context")
        context_title.setObjectName("assistantCardTitle")
        self.selection_label = QtWidgets.QLabel()
        self.selection_label.setObjectName("assistantBody")
        self.selection_label.setWordWrap(True)
        self.context_label = QtWidgets.QLabel()
        self.context_label.setObjectName("assistantMeta")
        self.context_label.setWordWrap(True)
        context_layout.addWidget(context_title)
        context_layout.addWidget(self.selection_label)
        context_layout.addWidget(self.context_label)
        self.context_card = context_card
        layout.addWidget(context_card)

        progress_card = QtWidgets.QFrame()
        progress_card.setObjectName("assistantProgressCard")
        progress_layout = QtWidgets.QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(14, 12, 14, 12)
        progress_layout.setSpacing(8)
        progress_header = QtWidgets.QHBoxLayout()
        self.progress_stage_label = QtWidgets.QLabel("Working")
        self.progress_stage_label.setObjectName("assistantCardTitle")
        self.cancel_request_button = QtWidgets.QPushButton("Stop")
        self.cancel_request_button.setObjectName("assistantSecondaryButton")
        self.cancel_request_button.setAccessibleDescription(
            "Ask the provider to stop. No proposal will be accepted automatically."
        )
        progress_header.addWidget(self.progress_stage_label)
        progress_header.addStretch(1)
        progress_header.addWidget(self.cancel_request_button)
        self.progress_message = QtWidgets.QLabel()
        self.progress_message.setObjectName("assistantBody")
        self.progress_message.setWordWrap(True)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setObjectName("assistantProgressBar")
        self.progress_bar.setTextVisible(False)
        progress_layout.addLayout(progress_header)
        progress_layout.addWidget(self.progress_message)
        progress_layout.addWidget(self.progress_bar)
        self.progress_card = progress_card
        layout.addWidget(progress_card)

        understanding_card = QtWidgets.QFrame()
        understanding_card.setObjectName("assistantCard")
        understanding_layout = QtWidgets.QVBoxLayout(understanding_card)
        understanding_layout.setContentsMargins(14, 12, 14, 12)
        understanding_layout.setSpacing(6)
        understanding_title = QtWidgets.QLabel("What I understood")
        understanding_title.setObjectName("assistantCardTitle")
        self.understanding_label = QtWidgets.QLabel()
        self.understanding_label.setObjectName("assistantBody")
        self.understanding_label.setWordWrap(True)
        self.warning_label = QtWidgets.QLabel()
        self.warning_label.setObjectName("assistantWarningCopy")
        self.warning_label.setWordWrap(True)
        understanding_layout.addWidget(understanding_title)
        understanding_layout.addWidget(self.understanding_label)
        understanding_layout.addWidget(self.warning_label)
        self.understanding_card = understanding_card
        layout.addWidget(understanding_card)

        proposal = QtWidgets.QFrame()
        proposal.setObjectName("assistantProposalCard")
        proposal_layout = QtWidgets.QVBoxLayout(proposal)
        proposal_layout.setContentsMargins(14, 12, 14, 12)
        proposal_layout.setSpacing(8)
        proposal_header = QtWidgets.QHBoxLayout()
        self.proposal_title = QtWidgets.QLabel("Review proposal")
        self.proposal_title.setObjectName("assistantCardTitle")
        self.operation_count = QtWidgets.QLabel()
        self.operation_count.setObjectName("assistantMeta")
        proposal_header.addWidget(self.proposal_title)
        proposal_header.addStretch(1)
        proposal_header.addWidget(self.operation_count)
        proposal_layout.addLayout(proposal_header)
        self.change_list = QtWidgets.QWidget()
        self.change_list.setObjectName("assistantChangeList")
        self.change_list_layout = QtWidgets.QVBoxLayout(self.change_list)
        self.change_list_layout.setContentsMargins(0, 0, 0, 0)
        self.change_list_layout.setSpacing(8)
        proposal_layout.addWidget(self.change_list)
        self.change_count = 0
        self.proposal_card = proposal
        layout.addWidget(proposal)

        self.status_copy = QtWidgets.QLabel()
        self.status_copy.setObjectName("assistantStatusCopy")
        self.status_copy.setWordWrap(True)
        layout.addWidget(self.status_copy)
        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        actions = QtWidgets.QFrame(self)
        actions.setObjectName("assistantActionBar")
        action_layout = QtWidgets.QVBoxLayout(actions)
        action_layout.setContentsMargins(12, 10, 12, 12)
        action_layout.setSpacing(8)

        self.proposal_action_widget = QtWidgets.QWidget(actions)
        proposal_actions = QtWidgets.QHBoxLayout(self.proposal_action_widget)
        proposal_actions.setContentsMargins(0, 0, 0, 0)
        proposal_actions.setSpacing(8)
        self.reject_button = QtWidgets.QPushButton("Reject Proposal")
        self.reject_button.setObjectName("assistantSecondaryButton")
        self.accept_button = QtWidgets.QPushButton("Accept and Apply")
        self.accept_button.setObjectName("assistantPrimaryButton")
        proposal_actions.addWidget(self.reject_button)
        proposal_actions.addWidget(self.accept_button, 1)
        action_layout.addWidget(self.proposal_action_widget)

        self.turn_action_widget = QtWidgets.QWidget(actions)
        turn_actions = QtWidgets.QHBoxLayout(self.turn_action_widget)
        turn_actions.setContentsMargins(0, 0, 0, 0)
        turn_actions.setSpacing(8)
        self.undo_button = QtWidgets.QPushButton("Undo Last Batch")
        self.undo_button.setObjectName("assistantSecondaryButton")
        self.commit_button = QtWidgets.QPushButton("Commit Turn")
        self.commit_button.setObjectName("assistantPrimaryButton")
        turn_actions.addWidget(self.undo_button)
        turn_actions.addWidget(self.commit_button, 1)
        action_layout.addWidget(self.turn_action_widget)

        self.safety_action_widget = QtWidgets.QWidget(actions)
        safety_actions = QtWidgets.QHBoxLayout(self.safety_action_widget)
        safety_actions.setContentsMargins(0, 0, 0, 0)
        safety_actions.setSpacing(8)
        self.pause_button = QtWidgets.QPushButton("Pause Turn")
        self.pause_button.setObjectName("assistantSecondaryButton")
        self.rollback_button = QtWidgets.QPushButton("Roll Back Entire Turn")
        self.rollback_button.setObjectName("assistantDangerButton")
        safety_actions.addWidget(self.pause_button)
        safety_actions.addWidget(self.rollback_button, 1)
        action_layout.addWidget(self.safety_action_widget)
        root.addWidget(actions)
        self.action_bar = actions

        for widget in (
            subtitle,
            empty_copy,
            self.connected_provider_label,
            self.request_scope_label,
            self.provider_label,
            self.revision_label,
            self.rationale_label,
            self.selection_label,
            self.context_label,
            self.progress_message,
            self.understanding_label,
            self.warning_label,
            self.status_copy,
        ):
            _allow_horizontal_shrink(widget)
        for button in (
            self.send_button,
            self.cancel_request_button,
            self.reject_button,
            self.accept_button,
            self.undo_button,
            self.commit_button,
            self.pause_button,
            self.rollback_button,
        ):
            button.setMinimumWidth(0)

        self.send_button.clicked.connect(self._submit_request)
        self.request_editor.textChanged.connect(self._request_text_changed)
        self.cancel_request_button.clicked.connect(self.cancelRequestRequested)
        self.pause_button.clicked.connect(self._pause_or_resume)
        self.accept_button.clicked.connect(self.acceptRequested)
        self.reject_button.clicked.connect(self.rejectProposalRequested)
        self.undo_button.clicked.connect(self.undoBatchRequested)
        self.commit_button.clicked.connect(self.commitRequested)
        self.rollback_button.clicked.connect(self.rollbackRequested)
        self._submit_shortcuts = [
            QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self.request_editor),
            QtGui.QShortcut(QtGui.QKeySequence("Meta+Return"), self.request_editor),
        ]
        for shortcut in self._submit_shortcuts:
            shortcut.activated.connect(self._submit_request)

    def set_provider(
        self,
        descriptor: AssistantProviderDescriptor | None,
    ) -> None:
        self._provider = (
            AssistantProviderDescriptor.from_dict(descriptor.to_dict())
            if descriptor is not None
            else None
        )
        self._sync_actions()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_actions()

    def set_mapping_activity(
        self,
        active: bool,
        *,
        stage: str = "",
        message: str = "",
    ) -> None:
        self._mapping_active = bool(active)
        self._mapping_stage = str(stage or "")
        self._mapping_message = str(message or "")
        self._sync_request_response()
        self._sync_actions()

    def mark_request_submitted(self) -> None:
        self.request_editor.clear()
        self._sync_actions()

    def _request_text_changed(self) -> None:
        if self._trimming_request:
            return
        text = self.request_editor.toPlainText()
        if len(text) > _MAX_REQUEST_LENGTH:
            self._trimming_request = True
            cursor = self.request_editor.textCursor()
            position = min(cursor.position(), _MAX_REQUEST_LENGTH)
            self.request_editor.setPlainText(text[:_MAX_REQUEST_LENGTH])
            cursor = self.request_editor.textCursor()
            cursor.setPosition(position)
            self.request_editor.setTextCursor(cursor)
            self._trimming_request = False
            text = self.request_editor.toPlainText()
        self.request_count_label.setText(f"{len(text)} / {_MAX_REQUEST_LENGTH}")
        self._sync_actions()

    def _submit_request(self) -> None:
        intent = self.request_editor.toPlainText().strip()
        if self.send_button.isEnabled() and intent:
            self.requestSubmitted.emit(intent)

    def _pause_or_resume(self) -> None:
        transaction = self._transaction
        if transaction is None:
            return
        if transaction.status == "paused":
            self.resumeRequested.emit()
        else:
            self.pauseRequested.emit()

    def set_transaction(
        self,
        transaction: CanvasTransaction | None,
        *,
        context: dict[str, Any],
        can_undo: bool,
    ) -> None:
        self._transaction = transaction
        self._can_undo = bool(can_undo)
        self._request_record = (
            transaction.parsed_request_record if transaction is not None else None
        )
        active = transaction is not None
        provider_connected = self._provider is not None
        self.empty_card.setVisible(not active and not provider_connected)
        self.summary_card.setVisible(active)
        self._sync_context(context)
        self._sync_request_response()

        pending_preview = (
            transaction.pending_preview if transaction is not None else None
        )
        response = (
            self._request_record.parsed_response
            if self._request_record is not None
            else None
        )
        mapping_proposal = (
            response.proposal
            if response is not None
            and response.status == "proposal"
            and response.proposal_kind == "data_mapping_proposal"
            else None
        )
        if pending_preview is not None:
            self.proposal_title.setText("Review proposal")
            self._set_preview(pending_preview)
        elif mapping_proposal is not None:
            self.proposal_title.setText("Confirm data meaning")
            self._set_mapping_proposal(
                mapping_proposal,
                self._request_record.parsed_mapping_state
                if self._request_record is not None
                else None,
            )
        else:
            self._clear_preview_cards()
            self.operation_count.clear()
        has_proposal = pending_preview is not None or mapping_proposal is not None
        self.proposal_card.setVisible(has_proposal)
        self.context_card.setVisible(active and not has_proposal)

        if transaction is None:
            self.state_chip.setText("Ready" if provider_connected else "Idle")
            self.state_chip.setProperty(
                "assistantState", "active" if provider_connected else "idle"
            )
            self.status_copy.setText(
                "Describe one change. SciPlot sends bounded structure, selection, "
                "review notes, and QA — never raw dataset arrays."
                if provider_connected
                else "No provider is connected and no transaction is active."
            )
            self._refresh_chip_style()
            self._sync_actions()
            return

        record_status = self._request_record.status if self._request_record else None
        if record_status in {"queued", "running"}:
            state_text, state_key = "Working", "applying"
        elif record_status == "cancel_requested":
            state_text, state_key = "Stopping", "paused"
        elif self._mapping_active:
            state_text, state_key = "Working", "applying"
        elif transaction.applying_batch_id:
            state_text, state_key = "Applying", "applying"
        elif transaction.status == "conflict":
            state_text, state_key = "Conflict", "conflict"
        elif transaction.pending_batch is not None:
            state_text, state_key = "Proposal", "proposal"
        elif self._request_record is not None and (
            self._request_record.parsed_mapping_state is not None
        ):
            mapping_status = self._request_record.parsed_mapping_state.status
            if mapping_status == "executed":
                state_text, state_key = "Mapped", "active"
            elif mapping_status == "preview_ready":
                state_text, state_key = "Confirm", "proposal"
            elif mapping_status in {"confirmed", "executing"}:
                state_text, state_key = "Building", "applying"
            else:
                state_text, state_key = "Sources", "paused"
        elif transaction.status == "paused":
            state_text, state_key = "Paused", "paused"
        else:
            state_text, state_key = "Ready", "active"
        self.state_chip.setText(state_text)
        self.state_chip.setProperty("assistantState", state_key)
        provider_name = (
            self._provider.display_name
            if self._provider is not None
            and self._provider.provider_id == transaction.provider
            else transaction.provider
        )
        self.provider_label.setText(provider_name)
        provider_tooltip = f"Provider ID: {transaction.provider}"
        if self._provider is not None and self._provider.model_label:
            provider_tooltip += f"\nModel: {self._provider.model_label}"
        self.provider_label.setToolTip(provider_tooltip)
        count = len(transaction.active_batch_ids)
        self.revision_label.setText(
            f"Started at version {transaction.base_revision} · "
            f"Now version {transaction.current_revision} · "
            f"{count} accepted change" + ("" if count == 1 else "s")
        )
        self.rationale_label.setText(transaction.rationale)
        self._set_status_copy(transaction, response)
        self._refresh_chip_style()
        self._sync_actions()

    def _sync_context(self, context: dict[str, Any]) -> None:
        selected = context.get("selected_object")
        if isinstance(selected, dict):
            self.selection_label.setText(
                f"Selection · {selected.get('object_type', 'object')} · "
                f"{selected.get('display_name') or 'Unnamed'}"
            )
        else:
            self.selection_label.setText("Selection · none")
        inventory = context.get("document_inventory")
        review = context.get("review")
        qa = context.get("qa")
        object_count = (
            int(inventory.get("object_count") or 0)
            if isinstance(inventory, dict)
            else 0
        )
        review_count = (
            int(review.get("active_count") or 0) if isinstance(review, dict) else 0
        )
        qa_status = (
            str(qa.get("structural_status") or "not run")
            if isinstance(qa, dict)
            else "not run"
        )
        selected_point = bool(context.get("explicit_selected_point_included"))
        self.context_label.setText(
            f"{object_count} document objects · {review_count} review marks · "
            f"structural QA {qa_status} · raw dataset arrays excluded"
            + (" · selected point included" if selected_point else "")
        )
        if self._provider is not None:
            scope = (
                self.selection_label.text() + " · structure, review notes, and QA only"
            )
            self.request_scope_label.setText(scope)
        else:
            self.request_scope_label.clear()

    def _sync_request_response(self) -> None:
        record = self._request_record
        running = record is not None and record.provider_running
        self.progress_card.setVisible(running or self._mapping_active)
        response = record.parsed_response if record is not None else None
        self.understanding_card.setVisible(response is not None)
        if response is not None:
            self.understanding_label.setText(response.understanding)
            warnings = "\n".join(f"• {item}" for item in response.warnings)
            self.warning_label.setText(warnings)
            self.warning_label.setVisible(bool(warnings))
        else:
            self.understanding_label.clear()
            self.warning_label.clear()
            self.warning_label.hide()
        if self._mapping_active:
            self.progress_stage_label.setText(
                (self._mapping_stage or "deterministic mapping")
                .replace("_", " ")
                .title()
            )
            self.progress_message.setText(
                self._mapping_message or "Verifying the deterministic mapping contract."
            )
            self.progress_bar.setRange(0, 0)
            self.cancel_request_button.hide()
            return
        self.cancel_request_button.show()
        if not running:
            return
        latest = record.latest_event
        if record.status == "cancel_requested":
            self.progress_stage_label.setText("Stopping safely")
            self.progress_message.setText(
                "Waiting for the provider to acknowledge cancellation. No late "
                "proposal will be accepted."
            )
        elif latest is None:
            self.progress_stage_label.setText("Starting")
            self.progress_message.setText("Preparing bounded Canvas context…")
        else:
            self.progress_stage_label.setText(latest.stage.replace("_", " ").title())
            self.progress_message.setText(latest.message)
        if latest is not None and latest.progress is not None:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(round(latest.progress * 100))
        else:
            self.progress_bar.setRange(0, 0)
        cancellable = bool(
            record.status != "cancel_requested"
            and self._provider is not None
            and self._provider.supports_cancellation
            and (latest is None or latest.cancellable)
        )
        self.cancel_request_button.setEnabled(cancellable and not self._busy)
        self.cancel_request_button.setText(
            "Stopping…" if record.status == "cancel_requested" else "Stop"
        )

    def _set_status_copy(
        self,
        transaction: CanvasTransaction,
        response: Any,
    ) -> None:
        record = self._request_record
        if record is not None and record.status in {"queued", "running"}:
            self.status_copy.setText(
                "The provider is working in place. The Canvas remains unchanged "
                "until you accept a typed proposal."
            )
        elif record is not None and record.status == "cancel_requested":
            self.status_copy.setText(
                "Stopping the provider. After it stops, you can resume, commit "
                "accepted work, or restore the exact starting document."
            )
        elif transaction.status == "conflict":
            self.status_copy.setText(
                "This turn no longer matches the exact-current version. Inspect "
                "the evidence and restore the verified starting document."
            )
        elif transaction.pending_batch is not None:
            self.status_copy.setText(
                "Review the complete Before/After proposal. The figure changes "
                "only after you choose Accept and Apply."
            )
        elif response is not None and response.proposal_kind == "data_mapping_proposal":
            state = record.parsed_mapping_state if record is not None else None
            if state is None:
                self.status_copy.setText(
                    "This changes data meaning and requires deterministic preview "
                    "plus a separate user confirmation."
                )
            elif state.status == "source_required":
                self.status_copy.setText(
                    (state.last_error or "Choose the source folder to continue.")
                    + " No data or figure files were changed."
                )
            elif state.status == "previewing":
                self.status_copy.setText(
                    "SciPlot is verifying source and request hashes without writing "
                    "files."
                )
            elif state.status == "preview_ready":
                self.status_copy.setText(
                    "Review the source roles, row counts, units, transformations, "
                    "and routing. Confirm and Build is the only action that issues a "
                    "receipt and writes an isolated candidate project."
                )
            elif state.status == "confirmed":
                self.status_copy.setText(
                    (state.last_error + " " if state.last_error else "")
                    + "The confirmation receipt is preserved. Resume Build will "
                    "reuse that exact receipt."
                )
            elif state.status == "executing":
                self.status_copy.setText(
                    "Building an isolated candidate project. The original VSZ, "
                    "request, and raw sources remain unchanged."
                )
            elif state.status == "executed":
                self.status_copy.setText(
                    "The verified candidate is ready. Open Mapped Canvas keeps the "
                    "original Canvas unchanged and opens the new exact-current VSZ. "
                    "Its execution evidence cannot be relabeled as rejected."
                )
            else:
                self.status_copy.setText(
                    "This mapping proposal remains paused until its source authority "
                    "and user decision are explicit."
                )
        elif record is not None and record.status == "needs_human_confirmation":
            self.status_copy.setText(
                "The provider found scientific ambiguity. No figure change was "
                "made; clarify the intent or restore the starting document."
            )
        elif record is not None and record.status == "needs_rule_repair":
            self.status_copy.setText(
                "The request is outside the safe operation contract. No figure "
                "change was made."
            )
        elif record is not None and record.status in {"failed", "interrupted"}:
            self.status_copy.setText(
                f"Provider work stopped without changing the figure. {record.error or ''}"
            )
        elif transaction.status == "paused":
            self.status_copy.setText(
                "This turn is paused. Resume to continue, or restore the exact "
                "starting document."
            )
        else:
            self.status_copy.setText(
                "Accepted changes are visible on the live Canvas. Commit keeps "
                "them; whole-turn rollback restores the exact starting document."
            )

    def _set_preview(self, preview: dict[str, Any] | None) -> None:
        self._clear_preview_cards()
        if preview is None:
            self.operation_count.clear()
            return
        changes = preview.get("changes")
        if not isinstance(changes, list):
            changes = []
        self.change_count = len(changes)
        self.operation_count.setText(
            f"{len(changes)} operation" + ("" if len(changes) == 1 else "s")
        )
        for change in changes:
            if not isinstance(change, dict):
                continue
            operation_type = str(change.get("operation_type") or "")
            if operation_type == "set_setting":
                setting_path = str(change.get("setting_path") or "")
                target = setting_path.rsplit("/", 1)[-1] or "Setting"
                before = _display_value(change.get("old_value"))
                after = _display_value(change.get("value"))
                tooltip = setting_path
            else:
                target = (
                    f"Add {change.get('widget_type', 'object')} · "
                    f"{change.get('name', '')}"
                )
                before = "Not present"
                after = _display_value(change.get("settings"))
                tooltip = str(change.get("proposed_path") or "")
            self._add_change_card(
                target=target,
                before=before,
                after=after,
                tooltip=tooltip,
            )

    def _set_mapping_proposal(
        self,
        proposal: dict[str, Any],
        state: AssistantDataMappingState | None,
    ) -> None:
        self._clear_preview_cards()
        sources = proposal.get("sources")
        columns = proposal.get("columns")
        transformations = proposal.get("transformations")
        if not isinstance(sources, list):
            sources = []
        if not isinstance(columns, list):
            columns = []
        if not isinstance(transformations, list):
            transformations = []
        self.change_count = len(sources)
        preview_payload = (
            state.preview if state is not None and state.preview is not None else {}
        )
        preview_sources = {
            str(item.get("source_id") or ""): item
            for item in (preview_payload.get("sources") or [])
            if isinstance(item, dict)
        }
        row_count = sum(
            int(item.get("row_count") or 0) for item in preview_sources.values()
        )
        count_text = f"{len(sources)} source" + ("" if len(sources) == 1 else "s")
        if row_count:
            count_text += f" · {row_count} rows"
        self.operation_count.setText(count_text)
        labels = proposal.get("sample_labels")
        if not isinstance(labels, dict):
            labels = {}
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_id = str(source.get("source_id") or "source")
            mapped = [
                item
                for item in columns
                if isinstance(item, dict) and item.get("source_id") == source_id
            ]
            before = (
                ", ".join(
                    f"column {item.get('source_column_index')}" for item in mapped
                )
                or "No columns"
            )
            after = (
                ", ".join(
                    f"{item.get('role')} → {item.get('output_column')}"
                    for item in mapped
                )
                or "No mapped roles"
            )
            sample = str(labels.get(source_id) or source_id)
            preview = preview_sources.get(source_id, {})
            if preview:
                units = preview.get("units")
                unit_text = (
                    ", ".join(f"{key}: {value}" for key, value in units.items())
                    if isinstance(units, dict) and units
                    else "units unchanged"
                )
                after += f" · {preview.get('row_count', 0)} rows · {unit_text}"
                transform_names = [
                    str(item.get("transformation_type") or "transformation")
                    for item in preview.get("transformations", [])
                    if isinstance(item, dict)
                ]
                tooltip = (
                    ", ".join(transform_names)
                    if transform_names
                    else "No declared transformations"
                )
            else:
                tooltip = f"{len(transformations)} declared transformation" + (
                    "" if len(transformations) == 1 else "s"
                )
            self._add_change_card(
                target=f"{sample} · {source.get('relative_path', '')}",
                before=before,
                after=after,
                tooltip=tooltip,
            )
        if state is not None and (
            state.source_root or state.output_root or preview_payload.get("base_request")
        ):
            source_root = state.source_root or "Not resolved"
            request_path = str(
                preview_payload.get("base_request") or "Not resolved"
            )
            output_root = state.output_root or "Not resolved"
            self._add_change_card(
                target="Authority paths bound by confirmation",
                before=(
                    f"Source root: {source_root}\n"
                    f"Request: {request_path}"
                ),
                after=f"Candidate parent: {output_root}",
                tooltip=(
                    "These normalized paths are visible before confirmation and "
                    "are bound into the immutable receipt."
                ),
            )

    def _add_change_card(
        self,
        *,
        target: str,
        before: str,
        after: str,
        tooltip: str,
    ) -> None:
        card = QtWidgets.QFrame(self.change_list)
        card.setObjectName("assistantChangeCard")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(10, 9, 10, 10)
        card_layout.setSpacing(5)
        target_label = QtWidgets.QLabel(target)
        target_label.setObjectName("assistantChangeTarget")
        target_label.setWordWrap(True)
        target_label.setToolTip(tooltip)
        _allow_horizontal_shrink(target_label)
        card_layout.addWidget(target_label)
        self._add_diff_value(card_layout, "Before", before, after=False)
        self._add_diff_value(card_layout, "After", after, after=True)
        self.change_list_layout.addWidget(card)

    def _clear_preview_cards(self) -> None:
        self.change_count = 0
        while self.change_list_layout.count():
            item = self.change_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _add_diff_value(
        layout: QtWidgets.QVBoxLayout,
        label: str,
        value: str,
        *,
        after: bool,
    ) -> None:
        heading = QtWidgets.QLabel(label)
        heading.setObjectName("assistantDiffLabel")
        layout.addWidget(heading)
        value_label = QtWidgets.QLabel(value)
        value_label.setObjectName(
            "assistantDiffAfter" if after else "assistantDiffValue"
        )
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        value_label.setToolTip(value)
        _allow_horizontal_shrink(value_label)
        layout.addWidget(value_label)

    def _refresh_chip_style(self) -> None:
        style = self.state_chip.style()
        style.unpolish(self.state_chip)
        style.polish(self.state_chip)

    def _sync_actions(self) -> None:
        transaction = self._transaction
        record = self._request_record
        running = record is not None and record.provider_running
        pending = transaction is not None and transaction.pending_batch is not None
        active = transaction is not None and transaction.status == "active"
        paused = transaction is not None and transaction.status == "paused"
        applying = bool(
            transaction is not None and transaction.applying_batch_id is not None
        )
        mapping_state = record.parsed_mapping_state if record is not None else None
        mapping_pending = bool(
            record is not None
            and record.status == "proposal_ready"
            and mapping_state is not None
            and mapping_state.status != "rejected"
        )
        unresolved_non_canvas = bool(
            record is not None
            and record.status
            in {"proposal_ready", "needs_human_confirmation", "needs_rule_repair"}
            and not pending
            and not mapping_pending
        )
        request_resolved = record is None or record.status in {
            "applied",
            "rejected",
            "cancelled",
            "failed",
            "interrupted",
        }
        can_compose = bool(
            self._provider is not None
            and not self._busy
            and not running
            and not pending
            and not mapping_pending
            and not unresolved_non_canvas
            and (transaction is None or active)
            and request_resolved
        )
        self.composer_card.setVisible(can_compose)
        if self._provider is not None:
            self.connected_provider_label.setText(self._provider.display_name)
            provider_tooltip = f"Provider ID: {self._provider.provider_id}"
            if self._provider.model_label:
                provider_tooltip += f"\nModel: {self._provider.model_label}"
            self.connected_provider_label.setToolTip(provider_tooltip)
        else:
            self.connected_provider_label.clear()
            self.connected_provider_label.setToolTip("")
        send_role = (
            "assistantPrimaryButton"
            if transaction is None
            else "assistantSecondaryButton"
        )
        if self.send_button.objectName() != send_role:
            self.send_button.setObjectName(send_role)
            style = self.send_button.style()
            style.unpolish(self.send_button)
            style.polish(self.send_button)
        self.request_editor.setEnabled(can_compose)
        self.send_button.setEnabled(
            can_compose and bool(self.request_editor.toPlainText().strip())
        )

        has_transaction_actions = transaction is not None and not running
        self.action_bar.setVisible(has_transaction_actions)
        self.proposal_action_widget.setVisible(bool(pending or mapping_pending))
        mapping_executed = bool(
            mapping_pending
            and mapping_state is not None
            and mapping_state.status == "executed"
        )
        self.reject_button.setVisible(not mapping_executed)
        self.turn_action_widget.setVisible(
            bool(not pending and not mapping_pending and not unresolved_non_canvas)
        )
        self.safety_action_widget.setVisible(has_transaction_actions)
        enabled = not self._busy and transaction is not None
        if mapping_pending and mapping_state is not None:
            mapping_labels = {
                "proposed": "Locate Sources",
                "source_required": "Choose Source Folder",
                "previewing": "Checking Sources…",
                "preview_ready": "Confirm and Build Project",
                "confirmed": "Resume Build",
                "executing": "Building Project…",
                "executed": "Open Mapped Canvas",
            }
            self.accept_button.setText(
                mapping_labels.get(mapping_state.status, "Continue")
            )
        else:
            self.accept_button.setText("Accept and Apply")
        mapping_accept_ready = bool(
            mapping_pending
            and mapping_state is not None
            and mapping_state.status
            in {"proposed", "source_required", "preview_ready", "confirmed", "executed"}
        )
        self.accept_button.setEnabled(
            enabled
            and not self._mapping_active
            and ((active and pending and not applying) or mapping_accept_ready)
        )
        self.reject_button.setEnabled(
            enabled
            and not self._mapping_active
            and (
                ((active or paused) and pending and not applying)
                or (mapping_pending and not mapping_executed)
            )
        )
        self.undo_button.setEnabled(
            enabled
            and active
            and not pending
            and not applying
            and self._can_undo
            and not unresolved_non_canvas
        )
        self.commit_button.setEnabled(
            enabled
            and (active or paused)
            and not pending
            and not applying
            and not unresolved_non_canvas
        )
        conflict = transaction is not None and transaction.status == "conflict"
        self.pause_button.setVisible(
            not conflict and not unresolved_non_canvas and not mapping_pending
        )
        self.pause_button.setText("Resume Turn" if paused else "Pause Turn")
        self.pause_button.setEnabled(
            enabled
            and not applying
            and (active or paused)
            and not unresolved_non_canvas
        )
        self.rollback_button.setEnabled(
            enabled and not applying and not self._mapping_active
        )


__all__ = ["AssistantTransactionPanel"]
