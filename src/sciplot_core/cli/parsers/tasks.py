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
    subparsers.add_parser("mcp", help="Run the optional external-AI MCP stdio server.")
