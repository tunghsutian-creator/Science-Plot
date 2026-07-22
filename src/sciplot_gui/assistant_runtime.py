from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import cast

from PyQt6 import QtCore

from sciplot_core.assistant_provider import (
    AssistantCancellationToken,
    AssistantCancelled,
    AssistantProgressEvent,
    AssistantProvider,
    AssistantProviderDescriptor,
    AssistantRequest,
    AssistantResponse,
)

_AUTO_ASSISTANT_PROVIDER = object()


def resolve_assistant_provider(
    assistant_provider: AssistantProvider | None | object = _AUTO_ASSISTANT_PROVIDER,
    *,
    environ: Mapping[str, str] | None = None,
) -> AssistantProvider | None:
    """Resolve the optional provider without importing a standalone app."""

    if assistant_provider is not _AUTO_ASSISTANT_PROVIDER:
        return cast(AssistantProvider | None, assistant_provider)
    from sciplot_core.openai_provider import load_openai_provider_from_environment

    try:
        return load_openai_provider_from_environment(environ)
    except ValueError as exc:
        warnings.warn(
            "SciPlot is continuing without its optional AI assistant because "
            f"the provider configuration is invalid: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


class _AssistantProviderWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(object)
    response = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()

    def __init__(
        self,
        *,
        provider: AssistantProvider,
        descriptor: AssistantProviderDescriptor,
        request: AssistantRequest,
        cancellation: AssistantCancellationToken,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._descriptor = AssistantProviderDescriptor.from_dict(
            descriptor.to_dict()
        )
        self._request = request
        self._cancellation = cancellation
        self._last_sequence = 0

    def _emit_progress(self, event: AssistantProgressEvent) -> None:
        restored = AssistantProgressEvent.from_dict(event.to_dict())
        if restored.request_id != self._request.request_id:
            raise ValueError("Provider progress request_id does not match request.")
        if restored.provider_id != self._request.provider_id:
            raise ValueError("Provider progress provider_id does not match request.")
        if restored.sequence != self._last_sequence + 1:
            raise ValueError("Provider progress events must be contiguous and ordered.")
        if restored.cancellable and not self._descriptor.supports_cancellation:
            raise ValueError(
                "Provider progress cannot advertise cancellation when the "
                "descriptor does not support it."
            )
        self._last_sequence = restored.sequence
        self.progress.emit(restored)

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            descriptor = AssistantProviderDescriptor.from_dict(
                self._provider.descriptor.to_dict()
            )
            if descriptor.to_dict() != self._descriptor.to_dict():
                raise ValueError("Provider descriptor changed after request submission.")
            if self._descriptor.provider_id != self._request.provider_id:
                raise ValueError("Provider descriptor does not match Assistant request.")
            self._cancellation.raise_if_cancelled()
            provider_request = AssistantRequest.from_dict(
                self._request.to_dict()
            )
            response = self._provider.generate(
                provider_request,
                emit_progress=self._emit_progress,
                cancellation=self._cancellation,
            )
            restored = (
                AssistantResponse.from_dict(response)
                if isinstance(response, dict)
                else AssistantResponse.from_dict(response.to_dict())
            )
            restored.validate_for_request(self._request)
            if self._cancellation.cancelled and restored.status != "cancelled":
                restored = AssistantResponse(
                    request_id=self._request.request_id,
                    transaction_id=self._request.transaction_id,
                    provider_id=self._request.provider_id,
                    request_sha256=self._request.payload_sha256,
                    status="cancelled",
                    understanding="Stopped before the provider result was accepted.",
                    warnings=(
                        "The provider returned after cancellation; its result was discarded.",
                    ),
                )
            self.response.emit(restored)
        except AssistantCancelled:
            self.response.emit(
                AssistantResponse(
                    request_id=self._request.request_id,
                    transaction_id=self._request.transaction_id,
                    provider_id=self._request.provider_id,
                    request_sha256=self._request.payload_sha256,
                    status="cancelled",
                    understanding="Stopped at the user's request.",
                )
            )
        except Exception as exc:
            self.failed.emit(
                {
                    "request_id": self._request.request_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        finally:
            self.finished.emit()


class AssistantRequestRunner(QtCore.QObject):
    """Run one injected provider off the GUI thread with cooperative stop."""

    progress = QtCore.pyqtSignal(object)
    response = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(object)
    activeChanged = QtCore.pyqtSignal(bool)

    def __init__(
        self,
        provider: AssistantProvider | None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._descriptor = (
            AssistantProviderDescriptor.from_dict(provider.descriptor.to_dict())
            if provider is not None
            else None
        )
        self._thread: QtCore.QThread | None = None
        self._worker: _AssistantProviderWorker | None = None
        self._cancellation: AssistantCancellationToken | None = None
        self._request: AssistantRequest | None = None

    @property
    def descriptor(self) -> AssistantProviderDescriptor | None:
        return self._descriptor

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @property
    def request(self) -> AssistantRequest | None:
        return (
            AssistantRequest.from_dict(self._request.to_dict())
            if self._request is not None
            else None
        )

    def submit(self, request: AssistantRequest) -> None:
        if self._provider is None or self._descriptor is None:
            raise RuntimeError("No Assistant provider is connected.")
        if self.active or self._thread is not None:
            raise RuntimeError("An Assistant provider request is already active.")
        restored = AssistantRequest.from_dict(request.to_dict())
        if restored.provider_id != self._descriptor.provider_id:
            raise ValueError("Assistant request does not target the connected provider.")
        unsupported = set(restored.allowed_proposal_kinds) - set(
            self._descriptor.proposal_kinds
        )
        if unsupported:
            raise ValueError(
                f"Assistant request asks for unsupported proposal kinds: {sorted(unsupported)!r}"
            )
        cancellation = AssistantCancellationToken()
        thread = QtCore.QThread(self)
        thread.setObjectName(f"assistant-provider-{restored.request_id}")
        worker = _AssistantProviderWorker(
            provider=self._provider,
            descriptor=self._descriptor,
            request=restored,
            cancellation=cancellation,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.response.connect(self.response)
        worker.failed.connect(self.failed)
        worker.finished.connect(
            thread.quit,
            QtCore.Qt.ConnectionType.DirectConnection,
        )
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._request = restored
        self._cancellation = cancellation
        self._thread = thread
        self._worker = worker
        self.activeChanged.emit(True)
        thread.start()

    def cancel(self) -> None:
        if self._cancellation is None or not self.active:
            raise RuntimeError("No Assistant provider request is running.")
        if self._descriptor is not None and not self._descriptor.supports_cancellation:
            raise RuntimeError("The connected Assistant provider cannot be stopped.")
        self._cancellation.cancel()

    @QtCore.pyqtSlot()
    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._cancellation = None
        self._request = None
        self.activeChanged.emit(False)

    def shutdown(self, *, wait_ms: int = 3000) -> bool:
        thread = self._thread
        if thread is None:
            return True
        if self._cancellation is not None:
            self._cancellation.cancel()
        return bool(thread.wait(max(int(wait_ms), 0)))


__all__ = ["AssistantRequestRunner", "resolve_assistant_provider"]
