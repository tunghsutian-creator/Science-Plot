"""Normalize only explicit mechanical replicate identities."""

from __future__ import annotations

import re
from collections import Counter

from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.series_labels import _with_series_sample


_EXPLICIT_REPLICATE = re.compile(
    r"^(?P<group>.+?)[\s_-]+(?P<replicate>repeat|replicate|specimen)"
    r"[\s_-]*(?P<number>\d+)\s*$",
    flags=re.IGNORECASE,
)


def explicit_mechanical_replicate_identity(
    sample: str,
) -> tuple[str, str] | None:
    """Return an explicit group/replicate pair without guessing from numbers."""

    label = str(sample).strip()
    if "__" in label:
        group, replicate = (part.strip() for part in label.split("__", 1))
        if group and replicate:
            return group, replicate
        return None
    match = _EXPLICIT_REPLICATE.fullmatch(label)
    if match is None:
        return None
    group = match.group("group").strip(" _-")
    if not group:
        return None
    replicate = f"{match.group('replicate').casefold()} {match.group('number')}"
    return group, replicate


def normalize_explicit_mechanical_replicates(
    series_list: list[CurveSeriesPayload],
) -> list[CurveSeriesPayload]:
    """Group a label only when at least two curves declare the same group."""

    identities = [
        explicit_mechanical_replicate_identity(series.sample) for series in series_list
    ]
    counts = Counter(
        group.casefold()
        for identity in identities
        if identity is not None
        for group, _replicate in (identity,)
    )
    canonical_groups: dict[str, str] = {}
    normalized: list[CurveSeriesPayload] = []
    for series, identity in zip(series_list, identities, strict=True):
        if identity is None or counts[identity[0].casefold()] < 2:
            normalized.append(series)
            continue
        group, replicate = identity
        group = canonical_groups.setdefault(group.casefold(), group)
        diagnostics = {
            **(series.diagnostics or {}),
            "source_sample": series.sample,
            "replicate_group": group,
            "replicate_label": replicate,
            "replicate_identity_source": (
                "double_underscore"
                if "__" in series.sample
                else "explicit_label_suffix"
            ),
        }
        renamed = _with_series_sample(series, f"{group}__{replicate}")
        normalized.append(
            CurveSeriesPayload(
                sample=renamed.sample,
                x_label=renamed.x_label,
                x_unit=renamed.x_unit,
                y_label=renamed.y_label,
                y_unit=renamed.y_unit,
                points=renamed.points,
                diagnostics=diagnostics,
            )
        )
    return normalized


__all__ = [
    "explicit_mechanical_replicate_identity",
    "normalize_explicit_mechanical_replicates",
]
