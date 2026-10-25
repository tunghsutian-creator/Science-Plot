"""Trusted in-process composition; no request or environment grant switches."""
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from .models import SourceScope, denied
from .registry import HostRegistry

_registry: ContextVar[HostRegistry | None] = ContextVar("sciplot_host_registry", default=None)
_sources: ContextVar[tuple[SourceScope | dict[str, Any], ...]] = ContextVar("sciplot_host_sources", default=())


def host_registry() -> HostRegistry:
    configured = _registry.get()
    return configured if configured is not None else HostRegistry.default()


@contextmanager
def using_host_registry(registry: HostRegistry) -> Iterator[None]:
    """Trusted local application/test composition, never a wire field."""
    token = _registry.set(registry)
    try:
        yield
    finally:
        _registry.reset(token)


@contextmanager
def execution_context(sources: Sequence[dict[str, Any] | SourceScope]) -> Iterator[None]:
    values = tuple(deepcopy(item) for item in sources)
    if len({item.source_id if isinstance(item, SourceScope) else item["source_id"] for item in values}) != len(values):
        denied("host_source_scope_invalid", "The execution source catalog has duplicate identities.")
    token = _sources.set(values)
    try:
        yield
    finally:
        _sources.reset(token)


def dataset_sources(dataset: dict[str, Any]) -> tuple[SourceScope, ...]:
    catalog = {item.source_id if isinstance(item, SourceScope) else item["source_id"]: item for item in _sources.get()}
    selected = []
    for fact in dataset["provenance"]["sources"]:
        declared = catalog.get(fact["source_id"])
        source = declared if isinstance(declared, SourceScope) else SourceScope.of(declared) if declared is not None else None
        if source is None or source.sha256 != fact["sha256"]:
            denied("host_executor_source_denied", "External execution needs the actual bound source catalog, not a request-created permission.")
        assert source is not None
        selected.append(source)
    return tuple(selected)
