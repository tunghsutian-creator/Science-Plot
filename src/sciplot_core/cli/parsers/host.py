"""Explicit local host administration; absent from remote tool schemas."""
from typing import Any


def register_host_commands(subparsers: Any) -> None:
    from sciplot_core.host_grants.administration import configure_parser

    parser = subparsers.add_parser("host", help="Manage trusted local scientific executor grants; not available through RPC/MCP.")
    configure_parser(parser)
