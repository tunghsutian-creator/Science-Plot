"""Run project filesystem services without accessing a live Veusz document."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6 import QtCore, QtWidgets


class ProjectChangeWorker(QtCore.QThread):
    def __init__(
        self, operation: Callable[[], dict[str, Any]], parent: QtCore.QObject
    ) -> None:
        super().__init__(parent)
        self.operation = operation
        self.result: dict[str, Any] = {}

    def run(self) -> None:
        try:
            self.result = {"ok": True, "payload": self.operation()}
        except Exception as exc:
            self.result = {"ok": False, "message": f"{type(exc).__name__}: {exc}"}


class ProjectChangeProgress(QtWidgets.QProgressDialog):
    """Keep the native editor closed to input until the filesystem call returns."""

    def __init__(self, title: str, parent: QtWidgets.QWidget) -> None:
        super().__init__("Validating project files…", "", 0, 0, parent)
        self.setWindowTitle(title)
        self.setCancelButton(None)
        self.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumDuration(0)
        self._finished = False

    def reject(self) -> None:
        if self._finished:
            super().reject()

    def finish(self) -> None:
        self._finished = True
        self.close()


class ProjectChangeCloseGuard(QtCore.QObject):
    def __init__(self, parent: QtCore.QObject, busy: Callable[[], bool]) -> None:
        super().__init__(parent)
        self.busy = busy

    def eventFilter(
        self, watched: QtCore.QObject | None, event: QtCore.QEvent | None
    ) -> bool:
        if (
            event is not None
            and event.type() == QtCore.QEvent.Type.Close
            and self.busy()
        ):
            event.ignore()
            return True
        return False
