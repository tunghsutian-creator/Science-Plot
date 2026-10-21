"""Common plot operation hooks for an exact source-bound native suite figure."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.workflow.native_suite_objects import (
    describe_native_object as describe_native_object,
    resolve_native_object as resolve_native_object,
)


def patch_native_object(target: Path, request: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.workflow.native_suite_transactions import patch_native

    return patch_native(target, request)


def decide_native_object(target: Path, request: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.workflow.native_suite_transactions import decide_native

    return decide_native(target, request)


def resume_native_object(target: Path, request: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.workflow.native_suite_transactions import resume_native

    return resume_native(target, request)


def export_native_object(target: Path) -> dict[str, Any]:
    from sciplot_core.workflow.native_suite_transactions import export_native

    return export_native(target)
