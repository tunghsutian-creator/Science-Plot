"""Offline transport boundaries: resource ownership never changes the outcome."""

from __future__ import annotations

import io
import json
import threading
import traceback

import pytest

from sciplot_core.assistant_provider import AssistantCancellationToken, AssistantCancelled
from sciplot_core.openai_provider import OpenAIProviderError, OpenAIResponsesConfig
from sciplot_core.openai_provider.sse_client import _ResponsesSSEClient
from sciplot_core.openai_provider.contracts import _MAX_STREAM_LINE_BYTES


_KEY = "sciplot-offline-transport-test-key"


def _event(kind, **values):
    return ("data: " + json.dumps({"type": kind, **values}) + "\n\n").encode()


def _completed():
    return _event("response.completed", response={
        "status": "completed", "output": [{"content": [{
            "type": "output_text", "text": "bounded proposal",
        }]}],
    })


class _Socket:
    def __init__(self):
        self.interrupted = threading.Event()
        self.shutdown_calls = 0

    def shutdown(self, _how):
        self.shutdown_calls += 1
        self.interrupted.set()

    def close(self):
        self.interrupted.set()


class _Response:
    def __init__(self, wire=None, *, status=200, close_error=False):
        self.status = status
        self.body = io.BytesIO(_completed() if wire is None else wire)
        self.close_error = close_error
        self.close_calls = 0
        self.before_read = lambda: None

    def getheader(self, _name):
        return "text/event-stream"

    def readline(self, limit):
        self.before_read()
        return self.body.readline(limit)

    def read(self, limit):
        self.before_read()
        return self.body.read(limit)

    def close(self):
        self.close_calls += 1
        self.body.close()
        if self.close_error:
            raise OSError("response cleanup " + _KEY)


class _Connection:
    def __init__(self, response=None, *, close_error=False):
        self.response = response if response is not None else _Response()
        self.sock = _Socket()
        self.close_error = close_error
        self.close_calls = 0
        self.request_calls = 0
        self.on_connect = lambda: None
        self.on_headers = lambda: None

    def connect(self):
        self.on_connect()

    def request(self, *_args, **_kwargs):
        self.request_calls += 1

    def getresponse(self):
        self.on_headers()
        return self.response

    def close(self):
        self.close_calls += 1
        if self.sock is not None:
            self.sock.close()
        if self.close_error:
            raise OSError("connection cleanup " + _KEY)


def _stream(connection, token=None, *, on_text=lambda: None):
    client = _ResponsesSSEClient(
        OpenAIResponsesConfig(api_key=_KEY),
        connection_factory=lambda *_args: connection,
    )
    return client.stream({}, cancellation=token or AssistantCancellationToken(),
                         on_headers=lambda: None, on_text=on_text)


def test_success_explicitly_closes_response_and_connection_once():
    connection = _Connection()
    result = _stream(connection)
    assert result.text == "bounded proposal"
    assert connection.response.close_calls == connection.close_calls == 1


@pytest.mark.parametrize("resource", ["response", "connection", "both"])
def test_cleanup_failure_is_redacted_and_other_resource_still_closes(resource):
    response = _Response(close_error=resource in {"response", "both"})
    connection = _Connection(response, close_error=resource in {"connection", "both"})
    with pytest.raises(OpenAIProviderError, match="cleanup") as exc:
        _stream(connection)
    assert _KEY not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)
    assert response.close_calls == connection.close_calls == 1


@pytest.mark.parametrize("cancelled", [False, True])
def test_cleanup_does_not_replace_original_protocol_or_cancellation_failure(cancelled):
    token = AssistantCancellationToken()
    connection = _Connection(_Response(b"data: invalid JSON\n\n"), close_error=True)
    if cancelled:
        token.cancel()
    expected = AssistantCancelled if cancelled else OpenAIProviderError
    with pytest.raises(expected) as exc:
        _stream(connection, token)
    assert ("cancelled" if cancelled else "invalid JSON") in str(exc.value)
    assert _KEY not in str(exc.value)
    assert connection.close_calls == 1
    assert connection.request_calls == (0 if cancelled else 1)


def test_cancel_from_final_text_callback_cannot_return_a_late_result():
    token = AssistantCancellationToken()
    connection = _Connection()
    with pytest.raises(AssistantCancelled):
        _stream(connection, token, on_text=token.cancel)
    assert connection.response.close_calls == connection.close_calls == 1


def test_stream_failure_redacts_configured_credential():
    connection = _Connection(_Response(_event(
        "response.failed", error={"message": "rejected " + _KEY},
    )))
    with pytest.raises(OpenAIProviderError, match="response failed") as exc:
        _stream(connection)
    assert _KEY not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)


