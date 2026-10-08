"""Register semantic plot commands over the shared local engine."""

from pathlib import Path
from typing import Any


def register_plot_commands(subparsers: Any) -> None:
    parser = subparsers.add_parser("plot", help="Edit persistent scientific documents through semantic patches.")
    actions = parser.add_subparsers(dest="plot_action", required=True)
    for name in ("open", "describe", "create", "patch", "render", "export", "rollback", "decide"):
        action = actions.add_parser(name)
        if name == "open":
            action.add_argument("target", type=Path)
            action.add_argument("--figure", dest="figure_id")
        elif name != "create":
            action.add_argument("plot", type=Path)
        if name in {"create", "patch", "rollback", "decide"}:
            action.add_argument("--request", type=Path, required=True)
        action.add_argument("--json", action="store_true")
        action.add_argument("--socket", type=Path, help="Private local engine socket; defaults to this checkout's engine.")
        action.add_argument("--timeout", type=float, default=600.0)
        action.add_argument("--direct", action="store_true", help="Call the same local engine in this process.")
    serve = actions.add_parser("serve", help="Run the serialized local plot engine in the foreground.")
    serve.add_argument("--socket", type=Path, required=True)
    serve.add_argument("--idle-timeout", type=float, default=900.0)
    serve.add_argument("--request-timeout", type=float, default=600.0)

