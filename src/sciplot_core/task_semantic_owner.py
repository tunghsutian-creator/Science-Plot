"""Select the active plot owner, or use ordinary task-to-engine RPC."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, NamedTuple

_ManagedRequest = Callable[[dict[str, Any]], dict[str, Any]]
_ManagedDescribe = Callable[[Path], dict[str, Any]]


class _Actions(NamedTuple):
    create: _ManagedRequest
    describe: _ManagedDescribe
    deliver: _ManagedRequest


_MANAGED_LOCAL: ContextVar[_Actions | None] = ContextVar("managed_task_local", default=None)


def managed_actions_bound() -> bool:
    return _MANAGED_LOCAL.get() is not None


@contextmanager
def local_managed_actions(create: _ManagedRequest, describe: _ManagedDescribe, deliver: _ManagedRequest) -> Iterator[None]:
    """Reuse the active plot owner; a serialized RPC request cannot call itself."""
    token = _MANAGED_LOCAL.set(_Actions(create, describe, deliver))
    try:
        yield
    finally:
        _MANAGED_LOCAL.reset(token)


def create_managed(request: dict[str, Any]) -> dict[str, Any]:
    local = _MANAGED_LOCAL.get()
    if local is not None:
        return local.create(request)
    from sciplot_core.plot_protocol.socket_client import call

    return call("plot.create", {"request": request})


def describe_managed(plot: Path) -> dict[str, Any]:
    local = _MANAGED_LOCAL.get()
    if local is not None:
        return local.describe(plot)
    from sciplot_core.plot_protocol.socket_client import call

    return call("plot.describe", {"plot": str(plot), "description": {"scope": "summary"}})


def inspect_managed_publication(plot: Path, *, plot_id: str,
                                revision: int | None = None) -> dict[str, Any]:
    """Observe the selected head in the existing read owner, never start a writer."""
    from sciplot_core.foundation.canonical_paths import canonical_path
    from sciplot_core.plot_engine.errors import EngineError

    plot = canonical_path(plot)
    current = describe_managed(plot)
    if (current.get("plot_type") != "ManagedPlot" or current.get("plot") != str(plot)
            or current.get("plot_id") != plot_id or type(current.get("revision")) is not int
            or revision is not None and current["revision"] != revision):
        raise EngineError("managed_publication_selection_changed",
                          "The observed publication does not identify the exact selected Managed figure.")
    return {key: current[key] for key in ("plot", "plot_id", "revision", "scientific_hash", "presentation_hash",
            "artifact", "export_current", "status", "pending", "changed_inputs")}


def deliver_managed(request: dict[str, Any]) -> dict[str, Any]:
    local = _MANAGED_LOCAL.get()
    if local is not None:
        return local.deliver(request)
    from sciplot_core.plot_protocol.socket_client import call

    return call("plot.deliver", {"request": request})
