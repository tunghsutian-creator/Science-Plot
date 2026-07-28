"""Compact torque series labels while preserving immutable payloads."""

from __future__ import annotations

from os.path import commonprefix


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.series_labels import (
    _with_series_sample,
)


def _compact_torque_sample_labels(labels: list[str]) -> list[str]:
    if len(labels) < 2:
        return labels
    prefix = commonprefix(labels)
    separator_index = max(prefix.rfind("-"), prefix.rfind("_"), prefix.rfind(" "))
    if separator_index < 3:
        return labels
    prefix = prefix[: separator_index + 1]
    compacted = [
        label[len(prefix) :] if label.startswith(prefix) else label for label in labels
    ]
    compacted = [
        label or original for label, original in zip(compacted, labels, strict=False)
    ]
    if len(set(compacted)) != len(compacted):
        return labels
    return compacted


def _compact_torque_series_labels(
    series_list: list[CurveSeriesPayload],
) -> list[CurveSeriesPayload]:
    labels = _compact_torque_sample_labels([series.sample for series in series_list])
    return [
        _with_series_sample(series, label)
        for series, label in zip(series_list, labels, strict=False)
    ]
