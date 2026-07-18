from __future__ import annotations

import http.client
import ipaddress
import json
import math
import os
import re
import socket
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from sciplot_core.canvas.operations import CanvasOperation, CanvasOperationBatch
from sciplot_core.canvas.provider import (
    ASSISTANT_CONTEXT_VERSION,
    AssistantCancellationToken,
    AssistantCancelled,
    AssistantProgressEvent,
    AssistantProviderDescriptor,
    AssistantRequest,
    AssistantResponse,
)

DEFAULT_OPENAI_MODEL = "gpt-5.6"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_PROVIDER_ID = "openai_responses"
OPENAI_REASONING_EFFORTS = frozenset(
    {"none", "low", "medium", "high", "xhigh", "max"}
)

_MAX_STREAM_LINE_BYTES = 262_144
_MAX_STREAM_EVENT_BYTES = 524_288
_MAX_STREAM_TEXT_BYTES = 262_144
_MAX_HTTP_ERROR_BYTES = 65_536
_MAX_MODEL_OPERATIONS = 16
_MAX_MODEL_WARNINGS = 16
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")

OPENAI_ASSISTANT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "proposal",
                "needs_human_confirmation",
                "needs_rule_repair",
            ],
        },
        "understanding": {"type": "string"},
        "proposal_kind": {
            "type": "string",
            "enum": ["canvas_operation_batch", "none"],
        },
        "rationale": {"type": "string"},
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "operation_type": {
                        "type": "string",
                        "enum": ["set_setting"],
                    },
                    "target_id": {"type": "string"},
                    "setting_path": {"type": "string"},
                    "value_json": {"type": "string"},
                },
                "required": [
                    "operation_type",
                    "target_id",
                    "setting_path",
                    "value_json",
                ],
                "additionalProperties": False,
            },
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "status",
        "understanding",
        "proposal_kind",
        "rationale",
        "operations",
        "warnings",
    ],
    "additionalProperties": False,
}

_PROVIDER_INSTRUCTIONS = """\
You are the bounded proposal planner inside SciPlot Canvas, a scientific-figure
workbench. Return only the requested JSON object. Never claim that an edit was
applied. SciPlot will preview, validate, and require the user to accept it.

For a proposal, use only exact target_id and setting_path pairs listed in
context.editing_capabilities.allowed_operations. Put the proposed setting value
in value_json as valid JSON. Do not invent paths, objects, datasets, columns,
coordinates, tools, or renderer commands. Do not change data authority.

If another object must be selected or scientific meaning is missing, return
needs_human_confirmation with proposal_kind none and an empty operations list.
If the request needs a SciPlot capability or deterministic rule that is not in
the catalog, return needs_rule_repair with proposal_kind none and an empty
operations list. Keep understanding and warnings concise and user-facing.
"""


class OpenAIProviderError(RuntimeError):
    """A redacted production-provider transport or protocol failure."""


class _AssistantContextUnavailable(ValueError):
    """The current Canvas selection cannot yet form a provider request."""


