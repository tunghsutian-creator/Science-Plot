"""Compose the native Veusz assistant dock from focused interaction facets."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from PyQt6 import QtCore
from sciplot_core.assistant_operations import VeuszSettingOperationBatch
from sciplot_core.assistant_provider import (
    AssistantProvider,
    AssistantRequest,
    AssistantResponse,
)
from sciplot_gui.assistant_runtime import (
    AssistantRequestRunner,
    resolve_assistant_provider as _default_provider_resolver,
)
from sciplot_gui.studio_assistant_history import (
    assistant_history_path,
)
from sciplot_gui.studio_assistant.context_history import ContextHistoryMixin
from sciplot_gui.studio_assistant.dock import DockMixin
from sciplot_gui.studio_assistant.selection import SelectionMixin
from sciplot_gui.studio_assistant.request_context import RequestContextMixin
from sciplot_gui.studio_assistant.request_flow import RequestFlowMixin
from sciplot_gui.studio_assistant.proposal_application import ProposalApplicationMixin
from sciplot_gui.studio_assistant.rejection import RejectionMixin


class StudioAssistantBridge(
    RejectionMixin,
    ProposalApplicationMixin,
    RequestFlowMixin,
    RequestContextMixin,
    SelectionMixin,
    DockMixin,
    ContextHistoryMixin,
    QtCore.QObject,
):
    """Bounded assistant over one existing Veusz MainWindow and Document."""

    requestSubmitted = QtCore.pyqtSignal(object)
    proposalReady = QtCore.pyqtSignal(object)
    proposalApplied = QtCore.pyqtSignal(object)
    requestRejected = QtCore.pyqtSignal(str)
    historyRecorded = QtCore.pyqtSignal(object)

    def __init__(
        self,
        window: Any,
        document_path: Path,
        *,
        provider: AssistantProvider | None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = window.document
        self.plot = window.plot
        self.document_path = document_path.expanduser().resolve()
        self.history_path = assistant_history_path(self.document_path)
        self.provider = provider
        self.runner = AssistantRequestRunner(provider, self)
        self._selected_widget: Any | None = None
        self._pending_request: AssistantRequest | None = None
        self._pending_response: AssistantResponse | None = None
        self._pending_batch: VeuszSettingOperationBatch | None = None
        self._pending_capabilities: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_render_sha256: str | None = None

        self.dock = self._build_dock()
        # SciPlot augments the native Veusz MainWindow; it must not claim space
        # or rearrange the user's established Veusz dock layout on startup.
        # The SciPlot menu exposes QDockWidget.toggleViewAction(), so the panel
        # remains one reversible, opt-in native dock when it is needed.
        self.dock.hide()
        self.window.addDockWidget(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
            self.dock,
        )
        self._connect_signals()
        self._refresh_selection_label()
        self._set_provider_state()


def attach_studio_assistant(
    window: Any,
    document_path: Path,
    *,
    provider: AssistantProvider | None = None,
    resolve_provider: bool = True,
    provider_resolver: Callable[
        [],
        AssistantProvider | None,
    ] = _default_provider_resolver,
) -> StudioAssistantBridge:
    existing = getattr(window, "_sciplot_assistant_bridge", None)
    if isinstance(existing, StudioAssistantBridge):
        return existing
    if provider is None and resolve_provider:
        provider = provider_resolver()
    bridge = StudioAssistantBridge(
        window,
        document_path,
        provider=provider,
    )
    window._sciplot_assistant_bridge = bridge
    return bridge
