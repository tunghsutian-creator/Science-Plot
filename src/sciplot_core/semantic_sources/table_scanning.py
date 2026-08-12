"""Read candidate tables and discover paired curve columns and metadata."""

from __future__ import annotations

import math
from pathlib import Path
import pandas as pd
from sciplot_core.foundation.text_values import clean_text as _clean_text, token as _token
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.paired_curve_data_block import (
    first_paired_curve_data_block,
)
from sciplot_core.semantic_sources.paired_curve_table_metadata import (
    axis_match as _axis_match,
    curve_axis_unit as _curve_axis_unit,
    looks_like_unit as _looks_like_unit,
    preceding_pair_sample as _preceding_pair_sample,
    resolve_adjacent_pair_row_roles,
)
from sciplot_core.semantic_sources.panalytical_scan_metadata import (
    resolve_panalytical_scan_metadata,
)
from sciplot_core.semantic_sources.table_candidate_sources import (
    read_candidate_tables as _read_candidate_tables,
    read_raw_table_normalized,
)

_read_raw_table_normalized = read_raw_table_normalized


def _sample_from_interval_metadata(raw: pd.DataFrame, fallback: str) -> str:
    for row_index in range(min(12, raw.shape[0])):
        row = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        if row and _token(row[0]) == "test" and len(row) > 1 and row[1]:
            return row[1]
    return fallback


def _rheology_test_sections(
    raw: pd.DataFrame,
    *,
    fallback: str,
) -> list[tuple[str, pd.DataFrame]]:
    """Split a concatenated instrument export into authoritative test blocks.

    Anton Paar text exports can contain several complete ``Test:`` sections in
    one file.  A filename is only a container label in that format; the test
    metadata inside each block owns sample identity.
    """

    starts = [
        row_index
        for row_index in range(raw.shape[0])
        if raw.shape[1] and _token(raw.iat[row_index, 0]) == "test"
    ]
    if not starts:
        return [(fallback, raw)]
    sections: list[tuple[str, pd.DataFrame]] = []
    for index, start in enumerate(starts):
        stop = starts[index + 1] if index + 1 < len(starts) else raw.shape[0]
        block = raw.iloc[start:stop].dropna(how="all")
        sample = _sample_from_interval_metadata(block, fallback)
        sections.append((sample, block))
    return sections


def _find_column(headers: list[str], candidates: tuple[str, ...]) -> int:
    for index, header in enumerate(headers):
        token = _token(header)
        if any(candidate in token for candidate in candidates):
            return index
    raise ValueError(f"Could not find any expected column: {', '.join(candidates)}")


def _unit_for(units: list[str], index: int, fallback: str) -> str:
    if index < len(units):
        unit = _clean_text(units[index]).strip("[]() ")
        if unit:
            return format_unit_label(unit)
    return format_unit_label(fallback)


def _float(value: object, *, decimal_comma: bool = False) -> float | None:
    text = (
        _clean_text(value).replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    )
    if not text:
        return None
    if decimal_comma:
        if "," in text and "." in text:
            text = text.replace(".", "")
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _unit_row_score(raw: pd.DataFrame, row_index: int, columns: tuple[int, ...]) -> int:
    if row_index >= raw.shape[0]:
        return -1
    if columns and all(_float(raw.iat[row_index, column]) is not None for column in columns):
        return -1
    return sum(1 for column in columns if _looks_like_unit(raw.iat[row_index, column]))


