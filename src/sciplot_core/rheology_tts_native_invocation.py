"""Scoped native dispatch and complete renderer fact observation."""
from __future__ import annotations

from pathlib import Path
from typing import Any
# The creator owns this scoped observation; it never turns an exception into a
# successful OS exit. A missing observation after hard exit remains unknown.
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from collections.abc import Callable, Iterator


@dataclass
class NativeInvocationObservation:
    dispatch_entered: bool = False
    owned_invocation_closed: bool = True


_NATIVE_OBSERVATION: ContextVar[NativeInvocationObservation | None] = ContextVar("tts_native_observation", default=None)
_NATIVE_RESULT: ContextVar[Callable[[dict[str, Any], Path, dict[str, Any]], None] | None] = ContextVar("tts_native_result", default=None)


@contextmanager
def observe_native_creation(callback: Callable[[dict[str, Any], Path, dict[str, Any]], None] | None = None) -> Iterator[NativeInvocationObservation]:
    observation = NativeInvocationObservation()
    token = _NATIVE_OBSERVATION.set(observation)
    result_token = _NATIVE_RESULT.set(callback)
    try:
        yield observation
    finally:
        _NATIVE_RESULT.reset(result_token)
        _NATIVE_OBSERVATION.reset(token)


def native_result_received(compiled: dict[str, Any], out: Path, result: dict[str, Any]) -> None:
    callback = _NATIVE_RESULT.get()
    if callback is not None:
        callback(compiled, out, result)



def current_native_observation() -> NativeInvocationObservation | None:
    return _NATIVE_OBSERVATION.get()
