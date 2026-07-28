"""Derive stable sample labels and return renamed immutable curve payloads."""

from __future__ import annotations

from pathlib import Path
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.table_scanning import (
    _read_candidate_tables,
)


def _constant_sample_label(source: Path) -> str | None:
    for _sheet_name, raw in _read_candidate_tables(source):
        for header_index in range(min(raw.shape[0], 32)):
            sample_column = next(
                (
                    index
                    for index, value in enumerate(raw.iloc[header_index].tolist())
                    if _token(value) in {"sample", "samplename"}
                ),
                None,
            )
            if sample_column is None:
                continue
            labels = list(
                dict.fromkeys(
                    _clean_text(raw.iat[row_index, sample_column])
                    for row_index in range(header_index + 1, raw.shape[0])
                    if _clean_text(raw.iat[row_index, sample_column])
                )
            )
            if len(labels) == 1:
                return labels[0]
    return None


def _source_display_sample(source: Path) -> str:
    stem = source.stem.strip()
    if "__" in stem:
        group, _rest = stem.split("__", 1)
        group = group.strip()
        if group:
            return group
    return stem


def _with_series_sample(series: CurveSeriesPayload, sample: str) -> CurveSeriesPayload:
    return CurveSeriesPayload(
        sample=sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=series.y_label,
        y_unit=series.y_unit,
        points=series.points,
        diagnostics=series.diagnostics,
    )


def _intake_group_name(sample: str) -> str | None:
    if "__" not in sample:
        return None
    group, _rest = sample.split("__", 1)
    group = group.strip()
    return group or None