def _scan_curve_series_table(
    raw: pd.DataFrame,
    *,
    x_aliases: tuple[str, ...],
    y_aliases: tuple[str, ...],
    x_label: str,
    y_label: str,
    default_x_unit: str,
    default_y_unit: str,
    sample_prefix: str,
) -> list[CurveSeriesPayload]:
    best: list[CurveSeriesPayload] = []
    for header_index in range(max(0, raw.shape[0] - 2)):
        row_values = raw.iloc[header_index].tolist()
        pairs: list[tuple[int, int]] = []
        for x_index, value in enumerate(row_values[:-1]):
            if not _axis_match(value, x_aliases):
                continue
            search_stop = min(x_index + 5, raw.shape[1])
            for y_index in range(x_index + 1, search_stop):
                if _axis_match(row_values[y_index], y_aliases):
                    pairs.append((x_index, y_index))
                    break
        if not pairs:
            continue
        first_extra = header_index + 1
        second_extra = header_index + 2
        preceding_sample_index = header_index - 1
        preceding_samples = (
            {
                x_index: _preceding_pair_sample(
                    raw.iat[preceding_sample_index, x_index],
                    raw.iat[preceding_sample_index, y_index],
                    axis_aliases=(*x_aliases, *y_aliases),
                )
                for x_index, y_index in pairs
            }
            if header_index > 0
            else {}
        )
        preceding_row_has_samples = bool(preceding_samples) and all(
            preceding_samples.values()
        )
        adjacent_rows = tuple(
            (row_index, tuple(raw.iloc[row_index].tolist()))
            for row_index in (first_extra, second_extra)
            if row_index < raw.shape[0]
        )
        unit_row, sample_row, adjacent_samples = resolve_adjacent_pair_row_roles(
            adjacent_rows,
            pairs=tuple(pairs),
            axis_aliases=(*x_aliases, *y_aliases),
        )
        unit_index = unit_row if unit_row is not None else -1
        sample_index = sample_row
        if sample_index is None and preceding_row_has_samples:
            sample_index = preceding_sample_index
        adjacent_metadata_rows = tuple(
            row_index
            for row_index in (unit_row, sample_row)
            if row_index is not None
        )
        if adjacent_metadata_rows:
            data_start = max(adjacent_metadata_rows) + 1
        else:
            first_row_is_numeric_data = any(
                _float(raw.iat[first_extra, x_index]) is not None
                and _float(raw.iat[first_extra, y_index]) is not None
                for x_index, y_index in pairs
                if first_extra < raw.shape[0]
            )
            data_start = header_index + (1 if first_row_is_numeric_data else 2)
        data_block = first_paired_curve_data_block(
            raw,
            data_start=data_start,
            pairs=tuple(pairs),
        )
        candidate_series: list[CurveSeriesPayload] = []
        for series_index, (x_index, y_index) in enumerate(pairs, start=1):
            points: list[tuple[float, float]] = []
            excluded_empty_pair_count = 0
            excluded_partial_or_nonnumeric_pair_count = 0
            excluded_nonfinite_pair_count = 0
            for row_index in data_block.rows:
                x_cell = raw.iat[row_index, x_index]
                y_cell = raw.iat[row_index, y_index]
                if not _clean_text(x_cell) and not _clean_text(y_cell):
                    excluded_empty_pair_count += 1
                    continue
                x_value = _float(x_cell, decimal_comma=data_block.decimal_comma)
                y_value = _float(y_cell, decimal_comma=data_block.decimal_comma)
                if x_value is None or y_value is None:
                    excluded_partial_or_nonnumeric_pair_count += 1
                    continue
                if not (math.isfinite(x_value) and math.isfinite(y_value)):
                    excluded_nonfinite_pair_count += 1
                    continue
                points.append((x_value, y_value))
            if not points:
                continue
            instrument_metadata = resolve_panalytical_scan_metadata(
                raw,
                header_index=header_index,
                x_index=x_index,
                y_index=y_index,
                data_start=data_start,
                finite_point_count=len(points),
            )
            if instrument_metadata is None:
                x_unit_evidence = _curve_axis_unit(
                    row_values[x_index],
                    raw.iat[unit_index, x_index] if unit_index >= 0 else "",
                    header_index=header_index,
                    unit_index=unit_index,
                    default=default_x_unit,
                )
                y_unit_evidence = _curve_axis_unit(
                    row_values[y_index],
                    raw.iat[unit_index, y_index] if unit_index >= 0 else "",
                    header_index=header_index,
                    unit_index=unit_index,
                    default=default_y_unit,
                )
            else:
                x_unit_evidence = instrument_metadata.x_unit_evidence
                y_unit_evidence = instrument_metadata.y_unit_evidence
            x_unit, x_unit_detection, x_unit_row_index, x_unit_value = (
                x_unit_evidence
            )
            y_unit, y_unit_detection, y_unit_row_index, y_unit_value = (
                y_unit_evidence
            )
            fallback_sample = sample_prefix if len(pairs) == 1 else f"{sample_prefix} {series_index}"
            if instrument_metadata is not None:
                sample, sample_detection, sample_row_index = (
                    instrument_metadata.sample_evidence(fallback_sample)
                )
            elif sample_index == preceding_sample_index and preceding_row_has_samples:
                sample = preceding_samples[x_index]
                sample_detection = "detected_from_preceding_sample_row"
                sample_row_index: int | None = preceding_sample_index
            elif sample_index is not None:
                sample = adjacent_samples[x_index]
                sample_detection = "detected_from_adjacent_sample_row"
                sample_row_index = sample_index
            else:
                sample = fallback_sample
                sample_detection = "fallback_from_source_table"
                sample_row_index = None
            instrument_diagnostics = (
                instrument_metadata.diagnostics() if instrument_metadata else {}
            )
            candidate_series.append(
                CurveSeriesPayload(
                    sample=sample,
                    x_label=x_label,
                    x_unit=x_unit,
                    y_label=y_label,
                    y_unit=y_unit,
                    points=tuple(points),
                    diagnostics={
                        "source_header_row_index": header_index,
                        "source_x_column_index": x_index,
                        "source_x_header": _clean_text(row_values[x_index]),
                        "source_y_column_index": y_index,
                        "source_y_header": _clean_text(row_values[y_index]),
                        "source_x_unit": x_unit,
                        "source_y_unit": y_unit,
                        "source_x_unit_detection": x_unit_detection,
                        "source_x_unit_detection_row_index": x_unit_row_index,
                        "source_x_unit_detection_value": x_unit_value,
                        "source_y_unit_detection": y_unit_detection,
                        "source_y_unit_detection_row_index": y_unit_row_index,
                        "source_y_unit_detection_value": y_unit_value,
                        "source_sample_detection": sample_detection,
                        "source_sample_row_index": sample_row_index,
                        "source_sample_value": sample,
                        "candidate_row_count": len(data_block.rows),
                        "retained_point_count": len(points),
                        "excluded_empty_pair_count": excluded_empty_pair_count,
                        "excluded_partial_or_nonnumeric_pair_count": excluded_partial_or_nonnumeric_pair_count,
                        "excluded_nonfinite_pair_count": excluded_nonfinite_pair_count,
                        **instrument_diagnostics,
                    },
                )
            )
        if sum(len(series.points) for series in candidate_series) > sum(
            len(series.points) for series in best
        ):
            best = candidate_series
    return best


