"""Opt-in native process reuse; legacy callers retain their cold subprocess path."""

from collections.abc import Callable
from functools import wraps
import subprocess
import sys
from typing import Any, ParamSpec, TypeVar

from .session import NativeRuntimeChanged, NativeWorkerDisconnected, PersistentWorker, active_worker, verified_runtime_identity

_P = ParamSpec("_P")
_T = TypeVar("_T")


def _cold_command(command: list[str], binding: dict[str, str] | None) -> list[str]:
    if binding is None:
        return command
    if command[:3] != [sys.executable, "-m", "sciplot_core.veusz_worker"]:
        raise ValueError("Only the existing native worker entry point accepts project runtime binding.")
    return command[:3] + ["--project-runtime", binding["path"], binding["sha256"], "--"] + command[3:]


def run_cold_worker(command: list[str], *, cold_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
                    **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Retain deliberately cold native commands without losing the selected IO scope."""
    from sciplot_core.project_store.worker_binding import native_runtime_binding

    with native_runtime_binding(command[3:]) as binding:
        runner = subprocess.run if cold_runner is None else cold_runner
        return runner(_cold_command(command, binding), **kwargs)


def run_worker(command: list[str], *, cold_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
               **kwargs: Any) -> subprocess.CompletedProcess[str]:
    worker = active_worker()
    if worker is None:
        return run_cold_worker(command, cold_runner=cold_runner, **kwargs)
    from sciplot_core.project_store.worker_binding import native_runtime_binding

    with native_runtime_binding(command[3:]) as binding:
        _cold_command(command, binding)  # Validate selected-scope entry without changing the pooled argv.
        return worker.run(command, timeout=kwargs.get("timeout", 120), check=kwargs.get("check", False),
                          **({"project_runtime": binding} if binding is not None else {}))


def warm_native_method(method: Callable[_P, _T]) -> Callable[_P, _T]:
    """Activate only a backend's explicitly owned worker; legacy/test subclasses opt out."""
    @wraps(method)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        worker = getattr(args[0], "_worker", None)
        if worker is None:
            return method(*args, **kwargs)
        with worker.activate():
            return method(*args, **kwargs)
    return wrapped


__all__ = ["NativeRuntimeChanged", "NativeWorkerDisconnected", "PersistentWorker", "active_worker", "run_worker", "run_cold_worker",
           "verified_runtime_identity", "warm_native_method"]
