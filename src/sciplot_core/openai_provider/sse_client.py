"""Stream one Responses API request over bounded SSE transport."""

from __future__ import annotations

import http.client
import json
import socket
import threading
from typing import Any, Callable
from sciplot_core.assistant_provider import (
    AssistantCancellationToken,
    AssistantCancelled,
)

from sciplot_core.openai_provider.contracts import (
    _MAX_STREAM_LINE_BYTES,
    _MAX_STREAM_EVENT_BYTES,
    _MAX_STREAM_TEXT_BYTES,
    _MAX_HTTP_ERROR_BYTES,
)

from sciplot_core.openai_provider.errors import (
    OpenAIProviderError,
)

from sciplot_core.openai_provider.validation import (
    _redact,
)

from sciplot_core.openai_provider.config import (
    OpenAIResponsesConfig,
)

from sciplot_core.openai_provider.transport_helpers import (
    _StreamResult,
    _error_message,
    _response_content,
    _connection,
)


class _ResponsesSSEClient:
    def __init__(
        self,
        config: OpenAIResponsesConfig,
        *,
        connection_factory: Callable[[str, str, int | None, float], Any] | None = None,
    ) -> None:
        self.config = config
        self._connection_factory = connection_factory or _connection

    def stream(
        self,
        payload: dict[str, Any],
        *,
        cancellation: AssistantCancellationToken,
        on_headers: Callable[[], None],
        on_text: Callable[[], None],
    ) -> _StreamResult:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        scheme, host, port, path = self.config.endpoint
        connection = self._connection_factory(
            scheme,
            host,
            port,
            self.config.timeout_seconds,
        )
        socket_holder: list[Any | None] = [None]
        monitor_stop = threading.Event()

        def close_on_cancel() -> None:
            while not monitor_stop.wait(0.05):
                if not cancellation.cancelled:
                    continue
                active_socket = socket_holder[0]
                if active_socket is not None:
                    try:
                        active_socket.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                    try:
                        active_socket.close()
                    except Exception:
                        pass
                else:
                    try:
                        connection.close()
                    except Exception:
                        pass
                return

        monitor = threading.Thread(
            target=close_on_cancel,
            name="sciplot-openai-cancel-monitor",
            daemon=True,
        )
        monitor.start()
        try:
            cancellation.raise_if_cancelled()
            connection.connect()
            socket_holder[0] = connection.sock
            cancellation.raise_if_cancelled()
            connection.request(
                "POST",
                path,
                body=encoded,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "User-Agent": "SciPlot/0.1 OpenAIResponsesProvider",
                },
            )
            response = connection.getresponse()
            cancellation.raise_if_cancelled()
            if response.status != 200:
                raw = response.read(_MAX_HTTP_ERROR_BYTES + 1)
                body: object = None
                if len(raw) <= _MAX_HTTP_ERROR_BYTES:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        body = None
                raise OpenAIProviderError(
                    _error_message(
                        body,
                        status=response.status,
                        secret=self.config.api_key,
                    )
                )
            content_type = str(response.getheader("Content-Type") or "")
            if "text/event-stream" not in content_type.casefold():
                raise OpenAIProviderError(
                    "OpenAI Responses API did not return an SSE stream."
                )
            on_headers()
            return self._read_events(
                response,
                cancellation=cancellation,
                on_text=on_text,
            )
        except AssistantCancelled:
            raise
        except OpenAIProviderError:
            raise
        except Exception as exc:
            if cancellation.cancelled:
                raise AssistantCancelled(
                    "Assistant request cancelled by the user."
                ) from exc
            safe = _redact(exc, secrets=(self.config.api_key,))
            raise OpenAIProviderError(
                f"OpenAI Responses request failed: {type(exc).__name__}: {safe}"
            ) from exc
        finally:
            monitor_stop.set()
            try:
                connection.close()
            finally:
                monitor.join(timeout=0.2)

    def _read_events(
        self,
        response: http.client.HTTPResponse,
        *,
        cancellation: AssistantCancellationToken,
        on_text: Callable[[], None],
    ) -> _StreamResult:
        event_name: str | None = None
        data_lines: list[str] = []
        text_parts: list[str] = []
        text_bytes = 0
        final_text: str | None = None
        refusal_parts: list[str] = []
        refusal_bytes = 0
        final_refusal: str | None = None
        incomplete_reason: str | None = None
        terminal = False
        text_announced = False
        event_data_bytes = 0

        def announce_text() -> None:
            nonlocal text_announced
            if not text_announced:
                text_announced = True
                on_text()

        def append_text(value: str) -> None:
            nonlocal text_bytes
            text_bytes += len(value.encode("utf-8"))
            if text_bytes > _MAX_STREAM_TEXT_BYTES:
                raise OpenAIProviderError(
                    "OpenAI structured output exceeded the SciPlot size bound."
                )
            text_parts.append(value)

            announce_text()

        def append_refusal(value: str) -> None:
            nonlocal refusal_bytes
            refusal_bytes += len(value.encode("utf-8"))
            if refusal_bytes > _MAX_STREAM_TEXT_BYTES:
                raise OpenAIProviderError(
                    "OpenAI refusal exceeded the SciPlot size bound."
                )
            refusal_parts.append(value)

        def dispatch() -> None:
            nonlocal event_name, data_lines, final_text, final_refusal
            nonlocal incomplete_reason, terminal, event_data_bytes
            if not data_lines:
                event_name = None
                event_data_bytes = 0
                return
            data = "\n".join(data_lines)
            current_event = event_name
            event_name = None
            data_lines = []
            event_data_bytes = 0
            if data == "[DONE]":
                return
            try:
                value = json.loads(data)
            except json.JSONDecodeError as exc:
                raise OpenAIProviderError(
                    "OpenAI SSE event contained invalid JSON."
                ) from exc
            if not isinstance(value, dict):
                raise OpenAIProviderError(
                    "OpenAI SSE event must contain a JSON object."
                )
            payload_type = value.get("type")
            if not isinstance(payload_type, str):
                payload_type = current_event
            if not isinstance(payload_type, str) or not payload_type:
                raise OpenAIProviderError("OpenAI SSE event has no type.")
            if current_event and current_event != payload_type:
                raise OpenAIProviderError(
                    "OpenAI SSE event header and payload type disagree."
                )
            if payload_type == "response.output_text.delta":
                delta = value.get("delta")
                if not isinstance(delta, str):
                    raise OpenAIProviderError("OpenAI output_text delta must be text.")
                append_text(delta)
            elif payload_type == "response.output_text.done":
                done_text = value.get("text")
                if not isinstance(done_text, str):
                    raise OpenAIProviderError(
                        "OpenAI output_text done event must contain text."
                    )
                if len(done_text.encode("utf-8")) > _MAX_STREAM_TEXT_BYTES:
                    raise OpenAIProviderError(
                        "OpenAI structured output exceeded the SciPlot size bound."
                    )
                final_text = done_text
                announce_text()
            elif payload_type == "response.refusal.delta":
                delta = value.get("delta")
                if isinstance(delta, str):
                    append_refusal(delta)
            elif payload_type == "response.refusal.done":
                refusal = value.get("refusal")
                if isinstance(refusal, str):
                    if len(refusal.encode("utf-8")) > _MAX_STREAM_TEXT_BYTES:
                        raise OpenAIProviderError(
                            "OpenAI refusal exceeded the SciPlot size bound."
                        )
                    final_refusal = refusal
            elif payload_type == "response.completed":
                completed = value.get("response")
                if not isinstance(completed, dict):
                    raise OpenAIProviderError(
                        "OpenAI completed event has no response object."
                    )
                if completed.get("status") != "completed":
                    raise OpenAIProviderError(
                        "OpenAI completed event has a non-completed status."
                    )
                content_text, content_refusal = _response_content(completed)
                if final_text is None and content_text:
                    if len(content_text.encode("utf-8")) > _MAX_STREAM_TEXT_BYTES:
                        raise OpenAIProviderError(
                            "OpenAI structured output exceeded the SciPlot size bound."
                        )
                    final_text = content_text
                    announce_text()
                if final_refusal is None and content_refusal:
                    final_refusal = content_refusal
                terminal = True
            elif payload_type == "response.incomplete":
                incomplete = value.get("response")
                details = (
                    incomplete.get("incomplete_details")
                    if isinstance(incomplete, dict)
                    else None
                )
                reason = details.get("reason") if isinstance(details, dict) else None
                incomplete_reason = (
                    str(reason) if isinstance(reason, str) and reason else "unknown"
                )
                terminal = True
            elif payload_type in {"response.failed", "error"}:
                error = value.get("error")
                if error is None and isinstance(value.get("response"), dict):
                    error = value["response"].get("error")
                message = (
                    error.get("message")
                    if isinstance(error, dict)
                    else value.get("message")
                )
                safe = _redact(message or "unknown provider error", secrets=())
                raise OpenAIProviderError(f"OpenAI response failed: {safe}")

        while True:
            cancellation.raise_if_cancelled()
            raw_line = response.readline(_MAX_STREAM_LINE_BYTES + 1)
            cancellation.raise_if_cancelled()
            if not raw_line:
                dispatch()
                break
            if len(raw_line) > _MAX_STREAM_LINE_BYTES:
                raise OpenAIProviderError("OpenAI SSE line exceeded the size bound.")
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise OpenAIProviderError("OpenAI SSE stream is not UTF-8.") from exc
            line = line.rstrip("\r\n")
            if not line:
                dispatch()
                if terminal:
                    break
                continue
            if line.startswith(":"):
                continue
            field_name, separator, raw_value = line.partition(":")
            field_value = (
                raw_value[1:] if separator and raw_value.startswith(" ") else raw_value
            )
            if field_name == "event":
                event_name = field_value
            elif field_name == "data":
                event_data_bytes += len(field_value.encode("utf-8"))
                if data_lines:
                    event_data_bytes += 1
                if event_data_bytes > _MAX_STREAM_EVENT_BYTES:
                    raise OpenAIProviderError(
                        "OpenAI SSE event exceeded the size bound."
                    )
                data_lines.append(field_value)

        if not terminal:
            raise OpenAIProviderError(
                "OpenAI SSE stream ended without a terminal response event."
            )
        refusal = final_refusal or ("".join(refusal_parts) or None)
        text = final_text if final_text is not None else "".join(text_parts)
        return _StreamResult(
            text=text,
            refusal=refusal,
            incomplete_reason=incomplete_reason,
        )
