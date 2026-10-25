"""Own request transport resources and decode bounded Responses results."""

from __future__ import annotations

import http.client
import socket
import threading
from dataclasses import dataclass
from types import TracebackType
from typing import Any

from sciplot_core.assistant_provider import AssistantCancellationToken
from sciplot_core.openai_provider.errors import OpenAIProviderError

from sciplot_core.openai_provider.validation import (
    _redact,
)


@dataclass(frozen=True)
class _StreamResult:
    text: str = ""
    refusal: str | None = None
    incomplete_reason: str | None = None


class _StreamTransport:
    """Own one request's I/O interruption, response, connection and monitor."""

    def __init__(self, connection: Any, cancellation: AssistantCancellationToken,
                 *, secret: str) -> None:
        self.connection = connection
        self.response: Any = None
        self._socket: Any = None
        self._cancellation = cancellation
        self._secret = secret
        self._stop = threading.Event()
        self._monitor = threading.Thread(target=self._interrupt_on_cancel,
                                         name="sciplot-openai-cancel-monitor", daemon=True)

    def __enter__(self) -> _StreamTransport:
        try:
            self._monitor.start()
        except BaseException:
            self._close_resources()
            raise
        return self

    def connected(self) -> None:
        # HTTPConnection may detach a will-close response from its socket.
        # Retain the connected socket so cancellation can still interrupt it.
        self._socket = self.connection.sock

    def _interrupt_on_cancel(self) -> None:
        while not self._stop.wait(0.05):
            if not self._cancellation.cancelled:
                continue
            active_socket = self._socket
            if active_socket is None:
                active_socket = getattr(self.connection, "sock", None)
            if active_socket is None:
                continue
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            # Only interrupt I/O here. The caller disposes both HTTP resources
            # after I/O unwinds, so cancellation cannot race their close methods.
            return

    def _close_resources(self) -> Exception | None:
        error = None
        for resource in (self.response, self.connection):
            close = getattr(resource, "close", None)
            if close is not None:
                try:
                    close()
                except Exception as exc:
                    if error is None:
                        error = exc
        return error

    def __exit__(self, exc_type: type[BaseException] | None,
                 _exc: BaseException | None, _tb: TracebackType | None) -> None:
        self._stop.set()
        self._monitor.join()
        cleanup_error = self._close_resources()
        if exc_type is not None:
            return
        self._cancellation.raise_if_cancelled()
        if cleanup_error is not None:
            safe = _redact(cleanup_error, secrets=(self._secret,))
            raise OpenAIProviderError(
                f"OpenAI Responses cleanup failed: {type(cleanup_error).__name__}: {safe}"
            ) from None


def _error_message(payload: object, *, status: int, secret: str) -> str:
    message = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            raw_message = error.get("message")
            raw_code = error.get("code") or error.get("type")
            if isinstance(raw_message, str):
                message = raw_message
            if isinstance(raw_code, str) and raw_code:
                message = f"{raw_code}: {message}" if message else raw_code
    safe = _redact(message, secrets=(secret,)) if message else ""
    suffix = f": {safe}" if safe else "."
    return f"OpenAI Responses API returned HTTP {status}{suffix}"


def _response_content(response: object) -> tuple[str, str | None]:
    if not isinstance(response, dict):
        return "", None
    texts: list[str] = []
    refusal: str | None = None
    output = response.get("output")
    if not isinstance(output, list):
        return "", None
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "output_text" and isinstance(part.get("text"), str):
                texts.append(str(part["text"]))
            elif part_type == "refusal" and isinstance(part.get("refusal"), str):
                refusal = str(part["refusal"])
    return "".join(texts), refusal


def _connection(
    scheme: str,
    host: str,
    port: int | None,
    timeout: float,
) -> http.client.HTTPConnection:
    connection_class = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    return connection_class(host, port=port, timeout=timeout)