@pytest.mark.parametrize("phase", ["connect", "headers", "read", "error_body"])
def test_cancellation_interrupts_only_its_active_socket_and_joins_monitor(phase):
    response = _Response(status=401 if phase == "error_body" else 200)
    connection = _Connection(response)
    entered = threading.Event()
    token = AssistantCancellationToken()
    outcome = []
    monitor_threads = []

    def block():
        monitor_threads.extend(t for t in threading.enumerate()
                               if t.name == "sciplot-openai-cancel-monitor")
        entered.set()
        assert connection.sock.interrupted.wait(1), "transport did not interrupt I/O"
        raise OSError("cancelled I/O")

    if phase == "connect":
        connection.on_connect = block
    elif phase == "headers":
        connection.on_headers = block
    else:
        response.before_read = block

    def execute():
        try:
            outcome.append(_stream(connection, token))
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert entered.wait(1), "transport did not reach controlled I/O"
        token.cancel()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert len(outcome) == 1 and isinstance(outcome[0], AssistantCancelled)
        assert connection.close_calls == 1
        assert response.close_calls == (1 if phase in {"read", "error_body"} else 0)
        assert monitor_threads and all(not t.is_alive() for t in monitor_threads)
    finally:
        token.cancel()
        connection.sock.interrupted.set()
        worker.join(timeout=1)


@pytest.mark.parametrize("wire, message", [
    (b"", "without a terminal"),
    (b"data: []\n\n", "JSON object"),
    (b"data: {\"type\":\"response.output_text.delta\",\"delta\":1}\n\n", "must be text"),
    (b"data: \xff\n\n", "not UTF-8"),
], ids=["missing-terminal", "nonobject-json", "nontext-delta", "invalid-utf8"])
def test_protocol_failures_keep_their_reason_and_close_all_resources(wire, message):
    connection = _Connection(_Response(wire))
    with pytest.raises(OpenAIProviderError, match=message):
        _stream(connection)
    assert connection.response.close_calls == connection.close_calls == 1


def test_non_cancelled_io_failure_remains_a_redacted_provider_error():
    connection = _Connection()

    def fail():
        raise OSError("network " + _KEY)

    connection.on_connect = fail
    with pytest.raises(OpenAIProviderError, match="request failed: OSError") as exc:
        _stream(connection)
    assert _KEY not in str(exc.value) and "[REDACTED]" in str(exc.value)
    assert connection.close_calls == 1 and connection.response.close_calls == 0


@pytest.mark.parametrize("cancelled", [False, True])
def test_formatted_transport_traceback_cannot_expose_the_configured_credential(cancelled):
    token = AssistantCancellationToken()
    connection = _Connection()

    def fail():
        if cancelled:
            token.cancel()
        raise OSError("raw transport exception " + _KEY)

    connection.on_connect = fail
    with pytest.raises(AssistantCancelled if cancelled else OpenAIProviderError) as exc:
        _stream(connection, token)
    rendered = "".join(traceback.format_exception(exc.value))
    assert _KEY not in rendered
    assert connection.close_calls == 1


def test_detached_http_response_retains_its_connected_socket_for_cancellation():
    connection = _Connection()
    active = connection.sock
    entered = threading.Event()
    token = AssistantCancellationToken()
    outcome = []

    def detach():
        connection.sock = None

    def block():
        entered.set()
        assert active.interrupted.wait(1)
        raise OSError("detached response read interrupted")

    connection.on_headers = detach
    connection.response.before_read = block

    def execute():
        try:
            outcome.append(_stream(connection, token))
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert entered.wait(1)
        token.cancel()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert len(outcome) == 1 and isinstance(outcome[0], AssistantCancelled)
        assert active.shutdown_calls == 1
        assert connection.response.close_calls == connection.close_calls == 1
    finally:
        token.cancel()
        active.interrupted.set()
        worker.join(timeout=1)


def test_cancellation_during_response_disposal_cannot_return_a_result():
    token = AssistantCancellationToken()
    connection = _Connection()
    close = connection.response.close

    def cancel_and_close():
        token.cancel()
        close()

    connection.response.close = cancel_and_close
    with pytest.raises(AssistantCancelled):
        _stream(connection, token)
    assert connection.response.close_calls == connection.close_calls == 1


def test_monitor_start_failure_closes_connection_and_is_redacted(monkeypatch):
    connection = _Connection(close_error=True)

    def fail(_thread):
        raise RuntimeError("monitor start " + _KEY)

    with monkeypatch.context() as scope:
        scope.setattr(threading.Thread, "start", fail)
        with pytest.raises(OpenAIProviderError, match="request failed: RuntimeError") as exc:
            _stream(connection)
    assert _KEY not in str(exc.value) and "[REDACTED]" in str(exc.value)
    assert connection.close_calls == 1


@pytest.mark.parametrize("wire, message", [
    (b"data: " + b"x" * _MAX_STREAM_LINE_BYTES, "line exceeded"),
    ((b"data: " + b"x" * 100_000 + b"\n") * 6, "event exceeded"),
    (_event("response.output_text.delta", delta="x" * 150_000) * 2, "output exceeded"),
    (_event("response.refusal.delta", delta="x" * 150_000) * 2, "refusal exceeded"),
], ids=["line", "event", "text", "refusal"])
def test_actual_wire_size_bounds_are_unchanged_and_cleanup_still_runs(wire, message):
    connection = _Connection(_Response(wire))
    with pytest.raises(OpenAIProviderError, match=message):
        _stream(connection)
    assert connection.response.close_calls == connection.close_calls == 1
