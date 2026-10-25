"""Host administration shared by the canonical CLI and local module entry."""
import argparse
import json
from pathlib import Path
from typing import Any

from .models import EXECUTE_TRANSFORM, SourceScope
from .registry import HostRegistry


def configure_parser(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="host_action", required=True)
    grant = actions.add_parser("grant", help="Explicitly authorize fixed code; this does not sandbox its OS/network access.")
    grant.add_argument("--id", required=True)
    grant.add_argument("--registration", type=Path, required=True)
    grant.add_argument("--action", choices=[EXECUTE_TRANSFORM], required=True)
    grant.add_argument("--source", action="append", required=True, help="SOURCE_ID=/absolute/original/file; repeat for all allowed sources")
    revoke = actions.add_parser("revoke")
    revoke.add_argument("--id", required=True)
    listing = actions.add_parser("list")
    for command in (grant, revoke, listing):
        command.add_argument("--registry", type=Path, help="Explicit local host administration/deployment path; not a plot request field.")
        command.add_argument("--json", action="store_true")


def administer(args: Any) -> dict[str, Any]:
    store = HostRegistry(args.registry) if args.registry is not None else HostRegistry.default()
    if args.host_action == "grant":
        sources = []
        for value in args.source:
            identifier, separator, path = value.partition("=")
            if not separator:
                raise ValueError("--source requires SOURCE_ID=/absolute/file")
            sources.append(SourceScope.local_file(identifier, Path(path)))
        store.grant(args.id, json.loads(args.registration.read_text()), sources, action=args.action)
    elif args.host_action == "revoke":
        store.revoke(args.id)
    return {"kind": "sciplot_host_executor_grants", "registry": str(store.path), "grants": store.registrations(),
            "execution_boundary": "explicit_host_authorization_without_OS_or_network_isolation"}
