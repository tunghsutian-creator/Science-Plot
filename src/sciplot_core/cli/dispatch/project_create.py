"""Adapt a source-bound plan file to the shared native creation service."""

from __future__ import annotations

import json
from typing import Any

from sciplot_core.cli.value_io import _print_json
from sciplot_core.studio_core.project_creation import create_project


def dispatch_project_create(args: Any) -> int:
    expected = json.loads(args.expected_plan.read_text(encoding="utf-8"))
    if not isinstance(expected, dict):
        raise ValueError("--expected-plan requires the complete successful plan JSON.")
    from sciplot_core.task_semantic_owner import local_managed_actions, managed_actions_bound

    if managed_actions_bound():
        result = create_project(args.target, expected_plan=expected, output_dir=args.out)
    else:
        from sciplot_core.plot_protocol.server import make_service

        owner = make_service()
        try:
            with local_managed_actions(owner.create, owner.describe, owner.deliver):
                result = create_project(args.target, expected_plan=expected, output_dir=args.out)
        finally:
            owner.close()
    _print_json(result)
    return 0 if result["status"] == "created" else 1


__all__ = ["dispatch_project_create"]
