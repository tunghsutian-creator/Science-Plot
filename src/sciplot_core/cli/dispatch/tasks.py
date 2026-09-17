"""Thin CLI adapter to deterministic tasks; no model invocation."""

import json
from pathlib import Path
from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.task_control import (
    inspect_task, resume_task, start_task,
)
from sciplot_core.task_discovery import find_tasks


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text())
    if not isinstance(payload, dict):
        raise ValueError("A complete JSON object is required.")
    return payload


def dispatch_task(args: Any) -> int:
    action = args.task_action
    result: dict[str, Any]
    if action == "compare":
        from sciplot_core.task_comparisons import inspect_comparison, resume_comparison, select_comparison, start_comparison
        from sciplot_core.task_comparison_contract import comparison_request_schema, comparison_selection_schema

        if args.compare_action == "capabilities":
            result = {"request_schema": comparison_request_schema(), "selection_schema": comparison_selection_schema()}
        elif args.compare_action == "start":
            result = start_comparison(_object(args.request), comparison_dir=args.comparison_dir,
                                      base_dir=args.request.expanduser().resolve().parent)
        elif args.compare_action == "select":
            result = select_comparison(args.target, _object(args.selection))
        else:
            result = inspect_comparison(args.target) if args.compare_action == "inspect" else resume_comparison(args.target)
    elif action == "group":
        from sciplot_core.task_groups import inspect_group, resume_group, start_group
        from sciplot_core.task_group_contract import group_request_schema, group_responses_schema

        if args.group_action == "capabilities":
            result = {"request_schema": group_request_schema(), "responses_schema": group_responses_schema()}
        elif args.group_action == "start":
            result = start_group(_object(args.request), group_dir=args.group_dir,
                                 base_dir=args.request.expanduser().resolve().parent)
        elif args.group_action == "inspect":
            result = inspect_group(args.target)
        else:
            responses = json.loads(args.responses.expanduser().read_text()) if args.responses else []
            result = resume_group(args.target, responses)
    elif action == "capabilities":
        from sciplot_core.task_capabilities import task_capabilities

        result = task_capabilities(section=args.section, name=args.name,
                                   expected_contract_sha256=args.expected_contract, full=args.full)
    elif action == "table-region":
        from sciplot_core.task_table_region import inspect_table_region

        result = inspect_table_region(args.target, _object(args.query))
    elif action == "find":
        result = find_tasks(args.source, tasks_root=args.tasks_root, limit=args.limit)
    elif action == "start":
        result = start_task(_object(args.request), task_dir=args.task_dir)
    elif action == "inspect":
        result = inspect_task(args.target)
    else:
        result = resume_task(args.target, _object(args.response))
    if action in {"start", "inspect", "resume"} and not args.full:
        from sciplot_core.task_result_projection import compact_task_result

        result = compact_task_result(result)
    _print_json(result)
    return 1 if result.get("status") == "blocked" else 0
