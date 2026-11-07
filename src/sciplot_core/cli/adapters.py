"""Lazily cross the autoplot application boundary."""

from __future__ import annotations

from typing import Any


def run_autoplot(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from sciplot_core.autoplot import run_autoplot as _run_autoplot

    return _run_autoplot(*args, **kwargs)
