"""Extract parallel swelling-ratio series from structured tabular sources."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.table_scanning import (
    _float,
    _read_candidate_tables,
    _axis_match,
    _scan_curve_series_source,
)

_SWELLING_Y_ALIASES = ("swelling ratio", "ai/a0", "normalized projected area")


def _swelling_time_conversion(header: object) -> tuple[str, float]:
    text = _clean_text(header).casefold().replace("µ", "u")
    if (
        re.search(r"\b(?:s|sec|secs|second|seconds)\b", text)
        or "(s)" in text
        or "[s]" in text
    ):
        return "s", 1.0 / 3600.0
    if (
        re.search(r"\b(?:min|mins|minute|minutes)\b", text)
        or "(min)" in text
        or "[min]" in text
    ):
        return "min", 1.0 / 60.0
    return "h", 1.0


def _source_row_number(value: object) -> int | str:
    try:
        return int(value) + 1
    except (TypeError, ValueError):
        return str(value)


def _contiguous_table_stop(raw: pd.DataFrame, data_start: int) -> int:
    """Stop before a disconnected lower table whose blank separator was dropped."""

    stop = raw.shape[0]
    for row_position in range(data_start + 1, raw.shape[0]):
        try:
            previous = int(raw.index[row_position - 1])
            current = int(raw.index[row_position])
        except (TypeError, ValueError):
            continue
        if current - previous > 1:
            stop = row_position
            break
    return stop


def _nearest_row_label(raw: pd.DataFrame, row_position: int, column: int) -> str:
    if row_position < 0 or row_position >= raw.shape[0]:
        return ""
    for candidate_column in range(column, 0, -1):
        label = _clean_text(raw.iat[row_position, candidate_column])
        if label:
            return label
    return ""


def _clean_swelling_condition(value: object, fallback: str) -> str:
    label = _clean_text(value).replace("_", " ")
    label = re.sub(
        r"^\s*fig(?:ure)?\s*\d+\s*\([^)]+\)\s*:\s*", "", label, flags=re.IGNORECASE
    )
    label = re.sub(r"\s+", " ", label).strip(" :;,-")
    return label or fallback or "Sample"


def _replicate_label(value: object, fallback: int) -> str:
    numeric = _float(value)
    if numeric is not None and numeric.is_integer():
        return str(int(numeric))
    return _clean_text(value) or str(fallback)


def _parallel_swelling_series(
    sheet_name: str, raw: pd.DataFrame
) -> list[CurveSeriesPayload]:
    best: list[CurveSeriesPayload] = []
    for header_index in range(min(raw.shape[0], 32)):
        headers = raw.iloc[header_index].tolist()
        pairs: list[tuple[int, int]] = []
        for x_index, header in enumerate(headers[:-1]):
            if not _axis_match(header, ("time",)):
                continue
            for y_index in range(x_index + 1, min(x_index + 4, raw.shape[1])):
                if _axis_match(headers[y_index], _SWELLING_Y_ALIASES):
                    pairs.append((x_index, y_index))
                    break
        if not pairs:
            continue
        data_start = header_index + 1
        while data_start < raw.shape[0] and not any(
            _float(raw.iat[data_start, x_index]) is not None
            and _float(raw.iat[data_start, y_index]) is not None
            for x_index, y_index in pairs
        ):
            data_start += 1
        if data_start >= raw.shape[0]:
            continue
        data_stop = _contiguous_table_stop(raw, data_start)
        excluded_rows = raw.shape[0] - data_stop
        block_diagnostics: dict[str, Any] = {
            "selection_policy": "contiguous_labeled_swelling_block",
            "source_header_row": _source_row_number(raw.index[header_index]),
            "source_data_row_start": _source_row_number(raw.index[data_start]),
            "source_data_row_end": _source_row_number(raw.index[data_stop - 1]),
            "excluded_disconnected_rows": excluded_rows,
        }
        if excluded_rows:
            block_diagnostics["excluded_source_row_span"] = [
                _source_row_number(raw.index[data_stop]),
                _source_row_number(raw.index[-1]),
            ]
        candidate: list[CurveSeriesPayload] = []
        for series_index, (x_index, y_index) in enumerate(pairs, start=1):
            points: list[tuple[float, float]] = []
            source_unit, factor = _swelling_time_conversion(headers[x_index])
            for row_index in range(data_start, data_stop):
                x_value = _float(raw.iat[row_index, x_index])
                y_value = _float(raw.iat[row_index, y_index])
                if x_value is not None and y_value is not None:
                    points.append((x_value * factor, y_value))
            if not points:
                continue
            condition = _clean_swelling_condition(
                _nearest_row_label(raw, header_index - 2, x_index),
                sheet_name,
            )
            replicate = _replicate_label(
                raw.iat[header_index - 1, x_index] if header_index > 0 else None,
                series_index,
            )
            candidate.append(
                CurveSeriesPayload(
                    sample=f"{condition} replicate {replicate}",
                    x_label="Time",
                    x_unit="h",
                    y_label="Swelling ratio",
                    y_unit="1",
                    points=tuple(points),
                    diagnostics={
                        "source_table": sheet_name,
                        "source_columns": {
                            "x": _clean_text(headers[x_index]),
                            "y": _clean_text(headers[y_index]),
                        },
                        "condition": condition,
                        "replicate": replicate,
                        "time_conversion": {
                            "source_unit": source_unit,
                            "canonical_unit": "h",
                            "factor": factor,
                        },
                        "source_block": block_diagnostics,
                    },
                )
            )
        if sum(len(item.points) for item in candidate) > sum(
            len(item.points) for item in best
        ):
            best = candidate
    return best


def _read_swelling_series_list(source: Path) -> list[CurveSeriesPayload]:
    """Keep labeled swelling observations separate and normalize time to hours."""

    best: list[CurveSeriesPayload] = []
    for sheet_name, raw in _read_candidate_tables(source):
        parallel = _parallel_swelling_series(sheet_name, raw)
        if sum(len(item.points) for item in parallel) > sum(
            len(item.points) for item in best
        ):
            best = parallel
        for header_index in range(min(raw.shape[0], 32)):
            headers = raw.iloc[header_index].tolist()
            sample_column = next(
                (
                    index
                    for index, value in enumerate(headers)
                    if _token(value) in {"sample", "samplename"}
                ),
                None,
            )
            time_column = next(
                (
                    index
                    for index, value in enumerate(headers)
                    if _axis_match(value, ("time",))
                ),
                None,
            )
            swelling_column = next(
                (
                    index
                    for index, value in enumerate(headers)
                    if _axis_match(value, _SWELLING_Y_ALIASES)
                ),
                None,
            )
            if time_column is None or swelling_column is None:
                continue
            data_start = header_index + 1
            data_stop = _contiguous_table_stop(raw, data_start)
            source_unit, factor = _swelling_time_conversion(headers[time_column])
            grouped: dict[str, list[tuple[float, float]]] = {}
            for row_index in range(data_start, data_stop):
                x_value = _float(raw.iat[row_index, time_column])
                y_value = _float(raw.iat[row_index, swelling_column])
                if x_value is None or y_value is None:
                    continue
                sample = (
                    (
                        _clean_text(raw.iat[row_index, sample_column])
                        if sample_column is not None
                        else sheet_name
                    )
                    or sheet_name
                    or "Sample"
                )
                grouped.setdefault(sample, []).append((x_value * factor, y_value))
            candidate = [
                CurveSeriesPayload(
                    sample=sample,
                    x_label="Time",
                    x_unit="h",
                    y_label="Swelling ratio",
                    y_unit="1",
                    points=tuple(points),
                    diagnostics={
                        "source_table": sheet_name,
                        "source_columns": {
                            "x": _clean_text(headers[time_column]),
                            "y": _clean_text(headers[swelling_column]),
                        },
                        "time_conversion": {
                            "source_unit": source_unit,
                            "canonical_unit": "h",
                            "factor": factor,
                        },
                    },
                )
                for sample, points in grouped.items()
                if points
            ]
            if sum(len(item.points) for item in candidate) > sum(
                len(item.points) for item in best
            ):
                best = candidate
    if best:
        return best
    return _scan_curve_series_source(
        source,
        x_aliases=("time",),
        y_aliases=_SWELLING_Y_ALIASES,
        x_label="Time",
        y_label="Swelling ratio",
        default_x_unit="h",
        default_y_unit="1",
        sample_prefix=source.stem,
    )
