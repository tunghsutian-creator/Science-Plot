"""Bounded, byte-checked parse reuse within one local operation only."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator, ParamSpec, TypeVar

import pandas as pd

from sciplot_core.foundation.file_hashing import file_sha256


@dataclass
class _ReadSession:
    tables: dict[tuple[Any, ...], pd.DataFrame] = field(default_factory=dict)
    bytes_used: int = 0


_CURRENT: ContextVar[_ReadSession | None] = ContextVar("sciplot_table_reads", default=None)
_MAX_BYTES = 32 * 1024 * 1024
_P = ParamSpec("_P")
_R = TypeVar("_R")


@contextmanager
def table_read_session() -> Iterator[None]:
    """Nested owners share parses; nothing survives the outer operation."""
    if _CURRENT.get() is not None:
        yield
        return
    token = _CURRENT.set(_ReadSession())
    try:
        yield
    finally:
        _CURRENT.reset(token)


def with_table_reads(function: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with table_read_session():
            return function(*args, **kwargs)
    return run


def read_table_once(
    path: Path, options: tuple[Any, ...], loader: Callable[[], pd.DataFrame],
    *, expected_sha256: str | None = None,
) -> pd.DataFrame:
    session = _CURRENT.get()
    if session is None and expected_sha256 is None:
        return loader()
    # Re-read actual bytes even on hits. Mtime/size are not scientific identity.
    digest = file_sha256(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Original table changed while reading.")
    key = (str(path.resolve()), digest, *options)
    cached = session.tables.get(key) if session else None
    if cached is not None:
        return cached.copy(deep=True)
    result = loader()
    if file_sha256(path) != digest:
        raise ValueError("Original table changed while reading.")
    if session is None:
        return result
    size = int(result.memory_usage(index=True, deep=True).sum())
    if size <= _MAX_BYTES:
        if session.bytes_used + size > _MAX_BYTES:
            session.tables.clear()
            session.bytes_used = 0
        session.tables[key] = result.copy(deep=True)
        session.bytes_used += size
    return result
