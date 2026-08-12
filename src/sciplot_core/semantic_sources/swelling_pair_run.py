"""Select and materialize the first run for one labeled swelling pair."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from sciplot_core.foundation.text_values import clean_text as _clean_text
from sciplot_core.semantic_sources.numeric_separators import (
    numeric_cell_syntax,
    selected_rows_use_decimal_comma,
)
from sciplot_core.semantic_sources.swelling_table_selection import (
    _LabeledSwellingTable,
    _is_explicit_swelling_unit_row,
)
from sciplot_core.semantic_sources.table_scanning import _float


_SELECTION_POLICY = "first_labeled_pair_run_with_isolated_blank_bridge"


def first_swelling_pair_run(
    table: _LabeledSwellingTable,
    *,
    x_index: int,
    y_index: int,
    factor: float,
) -> tuple[tuple[tuple[float, float], ...], dict[str, Any], bool]:
    """Choose rows structurally, then infer locale only from retained rows."""

    retained_rows, source_block = _select_pair_rows(
        table,
        x_index=x_index,
        y_index=y_index,
    )
    decimal_comma = selected_rows_use_decimal_comma(
        table.raw,
        rows=retained_rows,
        columns=(x_index, y_index),
    )
    points = tuple(
        _materialized_point(
            table.raw,
            row=row,
            x_index=x_index,
            y_index=y_index,
            factor=factor,
            decimal_comma=decimal_comma,
        )
        for row in retained_rows
    )
    return points, source_block, decimal_comma


def finite_swelling_pair(
    raw: pd.DataFrame,
    row: int,
    x: int,
    y: int,
    *,
    decimal_comma: bool,
) -> tuple[float, float] | None:
    x_value = _float(raw.iat[row, x], decimal_comma=decimal_comma)
    y_value = _float(raw.iat[row, y], decimal_comma=decimal_comma)
    if x_value is None or y_value is None:
        return None
    if not (math.isfinite(x_value) and math.isfinite(y_value)):
        return None
    return x_value, y_value


def swelling_pair_row_kind(raw: pd.DataFrame, row: int, x: int, y: int) -> str:
    x_kind = numeric_cell_syntax(raw.iat[row, x])
    y_kind = numeric_cell_syntax(raw.iat[row, y])
    if x_kind == "empty" and y_kind == "empty":
        return "empty"
    if "empty" in {x_kind, y_kind}:
        return "partial"
    if "nonfinite" in {x_kind, y_kind}:
        return "nonfinite"
    if x_kind == y_kind == "numeric_candidate":
        return "finite"
    return "nonnumeric"


def _select_pair_rows(
    table: _LabeledSwellingTable,
    *,
    x_index: int,
    y_index: int,
) -> tuple[list[int], dict[str, Any]]:
    raw = table.raw
    first = _measurement_start(table, x_index=x_index, y_index=y_index)
    retained_rows: list[int] = []
    bridged_rows: list[int] = []
    stop = raw.shape[0]
    termination = "end_of_source"
    row = first
    while row < raw.shape[0]:
        kind = swelling_pair_row_kind(raw, row, x_index, y_index)
        if kind == "finite":
            retained_rows.append(row)
            row += 1
            continue
        if _isolated_formatting_row(
            table,
            row=row,
            x_index=x_index,
            y_index=y_index,
        ):
            bridged_rows.append(row)
            row += 1
            continue
        stop = row
        termination = (
            "structural_content_row"
            if kind == "empty"
            and _row_has_unregistered_content(table, row=row)
            else f"{kind}_pair"
        )
        break
    exclusions = {
        reason: sum(
            swelling_pair_row_kind(raw, later, x_index, y_index) == reason
            for later in range(stop, raw.shape[0])
        )
        for reason in ("finite", "partial", "nonnumeric", "nonfinite")
    }
    excluded_rows = [
        later
        for later in range(stop, raw.shape[0])
        if swelling_pair_row_kind(raw, later, x_index, y_index) == "finite"
    ]
    source_block: dict[str, Any] = {
        "selection_policy": _SELECTION_POLICY,
        "source_header_row": table.header_index + 1,
        "source_data_row_start": retained_rows[0] + 1,
        "source_data_row_end": retained_rows[-1] + 1,
        "retained_point_count": len(retained_rows),
        "isolated_blank_bridge_count": len(bridged_rows),
        "retained_source_rows_zero_based": list(retained_rows),
        "selection_stop_row_zero_based": stop,
        "termination_reason": termination,
        "candidate_pair_row_count": len(retained_rows) + sum(exclusions.values()),
        "excluded_disconnected_point_count": len(excluded_rows),
        "excluded_partial_pair_count": exclusions["partial"],
        "excluded_nonnumeric_pair_count": exclusions["nonnumeric"],
        "excluded_nonfinite_pair_count": exclusions["nonfinite"],
        "excluded_disconnected_rows": raw.shape[0] - stop,
    }
    if excluded_rows:
        source_block["excluded_disconnected_source_row_span"] = [
            excluded_rows[0] + 1,
            excluded_rows[-1] + 1,
        ]
    return retained_rows, source_block


def _measurement_start(
    table: _LabeledSwellingTable,
    *,
    x_index: int,
    y_index: int,
) -> int:
    raw = table.raw
    first = table.header_index + 1
    if first >= raw.shape[0]:
        raise ValueError(f"Swelling table {table.name!r} has no measurement rows.")
    kind = swelling_pair_row_kind(raw, first, x_index, y_index)
    if kind == "finite":
        return first
    headers = raw.iloc[table.header_index].tolist()
    if _is_explicit_swelling_unit_row(
        x_header=headers[x_index],
        y_header=headers[y_index],
        x_cell=raw.iat[first, x_index],
        y_cell=raw.iat[first, y_index],
    ):
        first += 1
        if first < raw.shape[0] and swelling_pair_row_kind(
            raw, first, x_index, y_index
        ) == "finite":
            return first
        kind = (
            swelling_pair_row_kind(raw, first, x_index, y_index)
            if first < raw.shape[0]
            else "missing"
        )
    raise ValueError(
        f"Swelling table {table.name!r} starts the selected measurement pair "
        f"with {kind} cells; only one explicit adjacent unit row may precede "
        "the first finite pair."
    )


def _isolated_formatting_row(
    table: _LabeledSwellingTable,
    *,
    row: int,
    x_index: int,
    y_index: int,
) -> bool:
    return (
        swelling_pair_row_kind(table.raw, row, x_index, y_index) == "empty"
        and not _row_has_unregistered_content(table, row=row)
        and all(
            swelling_pair_row_kind(table.raw, row, pair_x, pair_y)
            in {"empty", "finite"}
            for pair_x, pair_y in table.pairs
        )
        and row + 1 < table.raw.shape[0]
        and swelling_pair_row_kind(table.raw, row + 1, x_index, y_index) == "finite"
    )


def _row_has_unregistered_content(
    table: _LabeledSwellingTable,
    *,
    row: int,
) -> bool:
    registered = {column for pair in table.pairs for column in pair}
    return any(
        column not in registered and _clean_text(value)
        for column, value in enumerate(table.raw.iloc[row].tolist())
    )


def _materialized_point(
    raw: pd.DataFrame,
    *,
    row: int,
    x_index: int,
    y_index: int,
    factor: float,
    decimal_comma: bool,
) -> tuple[float, float]:
    pair = finite_swelling_pair(
        raw,
        row,
        x_index,
        y_index,
        decimal_comma=decimal_comma,
    )
    if pair is None:
        raise RuntimeError("Selected swelling row failed numeric materialization.")
    return pair[0] * factor, pair[1]


__all__ = [
    "finite_swelling_pair",
    "first_swelling_pair_run",
    "swelling_pair_row_kind",
]
