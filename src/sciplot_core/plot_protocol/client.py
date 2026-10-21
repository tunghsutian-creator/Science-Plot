"""Compatible direct/socket facade; tasks depend only on the AF_UNIX leaf."""
from pathlib import Path
from typing import Any
import socket as socket
import time as time

# Preserve the existing transport test/diagnostic hooks while implementation
# lives in one leaf. The modules are shared, so socket/time fault injection still
# reaches the actual transport; there is no duplicated exchange implementation.
from .socket_client import (
    _exchange as _exchange, _ping as _ping,
    ensure_server as ensure_server, exchange_request, prepare_request,
)
from .rpc import RemoteError, handle


def call(method: str, params: dict[str, Any], *, socket_path: Path | None = None,
         direct: bool = False, timeout: float = 600.0, request_id: str | int | None = None) -> dict[str, Any]:
    request = prepare_request(method, params, timeout=timeout, request_id=request_id)
    if direct:
        from sciplot_core.plot_protocol.server import make_service

        response = handle(make_service(), request)
        if "error" in response:
            raise RemoteError(response["error"])
        result: dict[str, Any] = response["result"]
        return result
    return exchange_request(request, socket_path=socket_path, timeout=timeout,
                            start_server=ensure_server, exchange_call=_exchange)
