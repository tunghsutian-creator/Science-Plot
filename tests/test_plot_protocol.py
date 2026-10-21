"""The semantic transports cannot reinterpret, duplicate or conceal a request."""

from __future__ import annotations

from socket_fixture_helpers import socket_directory

import json
import os
import signal
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, ClassVar, Self

import pytest

from sciplot_core.plot_protocol import client, rpc, server
from sciplot_core.plot_protocol.paths import TransportError, prepare_socket, read_owner


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path | None, dict[str, Any]]] = []
        self.active = 0
        self.maximum_active = 0

    def _call(self, method: str, plot: Path | None = None, request: dict[str, Any] | None = None) -> dict[str, Any]:
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            self.calls.append((method, plot, request or {}))
            return {"status": "ready", "method": method, "pid": os.getpid(), "request": request or {}}
        finally:
            self.active -= 1

    def open(self, target: Path, figure_id: str | None = None) -> dict[str, Any]:
        return self._call("open", target, {"figure_id": figure_id})

    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("create", request=request)

    def describe(self, plot: Path) -> dict[str, Any]:
        return self._call("describe", plot)

    def patch(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("patch", plot, request)

    def resume(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("resume", plot, request)

    def render(self, plot: Path) -> dict[str, Any]:
        return self._call("render", plot)

    def export(self, plot: Path) -> dict[str, Any]:
        return self._call("export", plot)

    def rollback(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("rollback", plot, request)

    def decide(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("decide", plot, request)


@pytest.fixture
def engine() -> Iterator[tuple[Path, FakeService]]:
    with socket_directory(prefix="spp-", dir="/tmp", endpoints=("engine.sock", "socket")) as temporary:
        path = Path(temporary) / "engine.sock"
        service = FakeService()
        stop = threading.Event()
        thread = threading.Thread(target=server.serve, args=(path,), kwargs={"service": service, "stop_event": stop})
        thread.start()
        try:
            deadline = time.monotonic() + 3
            while not path.with_name("engine.sock.owner.json").exists():
                assert time.monotonic() < deadline
                time.sleep(0.01)
            yield path, service
        finally:
            stop.set()
            thread.join(timeout=3)
            assert not thread.is_alive()


def test_persistent_calls_share_server_and_preserve_semantic_request(engine: tuple[Path, FakeService]) -> None:
    path, service = engine
    request = {"idempotency_key": "unchanged-key", "revision": 4, "operations": [{"op": "set_style", "series": ["E2", "E4"]}]}
    first = client.call("plot.patch", {"plot": "/tmp/plot", "request": request}, socket_path=path, request_id="rpc-one")
    second = client.call("plot.describe", {"plot": "/tmp/plot"}, socket_path=path)
    assert first["pid"] == second["pid"] == read_owner(path)["pid"]
    assert first["request"] == request
    assert service.calls == [("patch", Path("/tmp/plot").resolve(), request), ("describe", Path("/tmp/plot").resolve(), {})]
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("method,params,code", [
    ("python.exec", {"code": "raise SystemExit"}, -32601),
    ("plot.patch", {"plot": "/tmp/plot", "request": {}, "force": True}, -32602),
    ("plot.patch", {"plot": "/tmp/plot"}, -32602),
    ("project.open", {"target": "/tmp/a", "figure_id": []}, -32602),
])
def test_unknown_methods_and_fields_never_reach_service(
    engine: tuple[Path, FakeService], method: str, params: dict[str, Any], code: int,
) -> None:
    path, service = engine
    with pytest.raises(rpc.RemoteError) as error:
        client._exchange(path, {"jsonrpc": "2.0", "id": "invalid", "method": method, "params": params}, 3)
    assert error.value.rpc_code == code
    assert error.value.issues
    assert service.calls == []


@pytest.mark.parametrize("raw", [b'{"jsonrpc":"2.0","id":1,"id":2,"method":"plot.create"}',
                                 b'{"jsonrpc":"2.0","id":1,"params":{"request":NaN}}'])
def test_ambiguous_or_nonfinite_json_rejected_before_service(engine: tuple[Path, FakeService], raw: bytes) -> None:
    path, service = engine
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(path))
        connection.sendall(raw + b"\n")
        result = json.loads(server.read_frame(connection, rpc.MAX_RESPONSE_BYTES))
    assert result["error"]["code"] == -32700
    assert service.calls == []


def test_batch_and_notification_are_explicitly_rejected() -> None:
    service = FakeService()
    for value in ([{"jsonrpc": "2.0", "id": 1, "method": "plot.describe"}],
                  {"jsonrpc": "2.0", "method": "plot.describe", "params": {"plot": "/tmp/a"}}):
        result = rpc.handle(service, value)
        assert result["error"]["code"] == -32600
    assert service.calls == []


def test_cli_and_socket_use_identical_service_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    from sciplot_core import cli

    service = FakeService()
    monkeypatch.setattr(server, "make_service", lambda: service)
    request = {"idempotency_key": "k", "operations": [{"op": "set_style", "width": "0.7pt"}]}
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request))
    result = cli.main(["plot", "patch", "/tmp/semantic", "--request", str(request_file), "--json", "--direct"])
    assert result == 0
    assert json.loads(capsys.readouterr().out)["request"] == request
    assert service.calls == [("patch", Path("/tmp/semantic").resolve(), request)]


def test_uncertain_disconnect_is_not_automatically_replayed() -> None:
    with socket_directory(prefix="spp-", dir="/tmp", endpoints=("engine.sock", "socket")) as temporary:
        path = Path(temporary) / "socket"
        calls: list[dict[str, Any]] = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            listener.listen(1)

            def receive_then_disconnect() -> None:
                connection, _ = listener.accept()
                with connection:
                    calls.append(json.loads(server.read_frame(connection, rpc.MAX_REQUEST_BYTES)))

            thread = threading.Thread(target=receive_then_disconnect)
            thread.start()
            request = {"jsonrpc": "2.0", "id": "same-id", "method": "plot.patch", "params": {
                "plot": "/tmp/plot", "request": {"idempotency_key": "same-key"}}}
            with pytest.raises(TransportError) as error:
                client._exchange(path, request, 2)
            thread.join(timeout=2)
            assert calls == [request]
            assert error.value.reason_code == "transport_outcome_unknown"
            assert error.value.repair is not None
            assert error.value.repair["request_id"] == "same-id"
            assert error.value.repair["action"] == "retry_same_request"
            assert error.value.repair["idempotency_key"] == "same-key"
            assert error.value.repair["automatic_retry"] is False
            assert error.value.repair["next_step"] == {"action": "plot.describe", "plot": "/tmp/plot",
                                                       "description": {"scope": "summary"}}


def test_slow_response_cannot_extend_the_total_exchange_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    sent: list[bytes] = []
    chunks = iter([b'{"jsonrpc":', b'"2.0","id":', b'"same-id",', b'"result":{}}\n'])

    class SlowSocket:
        timeout = 0.0

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def settimeout(self, timeout: float) -> None:
            self.timeout = timeout

        def connect(self, _path: str) -> None:
            pass

        def sendall(self, payload: bytes) -> None:
            sent.append(payload)

        def recv(self, _limit: int) -> bytes:
            delay = 0.04
            if self.timeout < delay:
                clock[0] += self.timeout
                raise TimeoutError("The partial response exhausted the remaining deadline.")
            clock[0] += delay
            return next(chunks)

    monkeypatch.setattr(client.socket, "socket", lambda *_args: SlowSocket())
    monkeypatch.setattr(client.time, "monotonic", lambda: clock[0])
    request = {"jsonrpc": "2.0", "id": "same-id", "method": "plot.patch", "params": {
        "plot": "/tmp/plot", "request": {"idempotency_key": "same-key"}}}
    with pytest.raises(TransportError) as error:
        client._exchange(Path("/tmp/private/engine.sock"), request, 0.1)
    assert error.value.reason_code == "transport_outcome_unknown"
    assert error.value.repair is not None
    assert error.value.repair["request_id"] == "same-id"
    assert error.value.repair["action"] == "retry_same_request"
    assert sent == [rpc.encode(request)]
    assert clock[0] == pytest.approx(0.1)


def test_simultaneous_client_start_and_crash_reconnect_keep_owned_socket() -> None:
    with socket_directory(prefix="spp-", dir="/tmp", endpoints=("engine.sock", "socket")) as temporary:
        path = Path(temporary) / "engine.sock"
        live_pid: int | None = None
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: client.ensure_server(path), range(2)))
            assert results == [path, path]
            first = read_owner(path)
            live_pid = first["pid"]
            assert live_pid != os.getpid()
            assert client._ping(path, 3)["pid"] == live_pid
            # Exercise abrupt death; SIGTERM now owns graceful daemon cleanup.
            os.kill(live_pid, signal.SIGKILL)
            time.sleep(0.2)
            client.ensure_server(path)
            replacement = read_owner(path)
            live_pid = replacement["pid"]
            assert replacement["instance_id"] != first["instance_id"]
            assert client._ping(path, 3)["pid"] == live_pid
        finally:
            if live_pid is not None:
                os.kill(live_pid, signal.SIGTERM)


