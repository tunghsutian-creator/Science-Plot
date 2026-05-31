from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(Generic[K, V]):  # noqa: UP046
    """A tiny thread-safe in-memory LRU cache for sidecar hot paths."""

    def __init__(self, *, maxsize: int) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be positive.")
        self._maxsize = maxsize
        self._items: OrderedDict[K, V] = OrderedDict()
        self._lock = Lock()

    def get(self, key: K) -> V | None:
        with self._lock:
            value = self._items.get(key)
            if value is None:
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: K, value: V) -> None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
            self._items[key] = value
            while len(self._items) > self._maxsize:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
