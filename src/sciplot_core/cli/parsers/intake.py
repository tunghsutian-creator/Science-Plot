"""Register the local confirmed intake adapter without importing a renderer."""

from pathlib import Path
from typing import Any


def register_intake_commands(subparsers: Any) -> None:
    parser = subparsers.add_parser("intake", help="Confirm original sample groups through local AI requests.")
    actions = parser.add_subparsers(dest="intake_action", required=True)
    prepare = actions.add_parser("prepare", help="Save a source-bound editable request and non-authoritative context.")
    prepare.add_argument("source", type=Path)
    prepare.add_argument("--out", type=Path, required=True, help="Intake session/project root; original sources are never rewritten.")
    prepare.add_argument("--rule", dest="rule_id")
    create = actions.add_parser("create", help="Create and export from the strict request in a confirmed local session.")
    create.add_argument("session", type=Path)
    table = actions.add_parser("table", help="Preview one declared original file/worksheet without creating a project.")
    table.add_argument("session", type=Path)
    table.add_argument("--group", type=int, required=True, help="Zero-based request group index.")
    table.add_argument("--file", type=int, required=True, help="Zero-based file index within that group.")
    table.add_argument("--sheet", help="Exact original worksheet name; otherwise preview the existing reader default.")
    for action in (prepare, create, table):
        action.add_argument("--json", action="store_true")
