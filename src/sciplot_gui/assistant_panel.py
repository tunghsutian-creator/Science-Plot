from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtWidgets

from sciplot_core.canvas.model import CanvasTransaction


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


class AssistantTransactionPanel(QtWidgets.QWidget):
    """Compact review surface for provider-neutral Canvas transactions."""

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
            "Review typed AI proposals, pause, accept, reject, undo, commit, "
            "or roll back the complete turn."
        )
        self._transaction: CanvasTransaction | None = None
        self._busy = False
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
        content = QtWidgets.QWidget(scroll)
        content.setObjectName("assistantContent")
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QtWidgets.QHBoxLayout()
        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(2)
        title = QtWidgets.QLabel("Assistant")
        title.setObjectName("inspectorTitle")
        subtitle = QtWidgets.QLabel(
            "Typed proposals on the exact-current Canvas"
        )
        subtitle.setObjectName("inspectorContext")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        self.state_chip = QtWidgets.QLabel("Idle")
        self.state_chip.setObjectName("assistantStateChip")
        self.state_chip.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
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
            "without a provider. When connected, an assistant can submit only "
            "a validated DataMappingProposal or CanvasOperationBatch."
        )
        empty_copy.setObjectName("assistantBody")
        empty_copy.setWordWrap(True)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_copy)
        self.empty_card = empty
        layout.addWidget(empty)

        summary = QtWidgets.QFrame()
        summary.setObjectName("assistantCard")
        summary_layout = QtWidgets.QVBoxLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(8)
        summary_title = QtWidgets.QLabel("Current turn")
        summary_title.setObjectName("assistantCardTitle")
        summary_layout.addWidget(summary_title)
        self.provider_label = QtWidgets.QLabel()
        self.provider_label.setObjectName("assistantMeta")
        self.provider_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.revision_label = QtWidgets.QLabel()
        self.revision_label.setObjectName("assistantMeta")
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
        context_title = QtWidgets.QLabel("Bounded context")
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

        proposal = QtWidgets.QFrame()
        proposal.setObjectName("assistantProposalCard")
        proposal_layout = QtWidgets.QVBoxLayout(proposal)
        proposal_layout.setContentsMargins(14, 12, 14, 12)
        proposal_layout.setSpacing(8)
        proposal_header = QtWidgets.QHBoxLayout()
        proposal_title = QtWidgets.QLabel("Proposed changes")
        proposal_title.setObjectName("assistantCardTitle")
        self.operation_count = QtWidgets.QLabel()
        self.operation_count.setObjectName("assistantMeta")
        proposal_header.addWidget(proposal_title)
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
        proposal_actions = QtWidgets.QHBoxLayout()
        proposal_actions.setSpacing(8)
        self.reject_button = QtWidgets.QPushButton("Reject Proposal")
        self.reject_button.setObjectName("assistantSecondaryButton")
        self.accept_button = QtWidgets.QPushButton("Accept & Apply")
        self.accept_button.setObjectName("assistantPrimaryButton")
        proposal_actions.addWidget(self.reject_button)
        proposal_actions.addWidget(self.accept_button, 1)
        action_layout.addLayout(proposal_actions)

        turn_actions = QtWidgets.QHBoxLayout()
        turn_actions.setSpacing(8)
        self.pause_button = QtWidgets.QPushButton("Pause")
        self.pause_button.setObjectName("assistantSecondaryButton")
        self.undo_button = QtWidgets.QPushButton("Undo Batch")
        self.undo_button.setObjectName("assistantSecondaryButton")
        self.commit_button = QtWidgets.QPushButton("Commit Turn")
        self.commit_button.setObjectName("assistantPrimaryButton")
        turn_actions.addWidget(self.pause_button)
        turn_actions.addWidget(self.undo_button)
        turn_actions.addWidget(self.commit_button, 1)
        action_layout.addLayout(turn_actions)

        self.rollback_button = QtWidgets.QPushButton("Roll Back Entire Turn")
        self.rollback_button.setObjectName("assistantDangerButton")
        action_layout.addWidget(self.rollback_button)
        root.addWidget(actions)
        self.action_bar = actions

        self.pause_button.clicked.connect(self._pause_or_resume)
        self.accept_button.clicked.connect(self.acceptRequested)
        self.reject_button.clicked.connect(self.rejectProposalRequested)
        self.undo_button.clicked.connect(self.undoBatchRequested)
        self.commit_button.clicked.connect(self.commitRequested)
        self.rollback_button.clicked.connect(self.rollbackRequested)

    def _pause_or_resume(self) -> None:
        transaction = self._transaction
        if transaction is None:
            return
        if transaction.status == "paused":
            self.resumeRequested.emit()
        else:
            self.pauseRequested.emit()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_actions()

    def set_transaction(
        self,
        transaction: CanvasTransaction | None,
        *,
        context: dict[str, Any],
        can_undo: bool,
    ) -> None:
        self._transaction = transaction
        self._can_undo = bool(can_undo)
        active = transaction is not None
        self.empty_card.setVisible(not active)
        self.summary_card.setVisible(active)
        self.context_card.setVisible(active)
        self.proposal_card.setVisible(
            active and transaction.pending_preview is not None
        )
        self.action_bar.setVisible(active)
        if transaction is None:
            self.state_chip.setText("Idle")
            self.state_chip.setProperty("assistantState", "idle")
            self.status_copy.setText(
                "No provider is connected and no transaction is active."
            )
            self._clear_preview_cards()
            self._refresh_chip_style()
            self._sync_actions()
            return

        status = transaction.status
        if transaction.applying_batch_id:
            state_text = "Applying"
            state_key = "applying"
        elif status == "paused":
            state_text = "Paused"
            state_key = "paused"
        elif status == "conflict":
            state_text = "Conflict"
            state_key = "conflict"
        elif transaction.pending_batch is not None:
            state_text = "Proposal"
            state_key = "proposal"
        else:
            state_text = "Ready"
            state_key = "active"
        self.state_chip.setText(state_text)
        self.state_chip.setProperty("assistantState", state_key)
        self.provider_label.setText(f"Provider · {transaction.provider}")
        self.revision_label.setText(
            f"Baseline r{transaction.base_revision} · "
            f"Current r{transaction.current_revision} · "
            f"{len(transaction.active_batch_ids)} active batch"
            + ("" if len(transaction.active_batch_ids) == 1 else "es")
        )
        self.rationale_label.setText(transaction.rationale)

        selected = context.get("selected_object")
        if isinstance(selected, dict):
            self.selection_label.setText(
                f"Selection · {selected.get('object_type', 'object')} · "
                f"{selected.get('display_name') or selected.get('path') or 'Unnamed'}"
            )
        else:
            self.selection_label.setText("Selection · none")
        inventory = context.get("document_inventory")
        review = context.get("review")
        structural = context.get("structural_qa")
        object_count = (
            int(inventory.get("object_count") or 0)
            if isinstance(inventory, dict)
            else 0
        )
        review_count = (
            int(review.get("active_count") or 0)
            if isinstance(review, dict)
            else 0
        )
        qa_status = (
            str(structural.get("status") or "not run")
            if isinstance(structural, dict)
            else "not run"
        )
        self.context_label.setText(
            f"{object_count} document objects · {review_count} review marks · "
            f"structural QA {qa_status} · raw dataset values excluded"
        )
        self._set_preview(transaction.pending_preview)

        if status == "paused":
            self.status_copy.setText(
                "The assistant is paused. The document is locked against "
                "untracked edits until you resume, commit, or roll back."
            )
        elif status == "conflict":
            self.status_copy.setText(
                "The transaction no longer matches the exact-current revision. "
                "Inspect the evidence and roll back to the verified baseline."
            )
        elif transaction.pending_batch is not None:
            self.status_copy.setText(
                "Review this closed-schema proposal. Nothing changes until "
                "you choose Accept & Apply."
            )
        else:
            self.status_copy.setText(
                "Accepted batches are visible on the live Canvas. Commit keeps "
                "them; whole-turn rollback restores the exact baseline."
            )
        self._refresh_chip_style()
        self._sync_actions()

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
            card = QtWidgets.QFrame(self.change_list)
            card.setObjectName("assistantChangeCard")
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(10, 9, 10, 10)
            card_layout.setSpacing(5)
            target_label = QtWidgets.QLabel(target)
            target_label.setObjectName("assistantChangeTarget")
            target_label.setWordWrap(True)
            target_label.setToolTip(tooltip)
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
        layout.addWidget(value_label)

    def _refresh_chip_style(self) -> None:
        style = self.state_chip.style()
        style.unpolish(self.state_chip)
        style.polish(self.state_chip)

    def _sync_actions(self) -> None:
        transaction = self._transaction
        if transaction is None:
            return
        applying = transaction.applying_batch_id is not None
        active = transaction.status == "active"
        paused = transaction.status == "paused"
        pending = transaction.pending_batch is not None
        enabled = not self._busy and transaction.status != "conflict"
        self.pause_button.setText("Resume" if paused else "Pause")
        self.pause_button.setEnabled(
            enabled and not applying and (active or paused)
        )
        self.accept_button.setEnabled(enabled and active and pending and not applying)
        self.reject_button.setEnabled(
            enabled and (active or paused) and pending and not applying
        )
        self.undo_button.setEnabled(
            enabled
            and active
            and not pending
            and not applying
            and self._can_undo
        )
        self.commit_button.setEnabled(
            enabled and (active or paused) and not pending and not applying
        )
        self.rollback_button.setEnabled(not self._busy and not applying)


__all__ = ["AssistantTransactionPanel"]
