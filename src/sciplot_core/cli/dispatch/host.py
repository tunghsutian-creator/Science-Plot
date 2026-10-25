"""Local host administration never passes through scientific request dispatch."""
from typing import Any


def dispatch_host(args: Any) -> int | None:
    if args.command != "host":
        return None
    from sciplot_core.cli.value_io import _print_json
    from sciplot_core.host_grants.administration import administer

    _print_json(administer(args))
    return 0
