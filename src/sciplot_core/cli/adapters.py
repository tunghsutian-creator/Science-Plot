"""Lazily cross the optional browser and autoplot application boundaries."""

from __future__ import annotations

from typing import Any


def serve_intake(**kwargs: Any) -> None:
    """Keep CLI startup independent of the optional browser adapter."""
    from sciplot_core.intake.browser_app import serve_intake as _serve_intake

    _serve_intake(**kwargs)


def run_autoplot(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from sciplot_core.autoplot import run_autoplot as _run_autoplot

    return _run_autoplot(*args, **kwargs)