def _scan_curve_series_source(
    source: Path,
    *,
    x_aliases: tuple[str, ...],
    y_aliases: tuple[str, ...],
    x_label: str,
    y_label: str,
    default_x_unit: str,
    default_y_unit: str,
    sample_prefix: str,
) -> list[CurveSeriesPayload]:
    matches: list[tuple[str, list[CurveSeriesPayload]]] = []
    for sheet_name, raw in _read_candidate_tables(source):
        table_sample_prefix = sheet_name or sample_prefix
        if "__" in table_sample_prefix:
            left, right = table_sample_prefix.rsplit("__", maxsplit=1)
            if left == right:
                table_sample_prefix = right
        series = _scan_curve_series_table(
            raw,
            x_aliases=x_aliases,
            y_aliases=y_aliases,
            x_label=x_label,
            y_label=y_label,
            default_x_unit=default_x_unit,
            default_y_unit=default_y_unit,
            sample_prefix=table_sample_prefix,
        )
        if series:
            matches.append((sheet_name, series))
    if len(matches) > 1:
        names = ", ".join(name for name, _series in matches)
        raise ValueError(
            "More than one source table contains the registered curve axes: "
            f"{names}. Select one table explicitly."
        )
    if not matches:
        return []
    sheet_name, series = matches[0]
    return [
        CurveSeriesPayload(
            sample=item.sample,
            x_label=item.x_label,
            x_unit=item.x_unit,
            y_label=item.y_label,
            y_unit=item.y_unit,
            points=item.points,
            diagnostics={**(item.diagnostics or {}), "source_table": sheet_name},
        )
        for item in series
    ]
