"""Thin CLI conversion into the shared local assembly owner."""

import json
from pathlib import Path
from typing import Any

from sciplot_core.cli.value_io import _print_json


def dispatch_composition(args: Any) -> int | None:
    if args.command != "compose":
        return None
    if args.compose_action == "open":
        from sciplot_core.studio_core.runtime import maybe_reexec_with_qt_runtime

        maybe_reexec_with_qt_runtime(["compose", "open", *([str(args.layout)] if args.layout else [])])
        from sciplot_core.panel_assembly.desktop import open_workbench

        return int(open_workbench(args.layout))
    from sciplot_core.panel_assembly.service import compose, composition_capabilities

    if args.compose_action == "capabilities":
        _print_json(composition_capabilities())
        return 0
    request: dict[str, Any] = {"action": args.compose_action, "layout": str(args.layout)}
    if args.compose_action == "new":
        request.update(rows=args.rows, columns=args.columns, width_mm=args.width_mm, height_mm=args.height_mm)
    elif args.compose_action == "apply":
        value = args.operations
        if value.startswith("@"):
            value = Path(value[1:]).expanduser().read_text(encoding="utf-8")
        request.update(operations=json.loads(value), expected_revision=args.expected_revision)
    elif args.compose_action == "inspect":
        request["check_sources"] = args.check_sources
    elif args.compose_action == "export":
        request.update(out=str(args.out), dpi=args.dpi)
    result = compose(request)
    _print_json(result)
    return 0 if result.get("status") not in {"blocked", "failed", "needs_revision"} else 1