def test_foreign_or_nonprivate_socket_paths_are_preserved(tmp_path: Path) -> None:
    with socket_directory(prefix="spp-", dir="/tmp", endpoints=("engine.sock", "socket")) as temporary:
        directory = Path(temporary)
        directory.chmod(0o755)
        with pytest.raises(TransportError, match="private directory"):
            prepare_socket(directory / "engine.sock")
        directory.chmod(0o700)
        path = directory / "engine.sock"
        path.write_text("not a socket")
        with pytest.raises(FileNotFoundError):
            server.serve(path, idle_timeout=0.1)
        assert path.read_text() == "not a socket"


def test_domain_issue_and_full_diagnostic_survive_rpc() -> None:
    from sciplot_core.cli.value_io import _cli_runtime_error_payload
    from sciplot_core.mcp_server.errors import error_payload

    class ScientificError(ValueError):
        reason_code = "scientific_patch_required"
        issues: ClassVar[list[dict[str, Any]]] = [{"path": "/operations/0", "constraint": "scientific_gate"}]

    result = rpc.error_response("abc", ScientificError("x" * 5000))
    assert result["id"] == "abc"
    assert len(result["error"]["message"]) <= 360
    assert result["error"]["data"]["reason_code"] == "scientific_patch_required"
    assert result["error"]["data"]["issues"] == ScientificError.issues
    diagnostic = Path(result["error"]["data"]["diagnostics"]["path"])
    try:
        assert json.loads(diagnostic.read_text())["message"] == "x" * 5000
        remote = rpc.RemoteError(result["error"])
        assert _cli_runtime_error_payload(remote)["diagnostics"] == result["error"]["data"]["diagnostics"]
        assert error_payload(remote)["diagnostics"] == result["error"]["data"]["diagnostics"]
    finally:
        diagnostic.unlink()


