"""Independent register/dispatch helper for the public ``task paper`` entry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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
            selection = action.add_mutually_exclusive_group(required=True)
            selection.add_argument("--request", type=Path)
            selection.add_argument("--group", type=Path, help="Freeze the current ordered group figures locally.")
            action.add_argument("--paper-dir", type=Path, required=True)
            action.add_argument("--out", type=Path, help="New output directory; required with --group.")
            action.add_argument("--title", help="Optional title for --group selection.")
            action.add_argument("--item-id", action="append", dest="item_ids", help="Select group items in this explicit order.")
        else:
            action.add_argument("target", type=Path)


def dispatch_paper(args: Any) -> int:
    from sciplot_core.task_papers import paper_capabilities, start_paper, inspect_paper, resume_paper

    if args.paper_action == "capabilities":
        result = paper_capabilities(project=args.project, figure_id=args.figure)
    elif args.paper_action == "start":
        if args.group is not None:
            from sciplot_core.task_paper_selection import start_group_paper

            if args.out is None:
                raise ValueError("--group requires a new --out directory.")
            result = start_group_paper(args.group, paper_dir=args.paper_dir, out=args.out,
                                      title=args.title, item_ids=args.item_ids)
        else:
            if args.out is not None or args.title is not None or args.item_ids is not None:
                raise ValueError("--out/--title/--item-id select a current --group; explicit requests retain their closed wire contract.")
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
