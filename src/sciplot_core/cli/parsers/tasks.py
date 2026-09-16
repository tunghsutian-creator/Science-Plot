"""Register complete local tasks and the optional MCP transport."""

from pathlib import Path
from typing import Any


def register_task_commands(subparsers: Any) -> None:
    parser = subparsers.add_parser("task", help="Run and resume complete local plotting tasks.")
    actions = parser.add_subparsers(dest="task_action", required=True)
    capabilities = actions.add_parser("capabilities", help="Read the small task capability index, or a requested schema.")
    capabilities.add_argument("--json", action="store_true")
    capabilities.add_argument("--section", choices=("request", "response", "operations", "table_region"))
    capabilities.add_argument("--name", help="One action, response field or operation from the capability index.")
    capabilities.add_argument("--expected-contract", help="Reject schemas from a different capability fingerprint.")
    capabilities.add_argument("--full", action="store_true", help="Read all task schemas with repeated definitions factored out.")
    region = actions.add_parser("table-region", help="Read a source-bound original cell rectangle; read-only.")
    region.add_argument("target", type=Path)
    region.add_argument("--query", type=Path, required=True)
    region.add_argument("--json", action="store_true")
    find = actions.add_parser("find", help="Find recorded creation tasks by exact original source path; read-only.")
    find.add_argument("source", type=Path)
    find.add_argument("--tasks-root", type=Path, help="Task-history directory; default is SOURCE_PARENT/.sciplot/tasks.")
    find.add_argument("--limit", type=int, default=20)
    find.add_argument("--json", action="store_true")
    start = actions.add_parser("start", help="Execute a complete structured request locally.")
    start.add_argument("--request", type=Path, required=True)
    start.add_argument("--task-dir", type=Path)
    start.add_argument("--json", action="store_true")
    for name in ("inspect", "resume"):
        action = actions.add_parser(name)
        action.add_argument("target", type=Path)
        action.add_argument("--json", action="store_true")
        if name == "resume":
            action.add_argument("--response", type=Path, required=True)
    group = actions.add_parser("group", help="Run an explicit experiment list and review all native figures together.")
    group_actions = group.add_subparsers(dest="group_action", required=True)
    for name in ("capabilities", "start", "inspect", "resume"):
        action = group_actions.add_parser(name)
        action.add_argument("--json", action="store_true")
        if name == "start":
            action.add_argument("--request", type=Path, required=True)
            action.add_argument("--group-dir", type=Path, required=True)
        elif name in {"inspect", "resume"}:
            action.add_argument("target", type=Path)
            if name == "resume":
                action.add_argument("--responses", type=Path, help="JSON array of item/task-bound answers. Omit to continue pending work.")
    compare = actions.add_parser("compare", help="Compare independent native alternatives from one saved figure, then select one.")
    compare_actions = compare.add_subparsers(dest="compare_action", required=True)
    for name in ("capabilities", "start", "inspect", "resume", "select"):
        action = compare_actions.add_parser(name)
        action.add_argument("--json", action="store_true")
        if name == "start":
            action.add_argument("--request", type=Path, required=True)
            action.add_argument("--comparison-dir", type=Path, required=True)
        elif name != "capabilities":
            action.add_argument("target", type=Path)
            if name == "select":
                action.add_argument("--selection", type=Path, required=True)
    subparsers.add_parser("mcp", help="Run the optional external-AI MCP stdio server.")
