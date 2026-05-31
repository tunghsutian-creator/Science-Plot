from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from src.data_loader import CurveSeries, ReplicateGroup

_T = TypeVar("_T")


def _normalized_label(value: str) -> str:
    return value.strip().casefold()


def normalized_series_order(series_order: Sequence[str] | None) -> tuple[str, ...]:
    if not series_order:
        return ()
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in series_order:
        label = str(item).strip()
        if not label:
            continue
        key = _normalized_label(label)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(label)
    return tuple(cleaned)


def unknown_series_order_labels(
    available_labels: Sequence[str],
    series_order: Sequence[str] | None,
) -> tuple[str, ...]:
    requested = normalized_series_order(series_order)
    if not requested:
        return ()
    known = {_normalized_label(label) for label in available_labels}
    return tuple(label for label in requested if _normalized_label(label) not in known)


def _reorder_named_items(  # noqa: UP047
    items: Sequence[_T],
    series_order: Sequence[str] | None,
    *,
    label_getter: Callable[[_T], str],
) -> list[_T]:
    requested = normalized_series_order(series_order)
    if not requested:
        return list(items)

    by_label: dict[str, list[_T]] = {}
    for item in items:
        key = _normalized_label(label_getter(item))
        by_label.setdefault(key, []).append(item)

    ordered: list[_T] = []
    consumed_ids: set[int] = set()
    for requested_label in requested:
        for item in by_label.get(_normalized_label(requested_label), []):
            marker = id(item)
            if marker in consumed_ids:
                continue
            ordered.append(item)
            consumed_ids.add(marker)

    for item in items:
        marker = id(item)
        if marker in consumed_ids:
            continue
        ordered.append(item)
    return ordered


def reorder_curve_series(
    series_list: Sequence[CurveSeries],
    series_order: Sequence[str] | None,
) -> list[CurveSeries]:
    return _reorder_named_items(series_list, series_order, label_getter=lambda series: series.sample)


def reorder_replicate_groups(
    groups: Sequence[ReplicateGroup],
    series_order: Sequence[str] | None,
) -> list[ReplicateGroup]:
    return _reorder_named_items(groups, series_order, label_getter=lambda group: group.group)


__all__ = [
    "normalized_series_order",
    "reorder_curve_series",
    "reorder_replicate_groups",
    "unknown_series_order_labels",
]
