"""Resolve auditable swelling-series identity only from selected source cells."""

from __future__ import annotations

import math
import numbers
import re
from typing import Any

import pandas as pd

from sciplot_core.foundation.text_values import clean_text as _clean_text


_FIGURE_PREFIX = re.compile(
    r"^\s*fig(?:ure)?\s*\d+\s*\([^)]+\)\s*:\s*",
    flags=re.IGNORECASE,
)


def parallel_swelling_identity(
    raw: pd.DataFrame,
    *,
    header_index: int,
    x_index: int,
) -> tuple[str, dict[str, Any]]:
    """Return display identity plus its exact condition/replicate cells."""

    condition_row = header_index - 2
    replicate_row = header_index - 1
    raw_condition, condition_column = _nearest_cell(
        raw,
        row_position=condition_row,
        column=x_index,
    )
    replicate_cell = (
        raw.iat[replicate_row, x_index]
        if 0 <= replicate_row < raw.shape[0]
        else None
    )
    condition = raw_condition
    replicate = _replicate_from_source(replicate_cell)
    if not condition or not replicate:
        raise ValueError(
            "Swelling parallel series lacks source-derived condition or "
            "replicate identity."
        )
    evidence = {
        "kind": "parallel_condition_and_replicate_cells",
        "condition": {
            "value": condition,
            "raw_cell": raw_condition,
            "row_index_zero_based": condition_row,
            "column_index_zero_based": condition_column,
            "extraction": "preserve_clean_source_text",
            "structural_prefix": _structural_prefix(raw_condition),
        },
        "replicate": {
            "value": replicate,
            "raw_cell": _clean_text(replicate_cell),
            "row_index_zero_based": replicate_row,
            "column_index_zero_based": x_index,
            "extraction": (
                "normalize_numeric_integer_cell"
                if _is_numeric_integer_cell(replicate_cell)
                else "preserve_clean_source_text"
            ),
        },
    }
    return f"{condition} replicate {replicate}", evidence


def long_swelling_identity(
    raw: pd.DataFrame,
    *,
    sample: str,
    sample_column: int,
    row_positions: list[int],
) -> dict[str, Any]:
    """Record every source row that contributes one long-form sample."""

    raw_cells = [_clean_text(raw.iat[row, sample_column]) for row in row_positions]
    if not row_positions or any(value != sample for value in raw_cells):
        raise ValueError(
            f"Swelling long-form identity evidence is inconsistent for {sample!r}."
        )
    return {
        "kind": "long_sample_column_cells",
        "sample": {
            "value": sample,
            "raw_cell": sample,
            "column_index_zero_based": sample_column,
            "row_indices_zero_based": list(row_positions),
            "row_span_zero_based": [row_positions[0], row_positions[-1]],
            "extraction": "preserve_clean_source_text",
        },
    }


def _nearest_cell(
    raw: pd.DataFrame,
    *,
    row_position: int,
    column: int,
) -> tuple[str, int]:
    if row_position < 0 or row_position >= raw.shape[0]:
        return "", column
    for candidate_column in range(column, -1, -1):
        value = _clean_text(raw.iat[row_position, candidate_column])
        if value:
            return value, candidate_column
    return "", column


def _structural_prefix(value: object) -> str:
    match = _FIGURE_PREFIX.match(_clean_text(value))
    return _clean_text(match.group(0)) if match is not None else ""


def _is_numeric_integer_cell(value: object) -> bool:
    return (
        isinstance(value, numbers.Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value).is_integer()
    )


def _replicate_from_source(value: object) -> str:
    if _is_numeric_integer_cell(value):
        return str(int(float(value)))
    return _clean_text(value)


__all__ = ["long_swelling_identity", "parallel_swelling_identity"]
