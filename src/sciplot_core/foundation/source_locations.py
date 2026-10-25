"""Explicit scoped IO locator port; scientific source identities stay literal."""
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Protocol


class SourceResolver(Protocol):
    def resolve_path(self, original: str | Path, *, expected_sha256: str | None = None,
                     source_id: str | None = None) -> Path: ...

    def literal_path(self, actual: Path) -> str: ...


_SELECTED: ContextVar[SourceResolver | None] = ContextVar("sciplot_selected_source_locator", default=None)


@contextmanager
def source_location_scope(resolver: SourceResolver) -> Iterator[None]:
    """Only trusted host composition installs a resolver; no path infers one."""
    token = _SELECTED.set(resolver)
    try:
        yield
    finally:
        _SELECTED.reset(token)


def selected_source_resolver() -> SourceResolver | None:
    return _SELECTED.get()


def resolve_source_path(original: str | Path, *, expected_sha256: str | None = None,
                        source_id: str | None = None) -> Path:
    resolver = _SELECTED.get()
    return (resolver.resolve_path(original, expected_sha256=expected_sha256, source_id=source_id)
            if resolver is not None else Path(original))


def literal_source_path(actual: Path) -> str:
    resolver = _SELECTED.get()
    return resolver.literal_path(actual) if resolver is not None else str(actual.expanduser().resolve())
