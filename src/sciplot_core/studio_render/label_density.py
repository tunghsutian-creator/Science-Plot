"""Measure label density and compact labels or figure size when needed."""

from __future__ import annotations

import re
from dataclasses import replace

from sciplot_core.studio_render.models import (
    IMPACT_POINT_LINE_SUMMARY_KIND,
    StudioSeries,
)


def _label_load(series: list[StudioSeries]) -> dict[str, int]:
    impact_summary = [
        item
        for item in series
        if item.presentation_kind == IMPACT_POINT_LINE_SUMMARY_KIND
    ]
    legend_series = impact_summary or series
    labels = [str(item.label) for item in legend_series]
    return {
        "series_count": len(labels),
        "max_label_length": max((len(label) for label in labels), default=0),
        "total_label_length": sum(len(label) for label in labels),
        "duplicate_count": len(labels) - len(set(labels)),
    }


def _compact_replicate_series_labels(
    series: list[StudioSeries],
) -> tuple[list[StudioSeries], list[dict[str, str]]]:
    """Drop a shared leading descriptor while retaining sample and repeat identity."""

    pattern = re.compile(
        r"^(?P<prefix>.+?)\s+(?P<kind>repeat|replicate|specimen)\s+(?P<index>\d+)$",
        flags=re.IGNORECASE,
    )
    matches = [pattern.fullmatch(str(item.label).strip()) for item in series]
    if len(series) < 5 or any(match is None for match in matches):
        return series, []
    parsed = [match for match in matches if match is not None]
    prefixes = {match.group("prefix").casefold() for match in parsed}
    kinds = {match.group("kind").casefold() for match in parsed}
    if len(prefixes) != 1 or len(kinds) != 1:
        return series, []

    prefix = parsed[0].group("prefix").strip()
    tokens = prefix.split()
    acronym_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if sum(character.isupper() for character in token) >= 2
        ),
        None,
    )
    compact_prefix = (
        " ".join(tokens[acronym_index:]) if acronym_index is not None else prefix
    )
    if "_" in compact_prefix:
        identifier_parts = [part for part in compact_prefix.split("_") if part]
        if len(identifier_parts) > 1 and len(identifier_parts[-1]) <= 8:
            compact_prefix = identifier_parts[-1]
    if len(compact_prefix) >= len(prefix):
        return series, []
    compacted_labels = [
        f"{compact_prefix} {'s' if match.group('kind').casefold() == 'specimen' else 'r'}{match.group('index')}"
        for match in parsed
    ]
    if len(set(compacted_labels)) != len(compacted_labels):
        return series, []
    mapping = [
        {"source_label": item.label, "display_label": display}
        for item, display in zip(series, compacted_labels, strict=True)
    ]
    return [
        replace(item, label=display)
        for item, display in zip(series, compacted_labels, strict=True)
    ], mapping


def _legend_is_dense(series: list[StudioSeries]) -> bool:
    load = _label_load(series)
    return (
        load["series_count"] > 8
        or load["max_label_length"] >= 15
        or load["total_label_length"] >= 90
        or load["duplicate_count"] >= 4
    )


def _wide_size_for_dense_legend(series: list[StudioSeries]) -> str:
    load = _label_load(series)
    if load["series_count"] > 16 or load["total_label_length"] >= 150:
        return "180x55"
    return "120x55"
