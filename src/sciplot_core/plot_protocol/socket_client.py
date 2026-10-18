"""AF_UNIX engine transport independent of the service implementation."""

from __future__ import annotations

import math
import os
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from collections.abc import Callable
from uuid import uuid4

from sciplot_core.plot_protocol.paths import (
    TransportError,
    lifecycle_lock,
    prepare_socket,
    read_owner,
)
from sciplot_core.plot_protocol.rpc import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    RemoteError,
    decode,
    encode,
    validate_call,
    validate_params,
)


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("The local exchange exceeded its total deadline.")
    return remaining


def _recovery(request: dict[str, Any], *, request_sent: bool) -> dict[str, Any]:
    """Keep the known semantic binding; recovery is always an explicit call."""
    params = request.get("params", {})
    params = params if isinstance(params, dict) else {}
    original = params.get("request", {})
    original = original if isinstance(original, dict) else {}
    repair = {"action": "retry_same_request", "method": request["method"], "request_id": request["id"],
              "request_sent": request_sent, "automatic_retry": False,
              "preserve": "Keep the original request and idempotency_key; do not create a new operation.",
              **{key: original[key] for key in ("plot_id", "base_revision", "idempotency_key") if key in original}}
    if "plot" in params:
        repair.update(plot=params["plot"], next_step={"action": "plot.describe", "plot": params["plot"],
                                                     "description": {"scope": "summary"}})
    return repair


def _exchange(path: Path, request: dict[str, Any], timeout: float) -> dict[str, Any]:
    payload = encode(request)
    if len(payload) > MAX_REQUEST_BYTES:
        raise TransportError("rpc_frame_too_large", "The local plot request exceeds 1 MiB; no request was sent.")
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(_remaining_timeout(deadline))
        connection.connect(str(path))
        try:
            connection.settimeout(_remaining_timeout(deadline))
            connection.sendall(payload)
            data = bytearray()
            while True:
                connection.settimeout(_remaining_timeout(deadline))
                chunk = connection.recv(min(65536, MAX_RESPONSE_BYTES + 1 - len(data)))
                if not chunk:
                    raise OSError("Local engine disconnected before its response.")
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise OSError("Local engine response exceeds the transport limit.")
                if b"\n" in chunk:
                    response = decode(bytes(data).split(b"\n", 1)[0])
                    break
        except (OSError, ValueError) as exc:
            raise TransportError("transport_outcome_unknown", "The connection ended without a confirmed local outcome.",
                                 repair=_recovery(request, request_sent=True)) from exc
    if (not isinstance(response, dict) or response.get("jsonrpc") != "2.0"
            or response.get("id") != request["id"] or (("result" in response) == ("error" in response))):
        raise TransportError("invalid_engine_response", "Engine response identity or envelope was invalid; inspect the durable plot outcome.",
                             repair=_recovery(request, request_sent=True))
    if "error" in response:
        error = response["error"]
        if (not isinstance(error, dict) or type(error.get("code")) is not int
                or not isinstance(error.get("message"), str) or not isinstance(error.get("data", {}), dict)):
            raise TransportError("invalid_engine_response", "Engine returned an invalid error envelope.",
                                 repair=_recovery(request, request_sent=True))
        raise RemoteError(error)
    if not isinstance(response["result"], dict):
        raise TransportError("invalid_engine_response", "Engine result must be an object.",
                             repair=_recovery(request, request_sent=True))
    return response["result"]


def _ping(path: Path, timeout: float) -> dict[str, Any]:
    owner = read_owner(path)
    result = _exchange(path, {"jsonrpc": "2.0", "id": uuid4().hex, "method": "engine.ping", "params": {}}, timeout)
    if any(result.get(key) != owner[key] for key in ("pid", "instance_id", "device", "inode")):
        raise TransportError("socket_owner_mismatch", "The active engine does not match the socket ownership record.")
    return result


