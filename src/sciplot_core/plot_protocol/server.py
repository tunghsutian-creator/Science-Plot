"""Serialized local JSON-RPC server; no network listeners or model calls."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import socket
import threading
import time
from typing import Any
from uuid import uuid4

from sciplot_core.plot_protocol.paths import (
    TransportError, lifecycle_lock, prepare_socket, read_owner, remove_owned_socket, write_owner,
)
from sciplot_core.plot_protocol.rpc import (
    MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, ProtocolError, Service, decode, encode, error_response,
    handle, validate_call, validate_params,
)


def make_service() -> Service:
    from sciplot_core.plot_engine.service import PlotService

    return PlotService()


def read_frame(connection: socket.socket, limit: int, *, timeout: float | None = None) -> bytes:
    data = bytearray()
    deadline = time.monotonic() + timeout if timeout is not None else None
    while True:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("The request frame exceeded its total read deadline.")
            connection.settimeout(remaining)
        chunk = connection.recv(min(65536, limit + 1 - len(data)))
        if not chunk:
            raise TransportError("transport_incomplete_frame", "The local connection ended before a complete response.")
        data.extend(chunk)
        if len(data) > limit:
            raise ProtocolError(-32600, "rpc_frame_too_large", f"JSON-RPC frames must be at most {limit} bytes.")
        if b"\n" in chunk:
            first, trailing = bytes(data).split(b"\n", 1)
            if trailing.strip():
                raise ProtocolError(-32600, "rpc_multiple_frames", "Use one JSON-RPC request per connection.")
            return first


def _remove_stale(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    owner = read_owner(path)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        try:
            probe.connect(str(path))
        except ConnectionRefusedError:
            remove_owned_socket(path, owner["instance_id"])
            return
    raise TransportError("engine_already_running", "The selected socket already has a live local server.")


def serve(socket_path: Path, *, service: Service | None = None, stop_event: threading.Event | None = None,
          idle_timeout: float = 900.0, request_timeout: float = 600.0) -> None:
    path = prepare_socket(socket_path)
    if any(not math.isfinite(value) or not 0 < value <= 86400 for value in (idle_timeout, request_timeout)):
        raise ValueError("Engine timeouts must be finite, positive and at most 86400 seconds.")
    with lifecycle_lock(path, "server", timeout=0):
        _remove_stale(path)
        instance_id = uuid4().hex
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            path.chmod(0o600)
            listener.listen(16)
            listener.settimeout(0.2)
            owner = write_owner(path, instance_id)
            try:
                _serve(listener, owner, service, stop_event, idle_timeout, request_timeout)
            finally:
                remove_owned_socket(path, instance_id)


def _serve(listener: socket.socket, owner: dict[str, Any], service: Service | None,
           stop_event: threading.Event | None, idle_timeout: float, request_timeout: float) -> None:
    owned = service is None
    try:
        last_request = time.monotonic()
        while stop_event is None or not stop_event.is_set():
            if time.monotonic() - last_request >= idle_timeout:
                return
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(request_timeout)
                request_id: str | int | None = None
                try:
                    request = decode(read_frame(connection, MAX_REQUEST_BYTES, timeout=request_timeout))
                    request_id, method, params = validate_call(request)
                    if method == "engine.ping":
                        if params:
                            raise ProtocolError(-32602, "invalid_rpc_params", "engine.ping accepts no parameters.")
                        response = {"jsonrpc": "2.0", "id": request_id, "result": owner}
                    else:
                        validate_params(method, params)
                        if service is None:
                            service = make_service()
                        response = handle(service, request)
                except Exception as exc:
                    response = error_response(request_id, exc)
                try:
                    payload = encode(response)
                    if len(payload) > MAX_RESPONSE_BYTES:
                        payload = encode(error_response(request_id, ProtocolError(
                            -32000, "rpc_response_too_large", "Local response exceeds the transport limit; inspect the durable plot receipt.")))
                    connection.sendall(payload)
                except (OSError, ValueError):
                    # A caller losing its connection never cancels or replays work.
                    # PlotService owns the durable outcome and idempotency record.
                    pass
            last_request = time.monotonic()
    finally:
        if owned and service is not None:
            close = getattr(service, "close", None)
            if close is not None:
                close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--idle-timeout", type=float, default=900.0)
    parser.add_argument("--request-timeout", type=float, default=600.0)
    args = parser.parse_args()
    serve(args.socket, idle_timeout=args.idle_timeout, request_timeout=args.request_timeout)


if __name__ == "__main__":
    main()
