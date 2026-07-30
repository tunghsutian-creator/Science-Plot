"""Select and order named render series without depending on a data loader."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar


_T = TypeVar("_T")


class _HasSample(Protocol):
    @property
    def sample(self) -> object: ...


class _HasGroup(Protocol):
    @property
    def group(self) -> object: ...


_SampleT = TypeVar("_SampleT", bound=_HasSample)
_GroupT = TypeVar("_GroupT", bound=_HasGroup)


def _normalized_label(value: object) -> str:
    return str(value).strip().casefold()


def normalized_series_order(
    series_order: Sequence[object] | None,
) -> tuple[str, ...]:
    """Normalize an optional user order while preserving its first spelling."""

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
    available_labels: Sequence[object],
    series_order: Sequence[object] | None,
) -> tuple[str, ...]:
    """Return requested labels that are absent from the available series."""

    requested = normalized_series_order(series_order)
    if not requested:
        return ()
    known = {_normalized_label(label) for label in available_labels}
    return tuple(label for label in requested if _normalized_label(label) not in known)


def _filter_named_items(
    items: Sequence[_T],
    series_include: Sequence[object] | None,
    *,
    label_getter: Callable[[_T], object],
) -> list[_T]:
    requested = normalized_series_order(series_include)
    if not requested:
        return list(items)
    wanted = {_normalized_label(label) for label in requested}
    return [item for item in items if _normalized_label(label_getter(item)) in wanted]


def _reorder_named_items(
    items: Sequence[_T],
    series_order: Sequence[object] | None,
    *,
    label_getter: Callable[[_T], object],
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
        if marker not in consumed_ids:
            ordered.append(item)
    return ordered


def filter_curve_series(
    series_list: Sequence[_SampleT],
    series_include: Sequence[object] | None,
) -> list[_SampleT]:
    """Keep curve models whose ``sample`` label is explicitly selected."""

    return _filter_named_items(
        series_list,
        series_include,
        label_getter=lambda series: series.sample,
    )


def reorder_curve_series(
    series_list: Sequence[_SampleT],
    series_order: Sequence[object] | None,
) -> list[_SampleT]:
    """Order curve models by ``sample`` and retain unspecified series afterward."""

    return _reorder_named_items(
        series_list,
        series_order,
        label_getter=lambda series: series.sample,
    )


def filter_replicate_groups(
    groups: Sequence[_GroupT],
    series_include: Sequence[object] | None,
) -> list[_GroupT]:
    """Keep replicate models whose ``group`` label is explicitly selected."""

    return _filter_named_items(
        groups,
        series_include,
        label_getter=lambda group: group.group,
    )


def reorder_replicate_groups(
    groups: Sequence[_GroupT],
    series_order: Sequence[object] | None,
) -> list[_GroupT]:
    """Order replicate models by ``group`` and retain unspecified groups afterward."""

    return _reorder_named_items(
        groups,
        series_order,
        label_getter=lambda group: group.group,
    )


__all__ = [
    "filter_curve_series",
    "filter_replicate_groups",
    "normalized_series_order",
    "reorder_curve_series",
    "reorder_replicate_groups",
    "unknown_series_order_labels",
]