def ensure_server(socket_path: Path | None = None, *, startup_timeout: float = 15.0,
                  request_timeout: float = 600.0) -> Path:
    path = prepare_socket(socket_path)
    with lifecycle_lock(path, "startup", timeout=startup_timeout):
        if path.exists() or path.is_symlink():
            try:
                _ping(path, request_timeout)
                return path
            except ConnectionRefusedError:
                pass  # The server alone validates and removes its stale socket.
        from sciplot_core.veusz_runtime import veusz_worker_environment

        log = path.with_name(path.name + ".log")
        descriptor = os.open(log, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise TransportError("unsafe_engine_log", "Engine log must be private and owned by this user.")
            process = subprocess.Popen(
                [sys.executable, "-m", "sciplot_core.plot_protocol.server", "--socket", str(path),
                 "--request-timeout", str(request_timeout)],
                stdin=subprocess.DEVNULL, stdout=descriptor, stderr=descriptor, close_fds=True,
                start_new_session=True, env=veusz_worker_environment(), cwd=path.parent,
            )
        finally:
            os.close(descriptor)
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise TransportError("engine_start_failed", "The local engine exited during startup.",
                                     repair={"action": "inspect_diagnostics", "path": str(log)})
            try:
                _ping(path, min(1.0, request_timeout))
                return path
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.05)
        raise TransportError("engine_start_timeout", "The engine did not confirm startup in time; the plotting request was not sent.",
                             repair={"action": "retry_same_request", "path": str(log)})


def prepare_request(method: str, params: dict[str, Any], *, timeout: float,
                    request_id: str | int | None = None) -> dict[str, Any]:
    if not math.isfinite(timeout) or not 0 < timeout <= 86400:
        raise TransportError("invalid_transport_timeout", "Transport timeout must be finite, positive and at most 86400 seconds.")
    request = {"jsonrpc": "2.0", "id": request_id if request_id is not None else uuid4().hex,
               "method": method, "params": params}
    validate_call(request)
    validate_params(method, params)
    try:
        payload = encode(request)
    except (ValueError, TypeError, RecursionError) as exc:
        raise TransportError("invalid_json", "Use finite JSON values in the request; no request was sent.") from exc
    if len(payload) > MAX_REQUEST_BYTES:
        raise TransportError("rpc_frame_too_large", "The local plot request exceeds 1 MiB; no request was sent.")
    return request


def exchange_request(request: dict[str, Any], *, socket_path: Path | None, timeout: float,
                     start_server: Callable[..., Path] | None = None,
                     exchange_call: Callable[[Path, dict[str, Any], float], dict[str, Any]] | None = None) -> dict[str, Any]:
    start = start_server or ensure_server
    exchange = exchange_call or _exchange
    try:
        path = start(socket_path, request_timeout=timeout)
    except TransportError as exc:
        if exc.reason_code not in {"transport_outcome_unknown", "invalid_engine_response", "engine_start_timeout", "engine_start_failed"}:
            raise
        repair = _recovery(request, request_sent=False)
        if exc.repair:
            repair["startup"] = exc.repair
        raise TransportError(exc.reason_code, "The engine did not confirm readiness; the plotting request was not sent.",
                             repair=repair) from exc
    except OSError as exc:
        raise TransportError("engine_unavailable", "The engine could not confirm readiness; the plotting request was not sent.",
                             repair=_recovery(request, request_sent=False)) from exc
    try:
        return exchange(path, request, timeout)
    except OSError as exc:
        raise TransportError("engine_unavailable", "The engine could not be reached; the plotting request was not sent.",
                             repair=_recovery(request, request_sent=False)) from exc


def call(method: str, params: dict[str, Any], *, socket_path: Path | None = None,
         timeout: float = 600.0, request_id: str | int | None = None) -> dict[str, Any]:
    request = prepare_request(method, params, timeout=timeout, request_id=request_id)
    return exchange_request(request, socket_path=socket_path, timeout=timeout)
