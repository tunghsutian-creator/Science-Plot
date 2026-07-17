from __future__ import annotations

import json
import tempfile
import threading
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core._utils import json_safe
from sciplot_core.canvas.model import CanvasSelection
from sciplot_core.canvas.operations import CanvasOperationBatch
from sciplot_core.canvas.provider import (
    ASSISTANT_CONTEXT_KIND,
    AssistantCancellationToken,
    AssistantCancelled,
    AssistantRequest,
)
from sciplot_core.openai_provider import (
    OPENAI_PROVIDER_ID,
    OpenAIProviderError,
    OpenAIResponsesConfig,
    OpenAIResponsesProvider,
    load_openai_provider_from_environment,
)

OPENAI_PROVIDER_PROBE_KIND = "sciplot_openai_provider_probe"
OPENAI_PROVIDER_PROBE_VERSION = 1
_PROBE_KEY = "sk-sciplot-protocol-probe-never-persist"


def _check(
    check_id: str,
    label: str,
    passed: bool,
    detail: Any = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _sse_payload(event_type: str, payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {encoded}\n\n".encode()


def _completed_response(
    text: str = "",
    *,
    refusal: str | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if refusal is not None:
        content.append({"type": "refusal", "refusal": refusal})
    elif text:
        content.append(
            {"type": "output_text", "text": text, "annotations": []}
        )
    return {
        "id": "resp_sciplot_probe",
        "object": "response",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": [
            {
                "id": "msg_sciplot_probe",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": content,
            }
        ],
    }


def _user_payload(request_body: dict[str, Any]) -> dict[str, Any]:
    messages = request_body.get("input")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Responses request has no input.")
    message = messages[0]
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list) or not content:
        raise ValueError("Responses request has no input content.")
    first = content[0]
    text = first.get("text") if isinstance(first, dict) else None
    if not isinstance(text, str):
        raise ValueError("Responses request has no input text.")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Responses input text must contain an object.")
    return payload


def _model_draft(user_payload: dict[str, Any], scenario: str) -> str:
    capabilities = user_payload["context"]["editing_capabilities"][
        "allowed_operations"
    ]
    capability = next(
        (item for item in capabilities if item.get("editor") == "text"),
        capabilities[0],
    )
    target_id = str(capability["target_id"])
    setting_path = str(capability["setting_path"])
    current = capability["current_value"]
    value: Any = f"{current} · AI" if isinstance(current, str) else current
    if scenario == "unknown_path":
        setting_path = "/page1/graph1/forbidden/value"
    elif scenario == "invalid_value":
        value = 999
    elif scenario == "noop":
        value = current
    operations = [
        {
            "operation_type": "set_setting",
            "target_id": target_id,
            "setting_path": setting_path,
            "value_json": json.dumps(value, ensure_ascii=False),
        }
    ]
    if scenario == "duplicate":
        operations.append(dict(operations[0]))
    return json.dumps(
        {
            "status": "proposal",
            "understanding": "Rename only the selected bounded field.",
            "proposal_kind": "canvas_operation_batch",
            "rationale": "Apply the requested selected-object text refinement.",
            "operations": operations,
            "warnings": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _wire_events(user_payload: dict[str, Any], scenario: str) -> bytes:
    events = bytearray()
    events.extend(
        _sse_payload(
            "response.created",
            {
                "type": "response.created",
                "response": {"id": "resp_sciplot_probe", "status": "in_progress"},
            },
        )
    )
    if scenario == "refusal":
        refusal = "The protocol fixture declined this request."
        events.extend(
            _sse_payload(
                "response.refusal.done",
                {"type": "response.refusal.done", "refusal": refusal},
            )
        )
        events.extend(
            _sse_payload(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": _completed_response(refusal=refusal),
                },
            )
        )
        return bytes(events)
    if scenario == "incomplete":
        events.extend(
            _sse_payload(
                "response.incomplete",
                {
                    "type": "response.incomplete",
                    "response": {
                        "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                    },
                },
            )
        )
        return bytes(events)
    text = (
        "{\"status\":"
        if scenario == "malformed"
        else _model_draft(user_payload, scenario)
    )
    split_at = max(1, len(text) // 2)
    for delta in (text[:split_at], text[split_at:]):
        events.extend(
            _sse_payload(
                "response.output_text.delta",
                {"type": "response.output_text.delta", "delta": delta},
            )
        )
    events.extend(
        _sse_payload(
            "response.output_text.done",
            {"type": "response.output_text.done", "text": text},
        )
    )
    events.extend(
        _sse_payload(
            "response.completed",
            {
                "type": "response.completed",
                "response": _completed_response(text),
            },
        )
    )
    return bytes(events)


class _WireSocket:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def shutdown(self, _how: int) -> None:
        self.closed.set()

    def close(self) -> None:
        self.closed.set()


class _WireResponse:
    def __init__(
        self,
        *,
        scenario: str,
        user_payload: dict[str, Any],
        wire_socket: _WireSocket,
        cancel_started: threading.Event,
    ) -> None:
        self.status = 401 if scenario == "http_error" else 200
        self._scenario = scenario
        self._socket = wire_socket
        self._cancel_started = cancel_started
        self._body = (
            json.dumps(
                {
                    "error": {
                        "type": "authentication_error",
                        "message": f"rejected credential {_PROBE_KEY}",
                    }
                }
            ).encode()
            if scenario == "http_error"
            else b""
        )
        wire = b"" if scenario in {"http_error", "cancel"} else _wire_events(
            user_payload,
            scenario,
        )
        if scenario == "cancel":
            wire = _sse_payload(
                "response.created",
                {
                    "type": "response.created",
                    "response": {
                        "id": "resp_sciplot_probe",
                        "status": "in_progress",
                    },
                },
            )
        self._lines = wire.splitlines(keepends=True)

    def getheader(self, name: str) -> str | None:
        if name.casefold() == "content-type":
            return (
                "application/json"
                if self.status != 200
                else "text/event-stream; charset=utf-8"
            )
        return None

    def read(self, amount: int = -1) -> bytes:
        return self._body if amount < 0 else self._body[:amount]

    def readline(self, _limit: int = -1) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        if self._scenario == "cancel":
            self._cancel_started.set()
            self._socket.closed.wait(5.0)
        return b""


class _WireConnection:
    def __init__(
        self,
        fixture: OpenAIProviderWireFixture,
        *,
        scheme: str,
        host: str,
        port: int | None,
        timeout: float,
    ) -> None:
        self.fixture = fixture
        self.sock = _WireSocket()
        self.scheme = scheme
        self.host = host
        self.port = port
        self.timeout = timeout
        self._scenario = ""
        self._user_payload: dict[str, Any] = {}

    def connect(self) -> None:
        return

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        request_body = json.loads(body.decode("utf-8"))
        self._user_payload = _user_payload(request_body)
        intent = str(self._user_payload.get("intent") or "")
        scenario_suffix = intent.partition("SCENARIO:")[2]
        self._scenario = (
            scenario_suffix.split(maxsplit=1)[0]
            if scenario_suffix
            else "success"
        )
        self.fixture.records.append(
            {
                "scheme": self.scheme,
                "host": self.host,
                "port": self.port,
                "timeout": self.timeout,
                "method": method,
                "path": path,
                "authorization_valid": (
                    headers.get("Authorization") == f"Bearer {_PROBE_KEY}"
                ),
                "accept": headers.get("Accept"),
                "content_type": headers.get("Content-Type"),
                "body": request_body,
                "scenario": self._scenario,
            }
        )

    def getresponse(self) -> _WireResponse:
        return _WireResponse(
            scenario=self._scenario,
            user_payload=self._user_payload,
            wire_socket=self.sock,
            cancel_started=self.fixture.cancel_stream_started,
        )

    def close(self) -> None:
        self.sock.close()


class OpenAIProviderWireFixture:
    """In-memory HTTP/SSE wire fixture used without network or credentials."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.cancel_stream_started = threading.Event()

    def connection_factory(
        self,
        scheme: str,
        host: str,
        port: int | None,
        timeout: float,
    ) -> _WireConnection:
        return _WireConnection(
            self,
            scheme=scheme,
            host=host,
            port=port,
            timeout=timeout,
        )

    def provider(self) -> OpenAIResponsesProvider:
        return OpenAIResponsesProvider(
            OpenAIResponsesConfig(
                api_key=_PROBE_KEY,
                model="probe-model",
                base_url="http://127.0.0.1:8765/v1",
                timeout_seconds=5,
            ),
            _connection_factory=self.connection_factory,
        )


def _context(*, allowed: bool = True, version: int = 3) -> dict[str, Any]:
    target_id = "11111111-1111-4111-8111-111111111111"
    selection = CanvasSelection(
        object_ids=[target_id],
        primary_object_id=target_id,
    ).to_dict()
    value: dict[str, Any] = {
        "kind": ASSISTANT_CONTEXT_KIND,
        "version": version,
        "project_id": "openai_provider_probe",
        "document_id": "22222222-2222-4222-8222-222222222222",
        "revision": 7,
        "state": "ai_proposing",
        "page": 0,
        "selection": selection,
        "selected_object": {
            "object_id": target_id,
            "object_type": "axis",
            "display_name": "x axis",
        },
        "document_inventory": {
            "object_count": 2,
            "object_types": {"axis": 1, "page": 1},
        },
        "review": {"active_count": 0, "annotations": []},
        "qa": {
            "structural_status": "passed",
            "structural_failed_ids": [],
            "structural_warning_ids": [],
            "ready_for_artifact_qa": True,
            "artifact_status": "not_run",
            "ready_to_use": None,
        },
        "raw_dataset_arrays_included": False,
        "explicit_selected_point_included": False,
    }
    if version >= 3:
        value["editing_capabilities"] = {
            "scope": "selected_object",
            "target_object_id": target_id,
            "allowed_operations": (
                [
                    {
                        "operation_type": "set_setting",
                        "target_id": target_id,
                        "field_id": "axis_label",
                        "section": "Axis",
                        "label": "Label",
                        "setting_path": "/page1/graph1/x/label",
                        "editor": "text",
                        "current_value": "Frequency",
                        "choices": [],
                        "minimum": None,
                        "maximum": None,
                        "help_text": "Visible axis label.",
                    }
                ]
                if allowed
                else []
            ),
        }
    return value


def _request(
    scenario: str,
    *,
    allowed: bool = True,
    version: int = 3,
) -> AssistantRequest:
    return AssistantRequest(
        transaction_id=str(uuid4()),
        provider_id=OPENAI_PROVIDER_ID,
        intent=f"SCENARIO:{scenario} Rename the selected x-axis label.",
        base_revision=7,
        context=_context(allowed=allowed, version=version),
        allowed_proposal_kinds=("canvas_operation_batch",),
    )


def _generate(
    provider: OpenAIResponsesProvider,
    request: AssistantRequest,
) -> tuple[Any, list[Any]]:
    progress: list[Any] = []
    response = provider.generate(
        request,
        emit_progress=progress.append,
        cancellation=AssistantCancellationToken(),
    )
    response.validate_for_request(request)
    return response, progress


def run_openai_provider_probe(*, output_root: Path) -> dict[str, Any]:
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="openai_provider_probe_", dir=resolved_output)
    )
    summary_path = run_root / "openai_provider_probe.json"
    checks: list[dict[str, Any]] = []
    error: dict[str, str] | None = None

    try:
        absent = load_openai_provider_from_environment({})
        configured = OpenAIResponsesConfig.from_environment(
            {
                "OPENAI_API_KEY": "fallback-key",
                "SCIPLOT_OPENAI_API_KEY": _PROBE_KEY,
                "SCIPLOT_OPENAI_MODEL": "probe-model",
                "SCIPLOT_OPENAI_REASONING_EFFORT": "high",
            }
        )
        checks.append(
            _check(
                "environment_activation",
                "The provider is absent without a key and honors explicit SciPlot environment precedence",
                absent is None
                and configured is not None
                and configured.api_key == _PROBE_KEY
                and configured.model == "probe-model"
                and configured.reasoning_effort == "high",
                {
                    "absent_without_key": absent is None,
                    "model": configured.model if configured else None,
                    "reasoning_effort": (
                        configured.reasoning_effort if configured else None
                    ),
                },
            )
        )
        insecure_rejected = False
        try:
            OpenAIResponsesConfig(
                api_key=_PROBE_KEY,
                base_url="http://api.example.com/v1",
            )
        except ValueError:
            insecure_rejected = True
        checks.append(
            _check(
                "transport_security",
                "Non-loopback production endpoints require HTTPS",
                insecure_rejected,
            )
        )
        from sciplot_gui.app import resolve_canvas_assistant_provider

        auto_provider = resolve_canvas_assistant_provider(
            environ={
                "SCIPLOT_OPENAI_API_KEY": _PROBE_KEY,
                "SCIPLOT_OPENAI_BASE_URL": "http://127.0.0.1:8765/v1",
                "SCIPLOT_OPENAI_MODEL": "probe-model",
            }
        )
        explicitly_disabled = resolve_canvas_assistant_provider(
            None,
            environ={"SCIPLOT_OPENAI_API_KEY": _PROBE_KEY},
        )
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")
            invalid_config_provider = resolve_canvas_assistant_provider(
                environ={
                    "SCIPLOT_OPENAI_API_KEY": _PROBE_KEY,
                    "SCIPLOT_OPENAI_BASE_URL": "http://api.example.com/v1",
                }
            )
        checks.append(
            _check(
                "canvas_automatic_activation",
                "Canvas activates a valid provider and keeps the independent path for absent, disabled, or invalid configuration",
                auto_provider is not None
                and auto_provider.descriptor.provider_id == OPENAI_PROVIDER_ID
                and explicitly_disabled is None
                and invalid_config_provider is None
                and len(caught_warnings) == 1
                and "continuing without OpenAI Assistant"
                in str(caught_warnings[0].message),
                {
                    "automatic_provider": (
                        auto_provider.descriptor.to_dict()
                        if auto_provider is not None
                        else None
                    ),
                    "explicit_none_preserved": explicitly_disabled is None,
                    "invalid_config_falls_back": invalid_config_provider is None,
                    "warning_count": len(caught_warnings),
                },
            )
        )

        wire = OpenAIProviderWireFixture()
        provider = wire.provider()
        success_request = _request("success")
        success, progress = _generate(provider, success_request)
        batch = CanvasOperationBatch.from_dict(dict(success.proposal or {}))
        operation = batch.operations[0]
        record = wire.records[-1]
        body = record["body"]
        format_contract = body["text"]["format"]
        input_text = body["input"][0]["content"][0]["text"]
        checks.append(
            _check(
                "responses_api_contract",
                "The adapter sends store=false streaming Responses input with strict Structured Outputs",
                record["method"] == "POST"
                and record["path"] == "/v1/responses"
                and record["authorization_valid"] is True
                and record["accept"] == "text/event-stream"
                and body["store"] is False
                and body["stream"] is True
                and format_contract["type"] == "json_schema"
                and format_contract["strict"] is True
                and body["reasoning"] == {"effort": "medium"},
                {
                    "method": record["method"],
                    "path": record["path"],
                    "authorization_valid": record["authorization_valid"],
                    "store": body["store"],
                    "stream": body["stream"],
                    "format_type": format_contract["type"],
                    "strict": format_contract["strict"],
                },
            )
        )
        checks.append(
            _check(
                "bounded_context_only",
                "Provider input contains the capability catalog but no raw arrays, document paths, or host request IDs",
                '"editing_capabilities"' in input_text
                and '"raw_dataset_arrays_included":false' in input_text
                and "document_path" not in input_text
                and "source_root" not in input_text
                and "request_id" not in input_text,
            )
        )
        checks.append(
            _check(
                "host_owned_typed_proposal",
                "The host supplies provider, revision, IDs, and exact expected value around the model draft",
                success.status == "proposal"
                and batch.provider == OPENAI_PROVIDER_ID
                and batch.base_revision == success_request.base_revision
                and operation.target_id
                == "11111111-1111-4111-8111-111111111111"
                and operation.arguments["setting_path"]
                == "/page1/graph1/x/label"
                and operation.arguments["expected_value"] == "Frequency"
                and operation.arguments["value"] == "Frequency · AI"
                and bool(batch.batch_id)
                and bool(operation.operation_id),
                operation.to_dict(),
            )
        )
        checks.append(
            _check(
                "ordered_stream_progress",
                "Streaming progress is contiguous and reaches local validation",
                [event.sequence for event in progress] == [1, 2, 3, 4]
                and [event.stage for event in progress]
                == ["understanding", "planning", "proposing", "validating"],
                [event.to_dict() for event in progress],
            )
        )

        unknown, _ = _generate(provider, _request("unknown_path"))
        invalid, _ = _generate(provider, _request("invalid_value"))
        duplicate, _ = _generate(provider, _request("duplicate"))
        malformed, _ = _generate(provider, _request("malformed"))
        checks.append(
            _check(
                "typed_boundary_rejections",
                "Unknown paths, invalid values, duplicates, and malformed JSON stop without a proposal",
                all(
                    item.status == "needs_rule_repair" and item.proposal is None
                    for item in (unknown, invalid, duplicate, malformed)
                ),
                {
                    "unknown_path": unknown.status,
                    "invalid_value": invalid.status,
                    "duplicate": duplicate.status,
                    "malformed": malformed.status,
                },
            )
        )
        noop, _ = _generate(provider, _request("noop"))
        refusal, _ = _generate(provider, _request("refusal"))
        incomplete, _ = _generate(provider, _request("incomplete"))
        checks.append(
            _check(
                "nonproposal_terminal_states",
                "No-op, refusal, and incomplete streams become explicit non-mutating states",
                noop.status == "needs_human_confirmation"
                and refusal.status == "needs_human_confirmation"
                and incomplete.status == "needs_rule_repair"
                and all(
                    item.proposal is None for item in (noop, refusal, incomplete)
                ),
                {
                    "noop": noop.status,
                    "refusal": refusal.status,
                    "incomplete": incomplete.status,
                },
            )
        )
        request_count = len(wire.records)
        no_capabilities, no_cap_progress = _generate(
            provider,
            _request("success", allowed=False),
        )
        legacy, legacy_progress = _generate(
            provider,
            _request("success", version=2),
        )
        checks.append(
            _check(
                "local_selection_gate",
                "Missing or legacy capability catalogs stop locally without an API request",
                no_capabilities.status == "needs_human_confirmation"
                and legacy.status == "needs_human_confirmation"
                and len(wire.records) == request_count
                and len(no_cap_progress) == 1
                and len(legacy_progress) == 1,
                {
                    "request_count_before": request_count,
                    "request_count_after": len(wire.records),
                },
            )
        )

        cancellation = AssistantCancellationToken()
        cancel_error: list[BaseException] = []

        def run_cancel() -> None:
            try:
                provider.generate(
                    _request("cancel"),
                    emit_progress=lambda _event: None,
                    cancellation=cancellation,
                )
            except BaseException as exc:
                cancel_error.append(exc)

        cancel_thread = threading.Thread(target=run_cancel, daemon=True)
        cancel_thread.start()
        started = wire.cancel_stream_started.wait(2.0)
        cancel_started_at = time.perf_counter()
        cancellation.cancel()
        cancel_thread.join(timeout=2.0)
        cancel_latency = (time.perf_counter() - cancel_started_at) * 1000.0
        checks.append(
            _check(
                "cooperative_stream_cancellation",
                "Cancellation interrupts an active SSE read and returns no late proposal",
                started
                and not cancel_thread.is_alive()
                and len(cancel_error) == 1
                and isinstance(cancel_error[0], AssistantCancelled)
                and cancel_latency < 2000.0,
                {
                    "stream_started": started,
                    "thread_alive": cancel_thread.is_alive(),
                    "error_type": (
                        type(cancel_error[0]).__name__ if cancel_error else None
                    ),
                    "latency_ms": round(cancel_latency, 3),
                },
            )
        )

        http_error = ""
        try:
            _generate(provider, _request("http_error"))
        except OpenAIProviderError as exc:
            http_error = str(exc)
        checks.append(
            _check(
                "credential_redaction",
                "API credentials stay out of descriptors, repr, errors, and persisted probe evidence",
                bool(http_error)
                and _PROBE_KEY not in http_error
                and _PROBE_KEY not in repr(provider.config)
                and _PROBE_KEY not in repr(provider.descriptor)
                and "[REDACTED]" in http_error,
                {
                    "error": http_error,
                    "descriptor": provider.descriptor.to_dict(),
                },
            )
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "probe_exception",
                "The OpenAI provider protocol probe completed without an exception",
                False,
                error,
            )
        )

    status = (
        "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    payload = {
        "kind": OPENAI_PROVIDER_PROBE_KIND,
        "version": OPENAI_PROVIDER_PROBE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [
                item["id"] for item in checks if item["status"] != "passed"
            ],
        },
        "artifacts": {
            "run_root": str(run_root),
            "summary": str(summary_path),
        },
        "error": error,
        "limitations": [
            "The probe uses an in-memory HTTP/SSE wire fixture; it does not call or evaluate a live OpenAI model.",
            "The production provider currently advertises bounded CanvasOperationBatch edits only; data mapping remains a separately confirmed deterministic path.",
        ],
    }
    serialized = json.dumps(json_safe(payload), indent=2, ensure_ascii=False)
    if _PROBE_KEY in serialized:
        raise RuntimeError("OpenAI provider probe attempted to persist its API key.")
    summary_path.write_text(serialized, encoding="utf-8")
    return payload


__all__ = [
    "OPENAI_PROVIDER_PROBE_KIND",
    "OPENAI_PROVIDER_PROBE_VERSION",
    "OpenAIProviderWireFixture",
    "run_openai_provider_probe",
]
