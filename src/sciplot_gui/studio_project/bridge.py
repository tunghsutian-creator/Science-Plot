"""Compose the native Veusz project dock from focused interaction facets."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from PyQt6 import QtCore, QtGui
from sciplot_gui.studio_project_status import (
    _validate_project_request_pair,
)
from sciplot_gui.studio_project.context import ContextMixin
from sciplot_gui.studio_project.dock import DockMixin
from sciplot_gui.studio_project.refresh import RefreshMixin
from sciplot_gui.studio_project.result_targets import ResultTargetsMixin
from sciplot_gui.studio_project.export_helpers import ExportHelpersMixin
from sciplot_gui.studio_project.export_action import ExportActionMixin
from sciplot_gui.studio_project.services import atomic_save_veusz_document


class StudioProjectBridge(
    ExportActionMixin,
    ExportHelpersMixin,
    ResultTargetsMixin,
    RefreshMixin,
    DockMixin,
    ContextMixin,
    QtCore.QObject,
):
    """Read-only SciPlot status and exact-current export on one Veusz window."""

    statusChanged = QtCore.pyqtSignal(object)
    exportFinished = QtCore.pyqtSignal(object)

    def __init__(
        self,
        window: Any,
        document_path: Path,
        *,
        project_dir: Path | None,
        request_path: Path | None,
        atomic_save_document: Callable[[Any, Path], dict[str, Any]] | None = None,
    ) -> None:
        _validate_project_request_pair(project_dir, request_path)
        super().__init__(window)
        self.window = window
        self.document = window.document
        self.plot = window.plot
        self.document_path = document_path.expanduser().resolve()
        self.project_dir = (
            project_dir.expanduser().resolve() if project_dir is not None else None
        )
        self.request_path = (
            request_path.expanduser().resolve() if request_path is not None else None
        )
        self._atomic_save_document = (
            atomic_save_document
            if atomic_save_document is not None
            else atomic_save_veusz_document
        )
        self.status_snapshot: dict[str, Any] = {}
        self._exporting = False
        self.export_action: QtGui.QAction | None = None
        self._bound_assistant_ids: set[int] = set()
        self.dock = self._build_dock()
        self.dock.hide()
        self.window.addDockWidget(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea,
            self.dock,
        )
        self.document.signalModified.connect(self._document_modified)
        self.dock.visibilityChanged.connect(self._dock_visibility_changed)
        self.refresh_button.clicked.connect(self.refresh_full)
        self.export_button.clicked.connect(self.export_current_document)
        self.figure_list.itemDoubleClicked.connect(
            lambda _item: self.open_selected_figure()
        )
        self.figure_list.currentItemChanged.connect(self._figure_selection_changed)
        self.open_figure_button.clicked.connect(self.open_selected_figure)
        self.open_pdf_button.clicked.connect(self.open_current_pdf)
        self.show_delivery_button.clicked.connect(self.show_current_delivery)
        self.reveal_vsz_button.clicked.connect(self.reveal_current_vsz)
        self.refresh()


def attach_studio_project(
    window: Any,
    document_path: Path,
    *,
    project_dir: Path | None = None,
    request_path: Path | None = None,
    atomic_save_document: Callable[[Any, Path], dict[str, Any]] | None = None,
) -> StudioProjectBridge:
    _validate_project_request_pair(project_dir, request_path)
    existing = getattr(window, "_sciplot_project_bridge", None)
    if isinstance(existing, StudioProjectBridge):
        return existing
    bridge = StudioProjectBridge(
        window,
        document_path,
        project_dir=project_dir,
        request_path=request_path,
        atomic_save_document=atomic_save_document,
    )
    window._sciplot_project_bridge = bridge
    return bridge
