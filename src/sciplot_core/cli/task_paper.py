"""Independent register/dispatch helper for the public ``task paper`` entry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sciplot_core.task_papers import paper_capabilities, start_paper, inspect_paper, resume_paper


def register_paper_commands(task_actions: Any) -> None:
    parser = task_actions.add_parser("paper", help="Package exact selected figures across saved projects in paper order.")
    actions = parser.add_subparsers(dest="paper_action", required=True)
    for name in ("capabilities", "start", "inspect", "resume"):
        action = actions.add_parser(name)
        action.add_argument("--json", action="store_true")
        if name == "capabilities":
            action.add_argument("--project", type=Path, help="Read a selected figure's exact current version.")
            action.add_argument("--figure", help="Exact registered figure_id; required with --project.")
        elif name == "start":
            action.add_argument("--request", type=Path, required=True)
            action.add_argument("--paper-dir", type=Path, required=True)
        else:
            action.add_argument("target", type=Path)


def dispatch_paper(args: Any) -> int:
    if args.paper_action == "capabilities":
        result = paper_capabilities(project=args.project, figure_id=args.figure)
    elif args.paper_action == "start":
        request = args.request.expanduser().resolve()
        result = start_paper(json.loads(request.read_text(encoding="utf-8")), paper_dir=args.paper_dir, base_dir=request.parent)
    elif args.paper_action == "inspect":
        result = inspect_paper(args.target)
    else:
        result = resume_paper(args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") == "blocked" else 0


def main() -> int:
    """Runnable equivalent while the shared task CLI composes this helper."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="task_action", required=True)
    register_paper_commands(actions)
    args = parser.parse_args()
    try:
        return dispatch_paper(args)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason_code": getattr(exc, "reason_code", "paper_request_failed"), "message": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