def _required_text(value: object, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    if len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _free_text(value: object, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _is_loopback(hostname: str | None) -> bool:
    if hostname is None:
        return False
    lowered = hostname.casefold().rstrip(".")
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def _redact(value: object, *, secrets: tuple[str, ...]) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text.replace("\r", " ").replace("\n", " ")[:1000]


@dataclass(frozen=True)
class OpenAIResponsesConfig:
    api_key: str = field(repr=False)
    model: str = DEFAULT_OPENAI_MODEL
    base_url: str = DEFAULT_OPENAI_BASE_URL
    reasoning_effort: str = "medium"
    max_output_tokens: int = 2400
    timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        key = _required_text(self.api_key, "OpenAI API key", maximum=8192)
        if "\r" in key or "\n" in key:
            raise ValueError("OpenAI API key must not contain line breaks.")
        object.__setattr__(self, "api_key", key)
        model = _required_text(self.model, "OpenAI model", maximum=200)
        if any(character.isspace() for character in model):
            raise ValueError("OpenAI model must not contain whitespace.")
        object.__setattr__(self, "model", model)
        base_url = _required_text(
            self.base_url,
            "OpenAI base URL",
            maximum=2048,
        ).rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OpenAI base URL must be an absolute HTTP(S) URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "OpenAI base URL must not contain credentials, query, or fragment."
            )
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("OpenAI base URL has an invalid port.") from exc
        if parsed.scheme != "https" and not _is_loopback(parsed.hostname):
            raise ValueError(
                "OpenAI base URL must use HTTPS except for loopback protocol tests."
            )
        if parsed.path.rstrip("/").endswith("/responses"):
            raise ValueError(
                "OpenAI base URL must name the API root, not the responses endpoint."
            )
        object.__setattr__(self, "base_url", base_url)
        effort = _required_text(
            self.reasoning_effort,
            "OpenAI reasoning effort",
            maximum=16,
        ).casefold()
        if effort not in OPENAI_REASONING_EFFORTS:
            raise ValueError(
                "OpenAI reasoning effort must be one of: "
                f"{', '.join(sorted(OPENAI_REASONING_EFFORTS))}."
            )
        object.__setattr__(self, "reasoning_effort", effort)
        if isinstance(self.max_output_tokens, bool) or not isinstance(
            self.max_output_tokens, int
        ):
            raise ValueError("OpenAI max output tokens must be an integer.")
        if not 256 <= self.max_output_tokens <= 32_000:
            raise ValueError(
                "OpenAI max output tokens must be between 256 and 32000."
            )
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise ValueError("OpenAI timeout must be numeric.")
        timeout = float(self.timeout_seconds)
        if not math.isfinite(timeout) or not 1.0 <= timeout <= 300.0:
            raise ValueError("OpenAI timeout must be between 1 and 300 seconds.")
        object.__setattr__(self, "timeout_seconds", timeout)

    @property
    def endpoint(self) -> tuple[str, str, int | None, str]:
        parsed = urlsplit(self.base_url)
        base_path = parsed.path.rstrip("/")
        path = f"{base_path}/responses" if base_path else "/responses"
        return parsed.scheme, str(parsed.hostname), parsed.port, path

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> OpenAIResponsesConfig | None:
        values = os.environ if environ is None else environ
        key = str(
            values.get("SCIPLOT_OPENAI_API_KEY")
            or values.get("OPENAI_API_KEY")
            or ""
        ).strip()
        if not key:
            return None
        model = str(
            values.get("SCIPLOT_OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        ).strip()
        base_url = str(
            values.get("SCIPLOT_OPENAI_BASE_URL")
            or values.get("OPENAI_BASE_URL")
            or DEFAULT_OPENAI_BASE_URL
        ).strip()
        effort = str(
            values.get("SCIPLOT_OPENAI_REASONING_EFFORT") or "medium"
        ).strip()
        try:
            max_tokens = int(
                str(values.get("SCIPLOT_OPENAI_MAX_OUTPUT_TOKENS") or "2400")
            )
        except ValueError as exc:
            raise ValueError(
                "SCIPLOT_OPENAI_MAX_OUTPUT_TOKENS must be an integer."
            ) from exc
        try:
            timeout = float(
                str(values.get("SCIPLOT_OPENAI_TIMEOUT_SECONDS") or "90")
            )
        except ValueError as exc:
            raise ValueError(
                "SCIPLOT_OPENAI_TIMEOUT_SECONDS must be numeric."
            ) from exc
        return cls(
            api_key=key,
            model=model,
            base_url=base_url,
            reasoning_effort=effort,
            max_output_tokens=max_tokens,
            timeout_seconds=timeout,
        )


@dataclass(frozen=True)
class _StreamResult:
    text: str = ""
    refusal: str | None = None
    incomplete_reason: str | None = None


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
            elif part_type == "refusal" and isinstance(
                part.get("refusal"), str
            ):
                refusal = str(part["refusal"])
    return "".join(texts), refusal


def _connection(
    scheme: str,
    host: str,
    port: int | None,
    timeout: float,
) -> http.client.HTTPConnection:
    connection_class = (
        http.client.HTTPSConnection
        if scheme == "https"
        else http.client.HTTPConnection
    )
    return connection_class(host, port=port, timeout=timeout)


class _ResponsesSSEClient:
    def __init__(
        self,
        config: OpenAIResponsesConfig,
        *,
        connection_factory: Callable[[str, str, int | None, float], Any]
        | None = None,
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
                    raise OpenAIProviderError(
                        "OpenAI output_text delta must be text."
                    )
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
                    if (
                        len(content_text.encode("utf-8"))
                        > _MAX_STREAM_TEXT_BYTES
                    ):
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
            field_value = raw_value[1:] if separator and raw_value.startswith(" ") else raw_value
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


def _json_loads_strict(value: str) -> Any:
    def reject_constant(constant: str) -> None:
        raise ValueError(f"Non-finite JSON constant is not allowed: {constant}")

    return json.loads(value, parse_constant=reject_constant)


def _model_envelope(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > _MAX_STREAM_TEXT_BYTES:
        raise ValueError("Model output exceeds the SciPlot size bound.")
    try:
        value = _json_loads_strict(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Model output is not valid finite JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Model output must be a JSON object.")
    expected = {
        "status",
        "understanding",
        "proposal_kind",
        "rationale",
        "operations",
        "warnings",
    }
    if set(value) != expected:
        raise ValueError("Model output does not match the closed response schema.")
    status = value.get("status")
    if status not in {
        "proposal",
        "needs_human_confirmation",
        "needs_rule_repair",
    }:
        raise ValueError("Model output has an unsupported status.")
    understanding = _required_text(
        value.get("understanding"),
        "Model understanding",
        maximum=2000,
    )
    proposal_kind = value.get("proposal_kind")
    if proposal_kind not in {"canvas_operation_batch", "none"}:
        raise ValueError("Model output has an unsupported proposal kind.")
    rationale = _free_text(
        value.get("rationale"),
        "Model rationale",
        maximum=2000,
    )
    raw_operations = value.get("operations")
    if not isinstance(raw_operations, list):
        raise ValueError("Model operations must be a list.")
    if len(raw_operations) > _MAX_MODEL_OPERATIONS:
        raise ValueError("Model output contains too many operations.")
    operations: list[dict[str, str]] = []
    operation_keys = {
        "operation_type",
        "target_id",
        "setting_path",
        "value_json",
    }
    for item in raw_operations:
        if not isinstance(item, dict) or set(item) != operation_keys:
            raise ValueError("Model operation does not match the closed schema.")
        operation_type = item.get("operation_type")
        if operation_type != "set_setting":
            raise ValueError("Model operation type is not supported.")
        operations.append(
            {
                "operation_type": "set_setting",
                "target_id": _required_text(
                    item.get("target_id"),
                    "Model target_id",
                    maximum=96,
                ),
                "setting_path": _required_text(
                    item.get("setting_path"),
                    "Model setting_path",
                    maximum=1024,
                ),
                "value_json": _required_text(
                    item.get("value_json"),
                    "Model value_json",
                    maximum=16_384,
                ),
            }
        )
    raw_warnings = value.get("warnings")
    if not isinstance(raw_warnings, list) or len(raw_warnings) > _MAX_MODEL_WARNINGS:
        raise ValueError("Model warnings must be a bounded list.")
    warnings = tuple(
        _required_text(item, "Model warning", maximum=500)
        for item in raw_warnings
    )
    if len(set(warnings)) != len(warnings):
        raise ValueError("Model warnings must be unique.")
    if status == "proposal":
        if proposal_kind != "canvas_operation_batch" or not operations:
            raise ValueError("A proposal requires one or more Canvas operations.")
        if not rationale:
            raise ValueError("A proposal requires a rationale.")
    elif proposal_kind != "none" or operations:
        raise ValueError("A non-proposal response cannot contain operations.")
    return {
        "status": status,
        "understanding": understanding,
        "proposal_kind": proposal_kind,
        "rationale": rationale,
        "operations": operations,
        "warnings": warnings,
    }


def _finite_number(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number


def _check_range(value: float, capability: dict[str, Any]) -> None:
    minimum = capability.get("minimum")
    maximum = capability.get("maximum")
    if minimum is not None and value < float(minimum):
        raise ValueError(f"Proposed value is below the allowed minimum {minimum}.")
    if maximum is not None and value > float(maximum):
        raise ValueError(f"Proposed value is above the allowed maximum {maximum}.")


def _coerce_value(capability: dict[str, Any], value: Any) -> Any:
    editor = capability["editor"]
    if editor == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Proposed boolean setting must be true or false.")
        return value
    if editor == "choice":
        if not isinstance(value, str) or value not in capability["choices"]:
            raise ValueError("Proposed choice is outside the advertised choices.")
        return value
    if editor == "text":
        if not isinstance(value, str):
            raise ValueError("Proposed text setting must be text.")
        if len(value) > 16_384:
            raise ValueError("Proposed text setting is too long.")
        return value
    if editor in {"color", "distance"}:
        return _required_text(value, "Proposed setting", maximum=256)
    if editor == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Proposed integer setting must be an integer.")
        _check_range(float(value), capability)
        return value
    if editor == "number":
        number = _finite_number(value, label="Proposed number")
        _check_range(number, capability)
        return number
    if editor == "number_or_auto":
        if isinstance(value, str) and value.strip().casefold() == "auto":
            return "Auto"
        number = _finite_number(value, label="Proposed number")
        _check_range(number, capability)
        return number
    if editor == "scalar_list":
        values = value if isinstance(value, list) else [value]
        if len(values) != 1:
            raise ValueError("Proposed scalar-list setting requires one value.")
        number = _finite_number(values[0], label="Proposed scalar-list value")
        _check_range(number, capability)
        return [number]
    if editor == "float_list":
        if not isinstance(value, list) or not value or len(value) > 128:
            raise ValueError("Proposed numeric list must contain 1 to 128 values.")
        values = [
            _finite_number(item, label="Proposed numeric-list value")
            for item in value
        ]
        for number in values:
            _check_range(number, capability)
        return values
    raise ValueError(f"Unsupported advertised editor: {editor!r}")


def _provider_safe_context(context: dict[str, Any]) -> None:
    if context.get("version") != ASSISTANT_CONTEXT_VERSION:
        raise _AssistantContextUnavailable(
            "This request predates the bounded editing-capability catalog."
        )
    project_id = str(context.get("project_id") or "")
    if project_id.startswith("/") or _WINDOWS_ABSOLUTE_PATH.match(project_id):
        raise ValueError("Assistant project_id must not be an absolute path.")
    if context.get("raw_dataset_arrays_included") is not False:
        raise ValueError("Assistant context must not contain raw dataset arrays.")
    capabilities = context.get("editing_capabilities")
    if not isinstance(capabilities, dict):
        raise _AssistantContextUnavailable(
            "Assistant context has no editing-capability catalog."
        )


class OpenAIResponsesProvider:
    """Production Responses API adapter behind SciPlot's typed proposal boundary."""

    def __init__(
        self,
        config: OpenAIResponsesConfig,
        *,
        _connection_factory: Callable[[str, str, int | None, float], Any]
        | None = None,
    ) -> None:
        self.config = config
        self._descriptor = AssistantProviderDescriptor(
            provider_id=OPENAI_PROVIDER_ID,
            display_name="OpenAI Assistant",
            model_label=config.model,
            capabilities=("canvas_operation_batch", "cancellation"),
        )
        self._client = _ResponsesSSEClient(
            config,
            connection_factory=_connection_factory,
        )

    @property
    def descriptor(self) -> AssistantProviderDescriptor:
        return self._descriptor

    def request_payload(self, request: AssistantRequest) -> dict[str, Any]:
        if request.provider_id != self.descriptor.provider_id:
            raise ValueError("Assistant request targets another provider.")
        if request.allowed_proposal_kinds != ("canvas_operation_batch",):
            raise ValueError(
                "OpenAI provider currently accepts only CanvasOperationBatch requests."
            )
        _provider_safe_context(request.context)
        user_payload = {
            "task": "Propose a bounded SciPlot Canvas edit.",
            "intent": request.intent,
            "base_revision": request.base_revision,
            "allowed_proposal_kinds": list(request.allowed_proposal_kinds),
            "context": request.context,
        }
        preview = request.visual_preview
        if preview is not None:
            user_payload["visual_preview"] = {
                "sha256": preview["sha256"],
                "width": preview["width"],
                "height": preview["height"],
                "revision": preview["revision"],
            }
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": json.dumps(
                    user_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            }
        ]
        if preview is not None:
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{preview['base64']}",
                    "detail": "high",
                }
            )
        return {
            "model": self.config.model,
            "store": False,
            "stream": True,
            "reasoning": {"effort": self.config.reasoning_effort},
            "max_output_tokens": self.config.max_output_tokens,
            "instructions": _PROVIDER_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "sciplot_canvas_assistant_response",
                    "strict": True,
                    "schema": OPENAI_ASSISTANT_OUTPUT_SCHEMA,
                }
            },
        }

    def _response(
        self,
        request: AssistantRequest,
        *,
        status: str,
        understanding: str,
        warnings: tuple[str, ...] = (),
        batch: CanvasOperationBatch | None = None,
    ) -> AssistantResponse:
        return AssistantResponse(
            request_id=request.request_id,
            transaction_id=request.transaction_id,
            provider_id=request.provider_id,
            request_sha256=request.payload_sha256,
            status=status,
            understanding=understanding,
            proposal_kind=("canvas_operation_batch" if batch is not None else None),
            proposal=(batch.to_dict() if batch is not None else None),
            warnings=warnings,
        )

    def _typed_model_response(
        self,
        request: AssistantRequest,
        envelope: dict[str, Any],
    ) -> AssistantResponse:
        if envelope["status"] != "proposal":
            return self._response(
                request,
                status=envelope["status"],
                understanding=envelope["understanding"],
                warnings=envelope["warnings"],
            )
        capabilities = request.context["editing_capabilities"]
        allowed = {
            (item["target_id"], item["setting_path"]): item
            for item in capabilities["allowed_operations"]
        }
        operations: list[CanvasOperation] = []
        seen_paths: set[str] = set()
        for draft in envelope["operations"]:
            key = (draft["target_id"], draft["setting_path"])
            capability = allowed.get(key)
            if capability is None:
                raise ValueError(
                    "Model proposed a target or setting outside the advertised catalog."
                )
            if draft["setting_path"] in seen_paths:
                raise ValueError("Model proposed the same setting more than once.")
            seen_paths.add(draft["setting_path"])
            try:
                raw_value = _json_loads_strict(draft["value_json"])
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError("Model operation value_json is invalid.") from exc
            value = _coerce_value(capability, raw_value)
            if value == capability["current_value"]:
                continue
            operations.append(
                CanvasOperation.set_setting(
                    target_id=draft["target_id"],
                    setting_path=draft["setting_path"],
                    value=value,
                    expected_value=capability["current_value"],
                    require_expected_value=True,
                )
            )
        if not operations:
            return self._response(
                request,
                status="needs_human_confirmation",
                understanding=(
                    "The requested result already matches the advertised current "
                    "settings, so there is no edit to preview."
                ),
                warnings=envelope["warnings"],
            )
        batch = CanvasOperationBatch(
            base_revision=request.base_revision,
            operations=tuple(operations),
            provider=request.provider_id,
            rationale=envelope["rationale"],
        )
        return self._response(
            request,
            status="proposal",
            understanding=envelope["understanding"],
            warnings=envelope["warnings"],
            batch=batch,
        )

    def generate(
        self,
        request: AssistantRequest,
        *,
        emit_progress: Callable[[AssistantProgressEvent], None],
        cancellation: AssistantCancellationToken,
    ) -> AssistantResponse:
        restored = AssistantRequest.from_dict(request.to_dict())
        if restored.provider_id != self.descriptor.provider_id:
            raise ValueError("Assistant request targets another provider.")
        sequence = 0

        def progress(stage: str, message: str, value: float | None) -> None:
            nonlocal sequence
            sequence += 1
            emit_progress(
                AssistantProgressEvent(
                    request_id=restored.request_id,
                    provider_id=restored.provider_id,
                    sequence=sequence,
                    stage=stage,
                    message=message,
                    cancellable=True,
                    progress=value,
                )
            )

        cancellation.raise_if_cancelled()
        progress(
            "understanding",
            "Reading the selected object and its bounded editing catalog.",
            0.1,
        )
        try:
            payload = self.request_payload(restored)
        except _AssistantContextUnavailable as exc:
            return self._response(
                restored,
                status="needs_human_confirmation",
                understanding=(
                    "Select an editable Canvas object and submit the request again."
                ),
                warnings=(_redact(exc, secrets=()),),
            )
        except ValueError as exc:
            return self._response(
                restored,
                status="needs_rule_repair",
                understanding=(
                    "The local provider boundary rejected this request before any "
                    "data was sent. The figure was not changed."
                ),
                warnings=(f"Provider request rejected: {_redact(exc, secrets=())}",),
            )
        allowed_operations = restored.context["editing_capabilities"][
            "allowed_operations"
        ]
        if not allowed_operations:
            return self._response(
                restored,
                status="needs_human_confirmation",
                understanding=(
                    "The current selection has no bounded editable fields. Select "
                    "an axis, series, legend, graph, page, scalar field, or label."
                ),
            )
        proposing_emitted = False

        def headers_ready() -> None:
            progress(
                "planning",
                "The model is planning against the exact allowed settings.",
                0.35,
            )

        def text_started() -> None:
            nonlocal proposing_emitted
            if proposing_emitted:
                return
            proposing_emitted = True
            progress(
                "proposing",
                "A structured proposal is arriving for local validation.",
                0.7,
            )

        result = self._client.stream(
            payload,
            cancellation=cancellation,
            on_headers=headers_ready,
            on_text=text_started,
        )
        cancellation.raise_if_cancelled()
        if not proposing_emitted:
            text_started()
        progress(
            "validating",
            "Validating the response against the local typed operation boundary.",
            0.92,
        )
        if result.refusal:
            refusal = _redact(result.refusal, secrets=())[:500]
            return self._response(
                restored,
                status="needs_human_confirmation",
                understanding="The model declined to create a Canvas proposal.",
                warnings=(refusal,),
            )
        if result.incomplete_reason:
            return self._response(
                restored,
                status="needs_rule_repair",
                understanding=(
                    "The model response ended before a complete typed proposal was "
                    "available."
                ),
                warnings=(
                    f"Incomplete response: {result.incomplete_reason[:400]}",
                ),
            )
        try:
            envelope = _model_envelope(result.text)
            return self._typed_model_response(restored, envelope)
        except ValueError as exc:
            safe = _redact(exc, secrets=())[:420]
            return self._response(
                restored,
                status="needs_rule_repair",
                understanding=(
                    "The model response could not be converted into a safe Canvas "
                    "proposal. The figure was not changed."
                ),
                warnings=(f"Typed proposal rejected: {safe}",),
            )


def load_openai_provider_from_environment(
    environ: Mapping[str, str] | None = None,
) -> OpenAIResponsesProvider | None:
    config = OpenAIResponsesConfig.from_environment(environ)
    return OpenAIResponsesProvider(config) if config is not None else None


__all__ = [
    "DEFAULT_OPENAI_BASE_URL",
    "DEFAULT_OPENAI_MODEL",
    "OPENAI_ASSISTANT_OUTPUT_SCHEMA",
    "OPENAI_PROVIDER_ID",
    "OpenAIProviderError",
    "OpenAIResponsesConfig",
    "OpenAIResponsesProvider",
    "load_openai_provider_from_environment",
]
