"""Thin CLI dispatch for the deterministic common-edit entry."""

from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.task_common_edits import edit_task


def dispatch_common_edit(args: Any) -> int:
    from sciplot_core.plot_engine.errors import EngineError

    labels, visible = {}, {}
    for selector, alias in args.rename_series or []:
        if selector in labels:
            raise EngineError("common_edit_invalid", "Rename each source selector once per intent.")
        labels[selector] = alias
    for selectors, value in ((args.hide_series or [], False), (args.show_series or [], True)):
        for selector in selectors:
            if selector in visible:
                raise EngineError("common_edit_invalid", "Set each source selector's visibility once per intent.")
            visible[selector] = value
    result = edit_task(args.target, intent=args.intent, palette=args.palette,
                       font_size=args.font_size, font_family=args.font_family,
                       legend_font_size=args.legend_font_size, legend_visible=args.legend_visible,
                       legend_columns=args.legend_columns,
                       legend_position=args.legend_position, series_labels=labels or None,
                       series_visibility=visible or None, figure_id=args.figure, task_dir=args.task_dir)
    _print_json(result)
    return 1 if result.get("status") == "blocked" else 0
