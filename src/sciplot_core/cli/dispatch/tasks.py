"""Thin CLI adapter to deterministic tasks; no model invocation."""

import json
from pathlib import Path
from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.task_control import (
    inspect_task, resume_task, start_task, task_request_schema, task_response_schema,
)
from sciplot_core.task_discovery import find_tasks


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text())
    if not isinstance(payload, dict):
        raise ValueError("A complete JSON object is required.")
    return payload


def dispatch_task(args: Any) -> int:
    action = args.task_action
    if action == "capabilities":
        result = {"kind": "sciplot_task_capabilities", "version": 1,
                  "request_schema": task_request_schema(),
                  "response_schema": task_response_schema(),
                  "model_configuration_required": False}
    elif action == "find":
        result = find_tasks(args.source, tasks_root=args.tasks_root, limit=args.limit)
    elif action == "start":
        result = start_task(_object(args.request), task_dir=args.task_dir)
    elif action == "inspect":
        result = inspect_task(args.target)
    else:
        result = resume_task(args.target, _object(args.response))
    _print_json(result)
    return 1 if result.get("status") == "blocked" else 0
