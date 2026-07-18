from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore

from sciplot_core.canvas.assistant_contract import (
    DataMappingConfirmation,
    DataMappingProposal,
)
from sciplot_core.data_mapping import (
    execute_data_mapping_proposal,
    preview_data_mapping_proposal,
)
from sciplot_gui.workspace import resolve_canvas_workspace


class _DataMappingWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(object)
    previewReady = QtCore.pyqtSignal(object)
    executionReady = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()

    def __init__(
        self,
        *,
        mode: str,
        proposal: DataMappingProposal,
        source_root: Path,
        request_path: Path,
        confirmation: DataMappingConfirmation | None = None,
        output_root: Path | None = None,
    ) -> None:
        super().__init__()
        if mode not in {"preview", "execute"}:
            raise ValueError(f"Unsupported data-mapping task mode: {mode!r}")
        self._mode = mode
        self._proposal = DataMappingProposal.from_dict(proposal.to_dict())
        self._source_root = source_root.expanduser().resolve()
        self._request_path = request_path.expanduser().resolve()
        self._confirmation = (
            DataMappingConfirmation.from_dict(confirmation.to_dict())
            if confirmation is not None
            else None
        )
        self._output_root = (
            output_root.expanduser().resolve() if output_root is not None else None
        )

    @property
    def mode(self) -> str:
        return self._mode

    def _progress(self, stage: str, message: str) -> None:
        self.progress.emit({"mode": self._mode, "stage": stage, "message": message})

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            if self._mode == "preview":
                self._progress(
                    "validating_sources",
                    "Verifying request and source hashes without writing files.",
                )
                preview = preview_data_mapping_proposal(
                    self._proposal,
                    source_root=self._source_root,
                    request_path=self._request_path,
                )
                self._progress(
                    "preview_ready",
                    "Deterministic preview is ready for your confirmation.",
                )
                self.previewReady.emit(preview)
                return

            if self._confirmation is None or self._output_root is None:
                raise RuntimeError(
                    "Confirmed data-mapping execution requires a receipt and output root."
                )
            self._progress(
                "executing_mapping",
                "Building an isolated mapped project; raw sources stay unchanged.",
            )
            execution = execute_data_mapping_proposal(
                self._proposal,
                self._confirmation,
                source_root=self._source_root,
                request_path=self._request_path,
                output_root=self._output_root,
            )
            self._progress(
                "preparing_canvas",
                "Preparing the verified candidate as an exact-current Canvas.",
            )
            workspace = resolve_canvas_workspace(Path(str(execution["output_root"])))
            self.executionReady.emit({"execution": execution, "workspace": workspace})
        except Exception as exc:
            self.failed.emit(
                {
                    "mode": self._mode,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        finally:
            self.finished.emit()


class DataMappingTaskRunner(QtCore.QObject):
    """Run deterministic preview/execution off the GUI thread."""

    progress = QtCore.pyqtSignal(object)
    previewReady = QtCore.pyqtSignal(object)
    executionReady = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(object)
    activeChanged = QtCore.pyqtSignal(bool)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QtCore.QThread | None = None
        self._worker: _DataMappingWorker | None = None
        self._mode: str | None = None

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @property
    def mode(self) -> str | None:
        return self._mode

    def submit_preview(
        self,
        *,
        proposal: DataMappingProposal,
        source_root: Path,
        request_path: Path,
    ) -> None:
        self._submit(
            _DataMappingWorker(
                mode="preview",
                proposal=proposal,
                source_root=source_root,
                request_path=request_path,
            )
        )

    def submit_execution(
        self,
        *,
        proposal: DataMappingProposal,
        confirmation: DataMappingConfirmation,
        source_root: Path,
        request_path: Path,
        output_root: Path,
    ) -> None:
        self._submit(
            _DataMappingWorker(
                mode="execute",
                proposal=proposal,
                confirmation=confirmation,
                source_root=source_root,
                request_path=request_path,
                output_root=output_root,
            )
        )

    def _submit(self, worker: _DataMappingWorker) -> None:
        if self.active or self._thread is not None:
            raise RuntimeError("A deterministic data-mapping task is already active.")
        thread = QtCore.QThread(self)
        self._mode = worker.mode
        thread.setObjectName(f"data-mapping-{self._mode}")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.previewReady.connect(self.previewReady)
        worker.executionReady.connect(self.executionReady)
        worker.failed.connect(self.failed)
        worker.finished.connect(
            thread.quit,
            QtCore.Qt.ConnectionType.DirectConnection,
        )
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self.activeChanged.emit(True)
        thread.start()

    @QtCore.pyqtSlot()
    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._mode = None
        self.activeChanged.emit(False)

    def shutdown(self, *, wait_ms: int = 30_000) -> bool:
        thread = self._thread
        if thread is None:
            return True
        return bool(thread.wait(max(int(wait_ms), 0)))


__all__ = ["DataMappingTaskRunner"]
