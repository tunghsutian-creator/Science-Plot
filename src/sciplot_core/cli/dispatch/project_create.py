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
    result = create_project(args.target, expected_plan=expected, output_dir=args.out)
    _print_json(result)
    return 0 if result["status"] == "created" else 1


__all__ = ["dispatch_project_create"]