def test_request_size_is_bounded_before_connect() -> None:
    request = {"jsonrpc": "2.0", "id": 1, "method": "plot.patch", "params": {"request": {"value": "a" * rpc.MAX_REQUEST_BYTES}}}
    with pytest.raises(TransportError) as error:
        client._exchange(Path("/missing/socket"), request, 1)
    assert error.value.reason_code == "rpc_frame_too_large"


def test_cli_create_paths_bind_caller_directory_before_daemon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from sciplot_core import cli

    monkeypatch.chdir(tmp_path)
    service = FakeService()
    monkeypatch.setattr(server, "make_service", lambda: service)
    path = tmp_path / "request.json"
    path.write_text(json.dumps({"idempotency_key": "source", "source": "input.csv", "out": "Visible"}))
    assert cli.main(["plot", "create", "--request", str(path), "--direct", "--json"]) == 0
    assert service.calls[0][2] == {"idempotency_key": "source", "source": str(tmp_path / "input.csv"), "out": str(tmp_path / "Visible")}
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_mcp_semantic_schemas_and_dispatch_share_core(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_task_capabilities import expand

    from sciplot_core.mcp_server.schemas import tool_definitions
    from sciplot_core.mcp_server.services import invoke_owner
    from sciplot_core.plot_document.schema import patch_schema

    tools = {item.name: item for item in tool_definitions()}
    assert expand(tools["sciplot_plot_patch"].input_schema)["properties"]["request"] == patch_schema()
    assert tools["sciplot_plot_patch"].annotations.idempotent_hint is True
    assert tools["sciplot_plot_patch"].annotations.read_only_hint is False
    captured: list[tuple[str, dict[str, Any]]] = []

    def call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        captured.append((method, params))
        return {"status": "committed"}

    monkeypatch.setattr(client, "call", call)
    params = {"plot": "/tmp/plot", "request": {"idempotency_key": "unchanged"}}
    assert invoke_owner("sciplot_plot_patch", params) == {"status": "committed"}
    assert captured == [("plot.patch", params)]


def test_lifecycle_contract_rejects_unknown_and_relative_fields() -> None:
    from sciplot_core.plot_document.errors import DocumentError
    from sciplot_core.plot_engine.contracts import (
        validate_create,
        validate_decide,
        validate_rollback,
    )

    for invalid in ({"source": "ambiguous.csv", "idempotency_key": "k"},
                    {"source": "/tmp/raw.csv", "idempotency_key": "k", "guess_mapping": True}):
        with pytest.raises(DocumentError):
            validate_create(invalid)
    with pytest.raises(DocumentError):
        validate_rollback({"base_revision": True, "target_revision": 0, "idempotency_key": "k"})
    with pytest.raises(DocumentError):
        validate_decide({"decision_id": "d", "base_revision": 1, "accept": "yes"})
    assert validate_decide({"decision_id": "d", "base_revision": 1, "accept": False})["accept"] is False


def test_invalid_cli_json_is_rejected_before_any_service_or_daemon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from sciplot_core import cli

    monkeypatch.setattr(client, "ensure_server", lambda *_args, **_kwargs: pytest.fail("Invalid input started engine"))
    path = tmp_path / "request.json"
    path.write_text('{"idempotency_key":"one","idempotency_key":"two"}')
    assert cli.main(["plot", "patch", "/tmp/plot", "--request", str(path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == "invalid_json"


def test_requests_are_serialized_while_first_mutation_is_running(engine: tuple[Path, FakeService]) -> None:
    path, service = engine
    started, release = threading.Event(), threading.Event()
    original_patch = service.patch

    def slow_patch(plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        started.set()
        assert release.wait(3)
        return original_patch(plot, request)

    service.patch = slow_patch  # type: ignore[method-assign]
    patch = {"jsonrpc": "2.0", "id": 1, "method": "plot.patch", "params": {"plot": "/tmp/plot", "request": {}}}
    describe = {"jsonrpc": "2.0", "id": 2, "method": "plot.describe", "params": {"plot": "/tmp/plot"}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client._exchange, path, patch, 3)
        assert started.wait(2)
        second = pool.submit(client._exchange, path, describe, 3)
        try:
            time.sleep(0.02)
            assert not second.done()
            assert service.calls == []
        finally:
            release.set()
        assert first.result()["method"] == "patch"
        assert second.result()["method"] == "describe"
    assert [entry[0] for entry in service.calls] == ["patch", "describe"]


def test_default_engine_identity_changes_with_build_but_not_bytecode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from sciplot_core.plot_protocol import paths

    package = tmp_path / "src/sciplot_core"
    protocol = package / "plot_protocol"
    protocol.mkdir(parents=True)
    module = protocol / "paths.py"
    module.write_text("version = 1")
    config = tmp_path / "pyproject.toml"
    config.write_text('[project]\nversion = "1"')
    monkeypatch.setattr(paths, "__file__", str(module))
    paths.runtime_fingerprint.cache_clear()
    try:
        first = paths.runtime_fingerprint()
        (package / "__pycache__").mkdir()
        (package / "__pycache__/module.pyc").write_bytes(b"cache")
        paths.runtime_fingerprint.cache_clear()
        assert paths.runtime_fingerprint() == first
        module.write_text("version = 2")
        assert paths.runtime_fingerprint() == first  # One running client keeps its build identity.
        paths.runtime_fingerprint.cache_clear()
        updated = paths.runtime_fingerprint()
        assert updated != first
        config.write_text('[project]\nversion = "3"')
        paths.runtime_fingerprint.cache_clear()
        assert paths.runtime_fingerprint() != updated
    finally:
        paths.runtime_fingerprint.cache_clear()


def test_startup_ping_loss_does_not_claim_the_plotting_request_was_sent(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise TransportError("transport_outcome_unknown", "ping reply lost", repair={"method": "engine.ping"})

    monkeypatch.setattr(client, "ensure_server", unavailable)
    monkeypatch.setattr(client, "_exchange", lambda *_args: pytest.fail("Startup failure sent a plotting request"))
    params = {"plot": "/tmp/plot", "request": {"plot_id": "original", "base_revision": 3, "idempotency_key": "known"}}
    with pytest.raises(TransportError) as failed:
        client.call("plot.resume", params, request_id="resume-id")
    repair = failed.value.repair
    assert repair["method"] == "plot.resume" and repair["request_id"] == "resume-id"
    assert repair["idempotency_key"] == "known" and repair["base_revision"] == 3
    assert repair["request_sent"] is False and repair["automatic_retry"] is False


@pytest.mark.parametrize("response", [
    {"jsonrpc": "2.0", "id": "foreign", "result": {}},
    {"jsonrpc": "2.0", "id": "known", "result": []},
    {"jsonrpc": "2.0", "id": "known", "error": "invalid"},
    {"jsonrpc": "2.0", "id": "known", "error": {}},
    {"jsonrpc": "2.0", "id": "known", "error": {"code": -32000, "message": "unusable", "data": []}},
])
def test_invalid_response_preserves_original_recovery_binding(response):
    with socket_directory(prefix="spr-invalid-", dir="/tmp", endpoints=("socket",)) as temporary:
        path = Path(temporary) / "socket"
        requests = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            listener.listen(1)

            def reply_once():
                connection, _ = listener.accept()
                with connection:
                    requests.append(rpc.decode(server.read_frame(connection, rpc.MAX_REQUEST_BYTES)))
                    connection.sendall(rpc.encode(response))

            thread = threading.Thread(target=reply_once)
            thread.start()
            request = {"jsonrpc": "2.0", "id": "known", "method": "plot.patch", "params": {
                "plot": "/tmp/plot", "request": {"plot_id": "saved", "idempotency_key": "saved-key", "base_revision": 7}}}
            with pytest.raises(TransportError) as failed:
                client._exchange(path, request, 3)
            thread.join(timeout=3)
            assert not thread.is_alive() and requests == [request]
            assert failed.value.reason_code == "invalid_engine_response"
            repair = failed.value.repair
            assert repair["idempotency_key"] == "saved-key" and repair["base_revision"] == 7
            assert repair["plot_id"] == "saved" and repair["request_sent"] is True
            assert repair["automatic_retry"] is False and repair["next_step"]["action"] == "plot.describe"


def test_resume_cli_rpc_and_mcp_share_one_closed_schema(monkeypatch, tmp_path, capsys):
    from sciplot_core import cli
    from sciplot_core.mcp_server.schemas import tool_definitions
    from sciplot_core.mcp_server.services import invoke_owner
    from sciplot_core.plot_engine.contracts import resume_schema, validate_resume
    from test_task_capabilities import expand

    request = {"plot_id": "saved", "base_revision": 2, "idempotency_key": "original-key"}
    assert validate_resume(request) == request
    service = FakeService()
    monkeypatch.setattr(server, "make_service", lambda: service)
    path = tmp_path / "resume.json"
    path.write_text(json.dumps(request))
    assert cli.main(["plot", "resume", "/tmp/plot", "--request", str(path), "--direct", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["request"] == request
    assert service.calls == [("resume", Path("/tmp/plot").resolve(), request)]
    tool = next(item for item in tool_definitions() if item.name == "sciplot_plot_resume")
    assert expand(tool.input_schema)["properties"]["request"] == resume_schema()
    assert tool.annotations.idempotent_hint and not tool.annotations.read_only_hint
    captured = []
    monkeypatch.setattr(client, "call", lambda method, params: captured.append((method, params)) or {"status": "complete"})
    params = {"plot": "/tmp/plot", "request": request}
    assert invoke_owner("sciplot_plot_resume", params) == {"status": "complete"}
    assert captured == [("plot.resume", params)]


@pytest.mark.parametrize("params", [None, 7, {"plot": "/tmp/plot", "request": None},
                                         {"plot": "/tmp/plot", "request": 7}])
def test_bad_reply_to_malformed_wire_request_keeps_transport_error(params):
    with socket_directory(prefix="spr-malformed-", dir="/tmp", endpoints=("socket",)) as temporary:
        path = Path(temporary) / "socket"
        received = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            listener.listen(1)

            def invalid_reply():
                connection, _ = listener.accept()
                with connection:
                    received.append(rpc.decode(server.read_frame(connection, rpc.MAX_REQUEST_BYTES)))
                    connection.sendall(rpc.encode({"jsonrpc": "2.0", "id": "wrong", "result": {}}))

            thread = threading.Thread(target=invalid_reply)
            thread.start()
            request = {"jsonrpc": "2.0", "id": "original", "method": "plot.patch", "params": params}
            with pytest.raises(TransportError) as failed:
                client._exchange(path, request, 3)
            thread.join(timeout=3)
            assert not thread.is_alive() and received == [request]
            assert failed.value.reason_code == "invalid_engine_response"
            repair = failed.value.repair
            assert repair["request_id"] == "original" and repair["method"] == "plot.patch"
            assert repair["automatic_retry"] is False and repair["request_sent"] is True
            assert "idempotency_key" not in repair
            if isinstance(params, dict):
                assert repair["next_step"]["plot"] == params["plot"]


@pytest.mark.parametrize("value", [None, 7])
def test_public_call_rejects_malformed_request_before_startup(monkeypatch, value):
    monkeypatch.setattr(client, "ensure_server", lambda *_a, **_k: pytest.fail("Invalid request started a daemon"))
    with pytest.raises(rpc.ProtocolError) as failed:
        client.call("plot.patch", {"plot": "/tmp/plot", "request": value})
    assert failed.value.reason_code == "invalid_rpc_params"
