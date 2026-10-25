"""Opt-in native process reuse; legacy callers retain their cold subprocess path."""

from collections.abc import Callable
from functools import wraps
import subprocess
import sys
from typing import Any, ParamSpec, TypeVar

from .session import NativeRuntimeChanged, NativeWorkerDisconnected, PersistentWorker, active_worker, verified_runtime_identity

_P = ParamSpec("_P")
_T = TypeVar("_T")


def run_worker(command: list[str], *, cold_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
               **kwargs: Any) -> subprocess.CompletedProcess[str]:
    from sciplot_core.project_store.worker_binding import native_runtime_binding

    with native_runtime_binding(command[3:]) as binding:
        if binding is not None and command[:3] != [sys.executable, "-m", "sciplot_core.veusz_worker"]:
            raise ValueError("Only the existing native worker entry point accepts project runtime binding.")
        worker = active_worker()
        if worker is None:
            runner = subprocess.run if cold_runner is None else cold_runner
            actual = (command[:3] + ["--project-runtime", binding["path"], binding["sha256"], "--"] + command[3:]
                      if binding is not None else command)
            return runner(actual, **kwargs)
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


__all__ = ["NativeRuntimeChanged", "NativeWorkerDisconnected", "PersistentWorker", "active_worker", "run_worker",
           "verified_runtime_identity", "warm_native_method"]
