"""Thin CLI adapter to deterministic tasks; no model invocation."""

import json
from pathlib import Path
from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.task_control import (
    inspect_task, resume_task, start_task,
)
from sciplot_core.task_discovery import find_tasks
from sciplot_core.task_contract import TaskControlError


def _object(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text())
    except OSError as cause:
        error = TaskControlError("invalid_json_file", "Provide a readable JSON file path; CLI JSON options do not accept inline objects.")
        error.repair = {"action": "select_json_file", "file": str(resolved), "issues": [{"path": "/", "constraint": "readable_json_file"}]}
        raise error from cause
    except json.JSONDecodeError as cause:
        error = TaskControlError("invalid_json_file", "Correct the JSON syntax at the reported line and column.")
        error.repair = {"action": "correct_json_file", "file": str(resolved),
                        "issues": [{"path": "/", "constraint": "json_syntax",
                                    "line": cause.lineno, "column": cause.colno,
                                    "message": cause.msg}]}
        raise error from cause
    if not isinstance(payload, dict):
        error = TaskControlError("invalid_json_file", "A complete JSON object is required.")
        error.repair = {"action": "correct_json_file", "file": str(resolved),
                        "issues": [{"path": "/", "constraint": "type", "expected": "object"}]}
        raise error
    return payload


def _semantic_intent(args: Any) -> dict[str, Any] | None:
    flags = ("x", "x_header", "y_header", "x_unit", "y", "y_unit", "y_min", "y_max", "secondary_y", "secondary_y_unit",
             "stages", "stage_order", "time_boundary", "temperature_header", "temperature_source", "labels", "marker_every", "interpolation")
    has_flags = any(getattr(args, key, None) is not None for key in flags)
    if args.intent is not None:
        if has_flags:
            raise TaskControlError("invalid_semantic_intent", "Use --intent JSON_FILE or semantic flags, keeping the attachment list unchanged.")
        return _object(args.intent)
    if not has_flags and not args.sources:
        return None
    if not args.x or not args.y:
        raise TaskControlError("invalid_semantic_intent", "Attachment plotting needs --x QUANTITY and --y QUANTITY; original columns, units and row IDs are expanded by the program.")
    intent: dict[str, Any] = {"x": {"quantity": args.x}, "y": {"quantity": args.y}}
    for coordinate in ("x", "y"):
        if getattr(args, coordinate + "_header") is not None:
            intent[coordinate]["header"] = getattr(args, coordinate + "_header")
    for key, coordinate in (("x_unit", "x"), ("y_unit", "y")):
        if getattr(args, key) is not None:
            intent[coordinate]["unit"] = getattr(args, key)
    for name in ("minimum", "maximum"):
        value = getattr(args, "y_min" if name == "minimum" else "y_max")
        if value is not None:
            intent["y"][name] = value
    if args.secondary_y:
        intent["secondary_y"] = {"quantity": args.secondary_y}
        if args.secondary_y_unit:
            intent["secondary_y"]["unit"] = args.secondary_y_unit
    if args.stages:
        intent["stages"] = {"mode": args.stages}
        for source, key in (("stage_order", "order"), ("time_boundary", "boundary")):
            if getattr(args, source) is not None:
                intent["stages"][key] = getattr(args, source)
    elif args.stage_order or args.time_boundary:
        raise TaskControlError("invalid_semantic_intent", "--stage-order and --time-boundary require --stages concatenate.")
    for key in ("temperature_header", "temperature_source", "labels"):
        if getattr(args, key) is not None:
            intent[key] = getattr(args, key)
    display: dict[str, Any] = {}
    if args.marker_every is not None:
        display["marker_every"] = args.marker_every
    if args.interpolation:
        display["interpolation"] = {"method": args.interpolation, "subdivisions": args.interpolation_subdivisions,
                                    "purpose": "display", "boundary": "preserve_gaps"}
    if display:
        intent["display"] = display
    if args.rule_id:
        intent["rule_id"] = args.rule_id
    return intent


def _resume_response(args: Any) -> dict[str, Any]:
    expected = args.expected_operation_id
    if args.accept_preview:
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise TaskControlError("invalid_task_response", "--accept-preview requires the reviewed preview's 64-character --expected-operation-id.")
        return {"accept_preview": True, "expected_operation_id": expected}
    if expected is not None:
        raise TaskControlError("invalid_task_response", "--expected-operation-id is used only with --accept-preview.")
    return {"retry": True} if args.retry else _object(args.response)


def dispatch_task(args: Any) -> int:
    action = args.task_action
    result: dict[str, Any]
    if action == "edit":
        from sciplot_core.cli.dispatch.common_edits import dispatch_common_edit

        return dispatch_common_edit(args)
    if action == "paper":
        from sciplot_core.cli.task_paper import dispatch_paper

        return dispatch_paper(args)
    if action == "continue":
        from sciplot_core.task_saved_work import continue_saved_work

        result = continue_saved_work(args.source, search_roots=args.search_root, tasks_root=args.tasks_root,
                                     target=args.target, figure_id=args.figure)
    elif action == "compare":
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
    elif action == "edit-context":
        from sciplot_core.task_edit_context import edit_context

        result = edit_context(args.target, operations=args.operation, figure_id=args.figure)
    elif action == "table-region":
        from sciplot_core.task_table_region import inspect_table_region

        result = inspect_table_region(args.target, _object(args.query))
    elif action == "find":
        if args.search_root:
            from sciplot_core.task_saved_work import find_saved_work

            result = find_saved_work(args.source, search_roots=args.search_root, tasks_root=args.tasks_root, limit=args.limit)
        else:
            result = find_tasks(args.source, tasks_root=args.tasks_root, limit=args.limit)
    elif action == "start":
        result = start_task(_object(args.request), task_dir=args.task_dir)
    elif action == "create":
        from sciplot_core.task_shortcuts import create_task

        create_options: dict[str, Any] = {}
        if args.xscale is not None:
            create_options["xscale"] = args.xscale
        if args.choose_columns:
            create_options["choose_columns"] = True
        semantic = _semantic_intent(args)
        if semantic is not None:
            create_options.update(intent=semantic, sources=args.sources)
        result = create_task(args.source, rule_id=args.rule_id, template=args.template,
                             profile=args.profile, out=args.out, task_dir=args.task_dir, **create_options)
    elif action == "style":
        from sciplot_core.task_shortcuts import style_task

        result = style_task(args.target, samples=args.sample, all_samples=args.all_samples,
                            width=args.width, color=args.color, figure_id=args.figure, task_dir=args.task_dir)
    elif action == "inspect":
        result = inspect_task(args.target)
    else:
        result = resume_task(args.target, _resume_response(args))
    if action in {"start", "create", "style", "inspect", "resume"} and not args.full:
        from sciplot_core.task_result_projection import compact_task_result

        result = compact_task_result(result)
    _print_json(result)
    return 1 if result.get("status") == "blocked" else 0
