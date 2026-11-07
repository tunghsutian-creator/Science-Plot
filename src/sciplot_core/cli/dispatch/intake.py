"""Thin local intake conversion shared with MCP; no browser or second pipeline."""

from typing import Any

from sciplot_core.cli.value_io import _print_json


def dispatch_intake(args: Any) -> int | None:
    if args.command != "intake":
        return None
    from sciplot_core.intake.session_adapter import create_session, prepare_session, preview_session_table

    if args.intake_action == "prepare":
        result = prepare_session(args.source, output_root=args.out, rule_id=args.rule_id)
    elif args.intake_action == "table":
        result = preview_session_table(args.session, group_index=args.group, file_index=args.file, sheet=args.sheet)
    else:
        result = create_session(args.session)
    _print_json(result)
    return 1 if result.get("run_failed") or (result.get("last_run") or {}).get("ready_to_use") is False else 0
