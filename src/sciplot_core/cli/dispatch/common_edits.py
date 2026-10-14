"""Thin CLI dispatch for the deterministic common-edit entry."""

from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.task_common_edits import edit_task


def dispatch_common_edit(args: Any) -> int:
    result = edit_task(args.target, intent=args.intent, palette=args.palette,
                       font_size=args.font_size, font_family=args.font_family,
                       legend_font_size=args.legend_font_size, legend_visible=args.legend_visible,
                       legend_position=args.legend_position, figure_id=args.figure, task_dir=args.task_dir)
    _print_json(result)
    return 1 if result.get("status") == "blocked" else 0
