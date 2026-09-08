"""Register complete local tasks and the optional MCP transport."""

from pathlib import Path
from typing import Any


def register_task_commands(subparsers: Any) -> None:
    parser = subparsers.add_parser("task", help="Run and resume complete local plotting tasks.")
    actions = parser.add_subparsers(dest="task_action", required=True)
    capabilities = actions.add_parser("capabilities", help="Read task request and response schemas.")
    capabilities.add_argument("--json", action="store_true")
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
    subparsers.add_parser("mcp", help="Run the optional external-AI MCP stdio server.")
