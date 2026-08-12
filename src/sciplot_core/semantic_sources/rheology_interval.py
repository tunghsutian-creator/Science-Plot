"""Extract rheology interval series from instrument result sections."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd
from sciplot_core.foundation.text_values import clean_text as _clean_text
from sciplot_core.foundation.text_values import token as _token
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.paired_curve_table_metadata import (
    explicit_header_unit as _explicit_header_unit,
    looks_like_unit as _looks_like_unit,
)
from sciplot_core.semantic_sources.rheology_sweep_sources import _sweep_source_files
from sciplot_core.semantic_sources.series_labels import _source_display_sample
from sciplot_core.semantic_sources.table_scanning import (
    _find_column,
    _float,
    _read_raw_table_normalized,
    _sample_from_interval_metadata,
)


def _explicit_interval_units(
    raw: pd.DataFrame,
    *,
    source: Path,
    header_index: int,
    headers: list[str],
    columns: tuple[int, ...],
    expected_units: dict[int, str],
    stop: int,
) -> dict[int, tuple[str, int]]:
    """Resolve one unambiguous explicit unit per selected interval column."""

    evidence: dict[int, list[tuple[str, int]]] = {column: [] for column in columns}
    for column in columns:
        header = headers[column]
        unit = _explicit_header_unit(header) or _terminal_wrapped_unit(header)
        if unit:
            evidence[column].append((unit, header_index))
    for row_index in range(header_index + 1, stop):
        values = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        numeric = [_float(raw.iat[row_index, column]) for column in columns]
        if any(value is not None for value in numeric):
            break
        for column in columns:
            unit = _whole_unit_cell(values[column], expected=expected_units[column])
            if unit:
                evidence[column].append((unit, row_index))

    resolved: dict[int, tuple[str, int]] = {}
    for column in columns:
        declarations = {format_unit_label(unit): row for unit, row in evidence[column]}
        if len(declarations) != 1:
            state = "missing" if not declarations else "ambiguous"
            raise ValueError(
                f"Explicit rheology interval unit is {state} for {headers[column]} "
                f"in {source}."
            )
        unit, row_index = next(iter(declarations.items()))
        resolved[column] = (unit, row_index)
    return resolved


def _terminal_wrapped_unit(value: object) -> str:
    text = _clean_text(value)
    for left, right in (("[", "]"), ("(", ")")):
        if text.endswith(right) and left in text:
            candidate = text.rsplit(left, 1)[1][:-1].strip()
            if candidate and _float(candidate) is None:
                return candidate
    return ""


def _whole_unit_cell(value: object, *, expected: str) -> str:
    text = _clean_text(value)
    wrapped = _terminal_wrapped_unit(text)
    if wrapped and text in {f"[{wrapped}]", f"({wrapped})"}:
        return wrapped
    if _float(text) is None and (
        _looks_like_unit(text) or format_unit_label(text) == format_unit_label(expected)
    ):
        return text
    return ""


def _identity_interval_unit(
    declared: str, expected: str, *, header: str, source: Path
) -> str:
    required = format_unit_label(expected)
    if declared != required:
        raise ValueError(
            f"Unsupported rheology interval unit {declared!r} for {header} in {source}; "
            f"expected identity-equivalent {required!r}."
        )
    return required


def _read_rheology_interval_series(
    source: Path,
    *,
    y_candidates: tuple[str, ...],
    y_label: str,
    y_unit: str,
    preferred_result_tokens: tuple[str, ...] = (),
    raw: pd.DataFrame | None = None,
) -> CurveSeriesPayload:
    raw = (_read_raw_table_normalized(source) if raw is None else raw.copy()).dropna(
        axis=1, how="all"
    )
    result_markers: list[tuple[int, str]] = []
    header_indexes: list[int] = []
    for row_index in range(raw.shape[0]):
        row = [_clean_text(value) for value in raw.iloc[row_index].tolist()]
        first_token = _token(row[0]) if row else ""
        if first_token == "result":
            result_markers.append(
                (row_index, next((value for value in row[1:] if value), ""))
            )
        elif first_token == "intervaldata":
            header_indexes.append(row_index)
    if not header_indexes:
        raise ValueError("Could not find `Interval data` section in rheology export.")

    spans: list[tuple[int, int, str]] = []
    if result_markers:
        first_marker = result_markers[0][0]
        if any(header_index < first_marker for header_index in header_indexes):
            spans.append((-1, first_marker, ""))
        for marker_index, (start, label) in enumerate(result_markers):
            stop = (
                result_markers[marker_index + 1][0]
                if marker_index + 1 < len(result_markers)
                else raw.shape[0]
            )
            spans.append((start, stop, label))
    else:
        spans.append((-1, raw.shape[0], ""))

    result_candidates: list[dict[str, Any]] = []
    for result_index, (start, stop, result_label) in enumerate(spans, start=1):
        result_headers = [
            header_index
            for header_index in header_indexes
            if start < header_index < stop
        ]
        intervals: list[dict[str, Any]] = []
        for interval_index, header_index in enumerate(result_headers, start=1):
            headers = [_clean_text(value) for value in raw.iloc[header_index].tolist()]
            x_index = _find_column(headers, ("time", "时间"))
            y_index = _find_column(headers, y_candidates)
            next_header = (
                result_headers[interval_index]
                if interval_index < len(result_headers)
                else stop
            )
            interval_stop = next_header
            for row_index in range(header_index + 1, next_header):
                first_value = raw.iloc[row_index, 0] if raw.shape[1] else None
                if _token(first_value) in {"intervalanddatapoints", "result"}:
                    interval_stop = row_index
                    break
            units = _explicit_interval_units(
                raw,
                source=source,
                header_index=header_index,
                headers=headers,
                columns=(x_index, y_index),
                expected_units={x_index: "s", y_index: y_unit},
                stop=interval_stop,
            )
            x_unit = _identity_interval_unit(
                units[x_index][0],
                "s",
                header=headers[x_index],
                source=source,
            )
            selected_y_unit = _identity_interval_unit(
                units[y_index][0],
                y_unit,
                header=headers[y_index],
                source=source,
            )
            points: list[tuple[float, float]] = []
            numeric_x_rows = 0
            candidate_rows = 0
            for row_index in range(header_index + 1, interval_stop):
                row = raw.iloc[row_index].tolist()
                x_value = _float(row[x_index] if x_index < len(row) else None)
                y_value = _float(row[y_index] if y_index < len(row) else None)
                if x_value is not None or y_value is not None:
                    candidate_rows += 1
                if x_value is not None and math.isfinite(x_value):
                    numeric_x_rows += 1
                if (
                    x_value is not None
                    and y_value is not None
                    and math.isfinite(x_value)
                    and math.isfinite(y_value)
                ):
                    points.append((x_value, y_value))
            if points:
                intervals.append(
                    {
                        "interval_index": interval_index,
                        "header_index": header_index,
                        "source_header_index": int(raw.index[header_index]),
                        "x_column_index": x_index,
                        "x_column_header": headers[x_index],
                        "y_column_index": y_index,
                        "y_column_header": headers[y_index],
                        "x_unit_row_index": int(raw.index[units[x_index][1]]),
                        "y_unit_row_index": int(raw.index[units[y_index][1]]),
                        "x_unit": x_unit,
                        "y_unit": selected_y_unit,
                        "points": tuple(points),
                        "numeric_x_rows": numeric_x_rows,
                        "candidate_rows": candidate_rows,
                    }
                )
        combined_points = tuple(
            point for interval in intervals for point in interval["points"]
        )
        if not combined_points:
            continue
        normalized_label = _token(result_label)
        preferred = any(
            _token(token) in normalized_label
            for token in preferred_result_tokens
            if _token(token)
        )
        numeric_x_rows = sum(int(interval["numeric_x_rows"]) for interval in intervals)
        result_candidates.append(
            {
                "result_index": result_index,
                "result_label": result_label,
                "preferred": preferred,
                "intervals": intervals,
                "points": combined_points,
                "coverage": len(combined_points) / max(numeric_x_rows, 1),
            }
        )
    if not result_candidates:
        raise ValueError(f"No numeric rheology interval points found in {source}.")

    selected = max(
        result_candidates,
        key=lambda item: (
            int(item["preferred"]),
            float(item["coverage"]),
            len(item["points"]),
            len(item["intervals"]),
            int(item["result_index"]),
        ),
    )
    selected_points = tuple(selected["points"])
    x_deltas = [
        right[0] - left[0]
        for left, right in zip(selected_points, selected_points[1:], strict=False)
    ]
    if x_deltas and all(delta >= 0.0 for delta in x_deltas):
        x_direction = "increasing"
    elif x_deltas and all(delta <= 0.0 for delta in x_deltas):
        x_direction = "decreasing"
    else:
        x_direction = "mixed"
    selected_intervals = selected["intervals"]
    diagnostics = {
        "result_selection_policy": (
            "preferred_result_label_then_completeness"
            if preferred_result_tokens
            else "most_complete_result"
        ),
        "preferred_result_tokens": list(preferred_result_tokens),
        "detected_result_count": len(result_candidates),
        "detected_interval_count": sum(
            len(item["intervals"]) for item in result_candidates
        ),
        "selected_result_index": selected["result_index"],
        "selected_result_label": selected["result_label"],
        "selected_interval_indexes": [
            interval["interval_index"] for interval in selected_intervals
        ],
        "selected_interval_point_counts": [
            len(interval["points"]) for interval in selected_intervals
        ],
        "selected_interval_numeric_x_row_counts": [
            int(interval["numeric_x_rows"]) for interval in selected_intervals
        ],
        "selected_interval_candidate_row_counts": [
            int(interval["candidate_rows"]) for interval in selected_intervals
        ],
        "selected_interval_header_rows": [
            int(interval["source_header_index"]) for interval in selected_intervals
        ],
        "selected_interval_columns": [
            {
                "interval_index": int(interval["interval_index"]),
                "header_row_index": int(interval["source_header_index"]),
                "x_unit_row_index": int(interval["x_unit_row_index"]),
                "y_unit_row_index": int(interval["y_unit_row_index"]),
                "x": {
                    "header": str(interval["x_column_header"]),
                    "column_index_zero_based": int(interval["x_column_index"]),
                    "unit": str(interval["x_unit"]),
                },
                "y": {
                    "header": str(interval["y_column_header"]),
                    "column_index_zero_based": int(interval["y_column_index"]),
                    "unit": str(interval["y_unit"]),
                },
            }
            for interval in selected_intervals
        ],
        "source_x_column_index": int(selected_intervals[0]["x_column_index"]),
        "source_x_header": str(selected_intervals[0]["x_column_header"]),
        "source_x_unit": str(selected_intervals[0]["x_unit"]),
        "source_y_column_index": int(selected_intervals[0]["y_column_index"]),
        "source_y_header": str(selected_intervals[0]["y_column_header"]),
        "source_y_unit": str(selected_intervals[0]["y_unit"]),
        "selected_point_interval_indexes": [
            int(interval["interval_index"])
            for interval in selected_intervals
            for _point in interval["points"]
        ],
        "selected_point_count": len(selected_points),
        "selected_y_coverage_fraction": round(float(selected["coverage"]), 6),
        "x_direction": x_direction,
        "candidate_results": [
            {
                "result_index": item["result_index"],
                "result_label": item["result_label"],
                "preferred_label_match": bool(item["preferred"]),
                "interval_count": len(item["intervals"]),
                "valid_point_count": len(item["points"]),
                "y_coverage_fraction": round(float(item["coverage"]), 6),
            }
            for item in result_candidates
        ],
    }
    return CurveSeriesPayload(
        sample=_sample_from_interval_metadata(raw, source.stem),
        x_label="Time",
        x_unit=str(selected_intervals[0]["x_unit"]),
        y_label=y_label,
        y_unit=str(selected_intervals[0]["y_unit"]),
        points=selected_points,
        diagnostics=diagnostics,
    )


def _read_rheology_interval_series_list(
    source: Path,
    *,
    y_candidates: tuple[str, ...],
    y_label: str,
    y_unit: str,
    preferred_result_tokens: tuple[str, ...] = (),
) -> list[CurveSeriesPayload]:
    candidates = _sweep_source_files(source)
    series_list: list[CurveSeriesPayload] = []
    errors: list[str] = []
    for candidate in candidates:
        try:
            series = _read_rheology_interval_series(
                candidate,
                y_candidates=y_candidates,
                y_label=y_label,
                y_unit=y_unit,
                preferred_result_tokens=preferred_result_tokens,
            )
            series_list.append(
                CurveSeriesPayload(
                    sample=_source_display_sample(candidate),
                    x_label=series.x_label,
                    x_unit=series.x_unit,
                    y_label=series.y_label,
                    y_unit=series.y_unit,
                    points=series.points,
                    diagnostics=series.diagnostics,
                )
            )
        except Exception as exc:
            errors.append(f"{candidate.name}: {exc}")
    if not series_list:
        detail = "; ".join(errors[:3])
        raise ValueError(
            f"No {y_label.casefold()} exports found under {source}. {detail}".strip()
        )
    if errors:
        raise ValueError(
            "Rheology interval preparation rejected one or more in-scope "
            f"source files; silent partial datasets are not allowed ({'; '.join(errors[:3])})."
        )
    return series_list
