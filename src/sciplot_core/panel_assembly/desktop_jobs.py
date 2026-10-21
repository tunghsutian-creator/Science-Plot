"""Bounded background work for the native assembly presentation."""

from PyQt6 import QtCore


class AssemblyJob(QtCore.QThread):
    succeeded = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            self.failed.emit(f"{code}: {exc}")
        else:
            self.succeeded.emit(result)
