"""Trusted local expert entry; deliberately absent from RPC and MCP methods."""
import argparse
import json
from typing import Sequence

from sciplot_core.plot_document.errors import DocumentError
from .administration import administer, configure_parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host-owned executor grants. Authorized scripts run with the host user's OS rights; no sandbox is promised.")
    configure_parser(parser)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(administer(args), sort_keys=True))
        return 0
    except (DocumentError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "refused", "reason_code": getattr(error, "reason_code", "host_registry_invalid"),
                          "message": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
