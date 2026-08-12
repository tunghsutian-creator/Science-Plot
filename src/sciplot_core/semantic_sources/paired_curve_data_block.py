"""Select the first structural data block for generic paired curve tables."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from sciplot_core.foundation.text_values import clean_text
from sciplot_core.semantic_sources.numeric_separators import (
    numeric_cell_syntax,
    selected_rows_use_decimal_comma,
)


_DISCONNECTED_BLOCK_MESSAGE = "Selected paired-curve data block is disconnected."
_MISSING_TOKENS = frozenset({"na", "n/a", "n.a.", "null", "none"})


@dataclass(frozen=True, slots=True)
class PairedCurveDataBlock:
    """Rows in one contiguous paired-data block and its numeric locale."""

    rows: tuple[int, ...]
    decimal_comma: bool


def first_paired_curve_data_block(
    raw: pd.DataFrame,
    *,
    data_start: int,
    pairs: tuple[tuple[int, int], ...],
) -> PairedCurveDataBlock:
    """Close on a blank/text row and reject any later complete numeric pair."""

    rows: list[int] = []
    closed = False
    for row in range(data_start, raw.shape[0]):
        if closed:
            if _has_complete_numeric_pair(raw, row=row, pairs=pairs):
                raise ValueError(_DISCONNECTED_BLOCK_MESSAGE)
            continue
        if _ends_block(raw, row=row, pairs=pairs):
            if rows:
                closed = True
            continue
        rows.append(row)
    evidence_rows = [
        row for row in rows if _has_complete_numeric_pair(raw, row=row, pairs=pairs)
    ]
    return PairedCurveDataBlock(
        rows=tuple(rows),
        decimal_comma=selected_rows_use_decimal_comma(
            raw,
            rows=evidence_rows,
            columns=tuple(column for pair in pairs for column in pair),
        ),
    )


def _ends_block(
    raw: pd.DataFrame,
    *,
    row: int,
    pairs: tuple[tuple[int, int], ...],
) -> bool:
    values = raw.iloc[row].tolist()
    if not any(clean_text(value) for value in values):
        return True
    selected_columns = {column for pair in pairs for column in pair}
    if any(
        column not in selected_columns
        and _is_structural_text(value)
        for column, value in enumerate(values)
    ):
        return True
    selected_kinds = tuple(
        numeric_cell_syntax(raw.iat[row, column]) for column in selected_columns
    )
    if any(kind in {"numeric_candidate", "nonfinite"} for kind in selected_kinds):
        return False
    return any(
        _is_structural_text(raw.iat[row, column]) for column in selected_columns
    )


def _has_complete_numeric_pair(
    raw: pd.DataFrame,
    *,
    row: int,
    pairs: tuple[tuple[int, int], ...],
) -> bool:
    return any(
        numeric_cell_syntax(raw.iat[row, x_index]) == "numeric_candidate"
        and numeric_cell_syntax(raw.iat[row, y_index]) == "numeric_candidate"
        for x_index, y_index in pairs
    )


def _is_structural_text(value: object) -> bool:
    if numeric_cell_syntax(value) != "nonnumeric":
        return False
    return clean_text(value).casefold() not in _MISSING_TOKENS


__all__ = ["PairedCurveDataBlock", "first_paired_curve_data_block"]
