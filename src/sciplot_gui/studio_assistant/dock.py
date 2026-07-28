"""Build the assistant dock and synchronize its provider controls."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets


class DockMixin:
    def _build_dock(self) -> QtWidgets.QDockWidget:
        dock = QtWidgets.QDockWidget("SciPlot AI", self.window)
        dock.setObjectName("sciplotStudioAssistantDock")
        dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        body = QtWidgets.QWidget(dock)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.intro_label = QtWidgets.QLabel(
            "AI inspects the exact-current rendered page for context. It can "
            "propose changes only to the selected object's supported properties."
        )
        self.intro_label.setWordWrap(True)
        layout.addWidget(self.intro_label)

        self.selection_label = QtWidgets.QLabel()
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)

        self.intent_edit = QtWidgets.QPlainTextEdit()
        self.intent_edit.setPlaceholderText(
            "Example: make the selected axis label easier to read."
        )
        self.intent_edit.setMaximumHeight(110)
        layout.addWidget(self.intent_edit)

        self.auto_apply = QtWidgets.QCheckBox(
            "Apply a safe, current proposal immediately"
        )
        self.auto_apply.setChecked(False)
        self.auto_apply.setToolTip(
            "Every change remains one native Veusz Undo step. A stale response "
            "is rejected instead of being applied."
        )
        layout.addWidget(self.auto_apply)

        request_row = QtWidgets.QHBoxLayout()
        self.ask_button = QtWidgets.QPushButton("Suggest Changes for Selected Object")
        self.cancel_button = QtWidgets.QPushButton("Stop")
        self.cancel_button.setEnabled(False)
        request_row.addWidget(self.ask_button, 1)
        request_row.addWidget(self.cancel_button)
        layout.addLayout(request_row)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

        self.proposal_view = QtWidgets.QPlainTextEdit()
        self.proposal_view.setReadOnly(True)
        self.proposal_view.setPlaceholderText(
            "The AI's bounded proposal and applied changes appear here."
        )
        layout.addWidget(self.proposal_view, 1)

        decision_row = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton("Apply Proposal")
        self.reject_button = QtWidgets.QPushButton("Reject")
        self.apply_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        decision_row.addWidget(self.apply_button)
        decision_row.addWidget(self.reject_button)
        layout.addLayout(decision_row)

        dock.setWidget(body)
        return dock

    def _connect_signals(self) -> None:
        self.window.treeedit.widgetsSelected.connect(self._widgets_selected)
        self.plot.sigWidgetClicked.connect(self._plot_widget_clicked)
        self.ask_button.clicked.connect(self._ask_from_ui)
        self.cancel_button.clicked.connect(self._cancel_request)
        self.apply_button.clicked.connect(self.accept_pending)
        self.reject_button.clicked.connect(self.reject_pending)
        self.runner.progress.connect(self._provider_progress)
        self.runner.response.connect(self._provider_response)
        self.runner.failed.connect(self._provider_failed)
        self.runner.activeChanged.connect(self._runner_active_changed)
        self.window.destroyed.connect(self._shutdown)

    def _set_provider_state(self) -> None:
        if self.provider is None:
            self.status_label.setText(
                "No OpenAI Assistant is connected. Veusz editing remains fully "
                "available; set OPENAI_API_KEY to enable visual AI edits."
            )
            self._refresh_ask_button()
            return
        descriptor = self.runner.descriptor
        label = descriptor.display_name if descriptor is not None else "Assistant"
        self.status_label.setText(
            f"{label} is ready. Select an object in the plot or object tree."
        )
        self._refresh_ask_button()

    def _refresh_ask_button(self) -> None:
        try:
            context_blocker = self._document_context_blocker()
            self.ask_button.setEnabled(
                self.provider is not None
                and self._selected_widget is not None
                and not self.runner.active
                and context_blocker is None
            )
            self.ask_button.setToolTip(context_blocker or "")
        except RuntimeError:
            # Child widgets can already be gone while the native MainWindow is
            # completing destruction.
            pass
