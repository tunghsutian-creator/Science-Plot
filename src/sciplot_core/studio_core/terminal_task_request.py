"""Recognize one canonical task-aware terminal worker request."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.terminal_request import (
    TERMINAL_RENDER_REQUEST_FIELDS,
    normalize_terminal_render_request,
)


def terminal_figure_task_from_request(
    request: dict[str, Any],
) -> FigureTask | None:
    """Return terminal task authority; reject partial or non-canonical v2 input."""

    if "resolved_figure_task" not in request:
        return None
    terminal_request = {
        field: deepcopy(request[field])
        for field in TERMINAL_RENDER_REQUEST_FIELDS
        if field in request
    }
    normalized = normalize_terminal_render_request(
        terminal_request,
        label="Studio terminal render request",
    )
    return FigureTask.from_payload(normalized["resolved_figure_task"])


def is_terminal_worker_request(
    request: dict[str, Any],
    *,
    request_path: Path,
) -> bool:
    """Return whether render/panel_render already selected one terminal plot."""

    if (
        "output" not in request
        or "exports" not in request
        or "_veusz" not in request_path.parts
    ):
        return False
    terminal_request = {
        field: deepcopy(request[field])
        for field in TERMINAL_RENDER_REQUEST_FIELDS
        if field in request
    }
    normalize_terminal_render_request(
        terminal_request,
        label="Studio terminal render request",
    )
    return True


__all__ = ["is_terminal_worker_request", "terminal_figure_task_from_request"]
