"""Local active-call timing, explicitly separate from external AI and user time."""

from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, ParamSpec


_P = ParamSpec("_P")
_ACTIVE: ContextVar[dict[str, Any] | None] = ContextVar("sciplot_task_clock", default=None)


def observe_phase(root: Path, state: dict[str, Any]) -> None:
    clock = _ACTIVE.get()
    if clock is None:
        return
    now = perf_counter()
    if clock.get("root") not in {None, str(root)}:
        return
    previous = clock.get("phase", "setup")
    totals = clock["phases"]
    totals[previous] = totals.get(previous, 0.0) + now - clock["last"]
    clock.update(root=str(root), phase=state["phase"], last=now)


def finish_timing(state: dict[str, Any]) -> None:
    clock = _ACTIVE.get()
    if clock is None:
        return
    observe_phase(Path(state["task_dir"]), state)
    elapsed = perf_counter() - clock["started"]
    previous = state.get("local_timing", {})
    state["local_timing"] = {
        "scope": "local_active_calls_only; excludes external AI, transport and user waiting",
        "calls": previous.get("calls", 0) + 1,
        "total_seconds": round(previous.get("total_seconds", 0.0) + elapsed, 6),
        "last_call_seconds": round(elapsed, 6),
        "last_call_phases_seconds": {key: round(value, 6) for key, value in clock["phases"].items()},
        "external_model_seconds": None,
    }


def timed_task_call(function: Callable[_P, dict[str, Any]]) -> Callable[_P, dict[str, Any]]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> dict[str, Any]:
        started = perf_counter()
        token = _ACTIVE.set({"started": started, "last": started, "phases": {}})
        try:
            return function(*args, **kwargs)
        finally:
            _ACTIVE.reset(token)
    return run
