"""Extract source-ordered swelling curves from one uniquely labeled table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.text_values import clean_text as _clean_text
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.swelling_identity import (
    long_swelling_identity,
    parallel_swelling_identity,
)
from sciplot_core.semantic_sources.swelling_pair_run import (
    finite_swelling_pair,
    first_swelling_pair_run,
    swelling_pair_row_kind,
)
from sciplot_core.semantic_sources.swelling_table_selection import (
    _LabeledSwellingTable,
    _matching_tables,
    _swelling_response_unit_evidence,
    _swelling_time_conversion,
)
from sciplot_core.semantic_sources.table_source_files import resolve_single_table_source


def _parallel_series(
    source: Path,
    table: _LabeledSwellingTable,
) -> list[CurveSeriesPayload]:
    headers = table.raw.iloc[table.header_index].tolist()
    series_list: list[CurveSeriesPayload] = []
    for x_index, y_index in table.pairs:
        adjacent = (
            table.raw.iat[table.header_index + 1, x_index]
            if table.header_index + 1 < table.raw.shape[0]
            else None
        )
        source_unit, factor = _swelling_time_conversion(headers[x_index], adjacent)
        points, source_block, decimal_comma = first_swelling_pair_run(
            table,
            x_index=x_index,
            y_index=y_index,
            factor=factor,
        )
        sample, source_identity = parallel_swelling_identity(
            table.raw,
            header_index=table.header_index,
            x_index=x_index,
        )
        if int(source_block["excluded_nonfinite_pair_count"]):
            raise ValueError(
                f"Swelling series {sample!r} contains "
                "nonfinite selected values."
            )
        series_list.append(
            CurveSeriesPayload(
                sample=sample,
                x_label="Time",
                x_unit="h",
                y_label="Swelling ratio",
                y_unit="1",
                points=points,
                diagnostics=_series_diagnostics(
                    source,
                    table,
                    x_index=x_index,
                    y_index=y_index,
                    source_unit=source_unit,
                    factor=factor,
                    source_block=source_block,
                    source_identity=source_identity,
                    decimal_comma=decimal_comma,
                ),
            )
        )
    return series_list


def _series_diagnostics(
    source: Path,
    table: _LabeledSwellingTable,
    *,
    x_index: int,
    y_index: int,
    source_unit: str,
    factor: float,
    source_block: dict[str, Any],
    source_identity: dict[str, Any],
    decimal_comma: bool,
) -> dict[str, Any]:
    headers = table.raw.iloc[table.header_index].tolist()
    adjacent_y = (
        table.raw.iat[table.header_index + 1, y_index]
        if table.header_index + 1 < table.raw.shape[0]
        and finite_swelling_pair(
            table.raw,
            table.header_index + 1,
            x_index,
            y_index,
            decimal_comma=decimal_comma,
        )
        is None
        else None
    )
    return {
        "source_file": str(source),
        "source_table": table.name,
        "source_header_row_index": int(table.raw.index[table.header_index]),
        "source_columns": {
            "x": _clean_text(headers[x_index]),
            "y": _clean_text(headers[y_index]),
        },
        "source_column_indices": {"x": x_index, "y": y_index},
        "time_conversion": {
            "source_unit": source_unit,
            "canonical_unit": "h",
            "factor": factor,
        },
        "response_unit_evidence": _swelling_response_unit_evidence(
            headers[y_index], adjacent_y
        ),
        "numeric_separator_evidence": {
            "selected_columns": [x_index, y_index],
            "decimal_separator": "," if decimal_comma else ".",
            "decimal_comma": decimal_comma,
            "method": (
                "selected_columns_lexical_evidence_with_native_numeric_passthrough"
            ),
        },
        "source_identity": source_identity,
        "source_block": source_block,
    }


def _long_table_series(
    source: Path,
    table: _LabeledSwellingTable,
) -> list[CurveSeriesPayload]:
    if len(table.pairs) != 1 or table.sample_column is None:
        return _parallel_series(source, table)
    x_index, y_index = table.pairs[0]
    headers = table.raw.iloc[table.header_index].tolist()
    source_unit, factor = _swelling_time_conversion(
        headers[x_index],
        table.raw.iat[table.header_index + 1, x_index]
        if table.header_index + 1 < table.raw.shape[0]
        else None,
    )
    _all_points, source_block, decimal_comma = first_swelling_pair_run(
        table,
        x_index=x_index,
        y_index=y_index,
        factor=factor,
    )
    retained_start = int(source_block["source_data_row_start"]) - 1
    retained_end = int(source_block["source_data_row_end"]) - 1
    grouped: dict[str, list[tuple[float, float]]] = {}
    grouped_rows: dict[str, list[int]] = {}
    for row in range(retained_start, retained_end + 1):
        pair = finite_swelling_pair(
            table.raw,
            row,
            x_index,
            y_index,
            decimal_comma=decimal_comma,
        )
        if pair is None:
            continue
        sample = _clean_text(table.raw.iat[row, table.sample_column])
        if not sample:
            raise ValueError(
                f"Swelling long table {table.name!r} has a finite pair without "
                "source sample identity."
            )
        grouped.setdefault(sample, []).append((pair[0] * factor, pair[1]))
        grouped_rows.setdefault(sample, []).append(row)
    _validate_long_disconnected_identities(
        table,
        global_block=source_block,
        known_samples=frozenset(grouped),
        sample_column=table.sample_column,
        x_index=x_index,
        y_index=y_index,
    )
    return [
        CurveSeriesPayload(
            sample=sample,
            x_label="Time",
            x_unit="h",
            y_label="Swelling ratio",
            y_unit="1",
            points=tuple(sample_points),
            diagnostics=_series_diagnostics(
                source,
                table,
                x_index=x_index,
                y_index=y_index,
                source_unit=source_unit,
                factor=factor,
                source_block=_long_sample_source_block(
                    table,
                    global_block=source_block,
                    sample=sample,
                    sample_column=table.sample_column,
                    retained_rows=grouped_rows[sample],
                    x_index=x_index,
                    y_index=y_index,
                ),
                source_identity=long_swelling_identity(
                    table.raw,
                    sample=sample,
                    sample_column=table.sample_column,
                    row_positions=grouped_rows[sample],
                ),
                decimal_comma=decimal_comma,
            ),
        )
        for sample, sample_points in grouped.items()
    ]


def _long_sample_source_block(
    table: _LabeledSwellingTable,
    *,
    global_block: dict[str, Any],
    sample: str,
    sample_column: int,
    retained_rows: list[int],
    x_index: int,
    y_index: int,
) -> dict[str, Any]:
    stop = int(global_block["selection_stop_row_zero_based"])
    exclusions = {key: 0 for key in ("finite", "partial", "nonnumeric", "nonfinite")}
    excluded_rows: list[int] = []
    for row in range(stop, table.raw.shape[0]):
        kind = swelling_pair_row_kind(table.raw, row, x_index, y_index)
        row_sample = _clean_text(table.raw.iat[row, sample_column])
        if kind == "empty" and not row_sample:
            continue
        if not row_sample:
            raise ValueError(
                f"Swelling long table {table.name!r} has disconnected selected "
                "content without source sample identity."
            )
        if row_sample != sample:
            continue
        if kind == "empty":
            kind = "partial"
        exclusions[kind] += 1
        excluded_rows.append(row)
    return {
        "selection_policy": global_block["selection_policy"],
        "sample_filter": sample,
        "source_header_row": global_block["source_header_row"],
        "source_data_row_start": retained_rows[0] + 1,
        "source_data_row_end": retained_rows[-1] + 1,
        "retained_source_rows_zero_based": list(retained_rows),
        "retained_point_count": len(retained_rows),
        "isolated_blank_bridge_count": 0,
        "global_isolated_blank_bridge_count": global_block[
            "isolated_blank_bridge_count"
        ],
        "selection_stop_row_zero_based": stop,
        "termination_reason": global_block["termination_reason"],
        "candidate_pair_row_count": len(retained_rows) + sum(exclusions.values()),
        "excluded_disconnected_point_count": exclusions["finite"],
        "excluded_partial_pair_count": exclusions["partial"],
        "excluded_nonnumeric_pair_count": exclusions["nonnumeric"],
        "excluded_nonfinite_pair_count": exclusions["nonfinite"],
        "excluded_disconnected_rows": len(excluded_rows),
        **(
            {
                "excluded_disconnected_source_row_span": [
                    excluded_rows[0] + 1,
                    excluded_rows[-1] + 1,
                ]
            }
            if excluded_rows
            else {}
        ),
    }


def _validate_long_disconnected_identities(
    table: _LabeledSwellingTable,
    *,
    global_block: dict[str, Any],
    known_samples: frozenset[str],
    sample_column: int,
    x_index: int,
    y_index: int,
) -> None:
    stop = int(global_block["selection_stop_row_zero_based"])
    for row in range(stop, table.raw.shape[0]):
        kind = swelling_pair_row_kind(table.raw, row, x_index, y_index)
        row_sample = _clean_text(table.raw.iat[row, sample_column])
        if kind == "empty" and not row_sample:
            continue
        if not row_sample or row_sample not in known_samples:
            raise ValueError(
                f"Swelling long table {table.name!r} has disconnected selected "
                "content without a retained source sample identity."
            )


def _read_swelling_series_list(source: Path) -> list[CurveSeriesPayload]:
    """Resolve one labeled table and preserve each pair's first finite run."""

    resolved = resolve_single_table_source(source, context="swelling transform")
    matches = _matching_tables(resolved)
    if len(matches) != 1:
        raise ValueError(
            "Swelling transform requires exactly one matching labeled worksheet "
            f"in {resolved}; found {len(matches)}."
        )
    return _long_table_series(resolved, matches[0])


__all__ = ["_read_swelling_series_list"]
