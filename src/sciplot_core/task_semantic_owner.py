"""Invocation-local access to the Managed use cases, independent of transport."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, ParamSpec, TypeVar

if TYPE_CHECKING:
    from sciplot_core.plot_engine.service import PlotService

_ManagedRequest = Callable[[dict[str, Any]], dict[str, Any]]
_ManagedDescribe = Callable[[Path], dict[str, Any]]
_ManagedInspectDelivery = Callable[[dict[str, Any], Path | None], dict[str, Any]]
_P = ParamSpec("_P")
_R = TypeVar("_R")


class _Actions(NamedTuple):
    create: _ManagedRequest
    describe: _ManagedDescribe
    deliver: _ManagedRequest
    inspect_delivery: _ManagedInspectDelivery | None


@dataclass
class _Invocation:
    owner: "PlotService | None" = None

    def service(self) -> "PlotService":
        if self.owner is None:
            from sciplot_core.plot_engine.service import public_plot_service

            self.owner = public_plot_service()
        return self.owner


_ACTIONS: ContextVar[_Actions | None] = ContextVar("managed_task_actions", default=None)
_INVOCATION: ContextVar[_Invocation | None] = ContextVar("managed_task_invocation", default=None)


@contextmanager
def local_managed_actions(create: _ManagedRequest, describe: _ManagedDescribe, deliver: _ManagedRequest,
                          inspect_delivery: _ManagedInspectDelivery | None = None) -> Iterator[None]:
    """Accept an owner already opened by the host; it retains its own lifetime."""
    token = _ACTIONS.set(_Actions(create, describe, deliver, inspect_delivery))
    try:
        yield
    finally:
        _ACTIONS.reset(token)


@contextmanager
def _managed_scope() -> Iterator[_Invocation]:
    current = _INVOCATION.get()
    if current is not None:
        yield current
        return
    current = _Invocation()
    token = _INVOCATION.set(current)
    try:
        yield current
    finally:
        _INVOCATION.reset(token)
        if current.owner is not None:
            current.owner.close()


def managed_task_call(callback: Callable[_P, _R]) -> Callable[_P, _R]:
    """One lazy owner serves all use cases entered during one task or group call."""
    @wraps(callback)
    def invoke(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with _managed_scope():
            return callback(*args, **kwargs)

    return invoke


def create_managed(request: dict[str, Any]) -> dict[str, Any]:
    actions = _ACTIONS.get()
    if actions is not None:
        return actions.create(request)
    with _managed_scope() as scope:
        return scope.service().create(request)


def describe_managed(plot: Path) -> dict[str, Any]:
    actions = _ACTIONS.get()
    if actions is not None:
        return actions.describe(plot)
    with _managed_scope() as scope:
        return scope.service().describe(plot, description={"scope": "summary"})


def deliver_managed(request: dict[str, Any]) -> dict[str, Any]:
    actions = _ACTIONS.get()
    if actions is not None:
        return actions.deliver(request)
    with _managed_scope() as scope:
        return scope.service().deliver(request)


def inspect_managed_delivery(request: dict[str, Any], *, paper_dir: Path | None = None) -> dict[str, Any]:
    actions = _ACTIONS.get()
    if actions is not None and actions.inspect_delivery is not None:
        return actions.inspect_delivery(request, paper_dir)
    with _managed_scope() as scope:
        return scope.service().inspect_delivery(request, paper_dir=paper_dir)
