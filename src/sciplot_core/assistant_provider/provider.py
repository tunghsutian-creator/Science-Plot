"""Define cancellation and provider protocol boundaries."""

from __future__ import annotations

import threading
from typing import Callable, Protocol

from sciplot_core.assistant_provider.descriptor import (
    AssistantProviderDescriptor,
)

from sciplot_core.assistant_provider.request import (
    AssistantRequest,
)

from sciplot_core.assistant_provider.progress import (
    AssistantProgressEvent,
)

from sciplot_core.assistant_provider.response import (
    AssistantResponse,
)


class AssistantCancelled(RuntimeError):
    """Raised by a provider when cooperative cancellation is observed."""


class AssistantCancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise AssistantCancelled("Assistant request cancelled by the user.")


AssistantProgressCallback = Callable[[AssistantProgressEvent], None]


class AssistantProvider(Protocol):
    @property
    def descriptor(self) -> AssistantProviderDescriptor: ...

    def generate(
        self,
        request: AssistantRequest,
        *,
        emit_progress: AssistantProgressCallback,
        cancellation: AssistantCancellationToken,
    ) -> AssistantResponse: ...
