"""Bind the intake handler to a loopback-only threaded server."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer

from sciplot_core.intake_server.request_security import (
    _is_loopback_host,
)

from sciplot_core.intake_server.handler import (
    _IntakeHandler,
)


class _IntakeServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name = str(self.server_address[0])
        self.server_port = int(self.server_address[1])

    def __init__(self, server_address: tuple[str, int], output_root: Path):
        if not _is_loopback_host(server_address[0]):
            raise ValueError(
                "SciPlot browser app only binds to localhost/loopback addresses; "
                "remote access requires a separately authenticated service."
            )
        super().__init__(server_address, _IntakeHandler)
        self.output_root = output_root.expanduser().resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
