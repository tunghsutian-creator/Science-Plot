"""Infer one numeric separator only from parser-selected scientific columns."""

from __future__ import annotations

import re
from typing import Literal

import pandas as pd


SeparatorEvidence = Literal["point", "comma", "ambiguous", "malformed"]

_NUMBER_TOKEN = re.compile(
    r"^[+-]?(?P<mantissa>(?:\d+(?:[.,]\d+)*|[.,]\d+))"
    r"(?:[Ee][+-]?\d+)?$"
)


def selected_columns_use_decimal_comma(
    raw: pd.DataFrame,
    *,
    start_row: int,
    columns: tuple[int, ...],
) -> bool:
    """Resolve selected numeric lexemes without point-count voting."""

    evidence: set[str] = set()
    ambiguous = False
    selected_columns = tuple(dict.fromkeys(columns))
    for row_index in range(start_row, raw.shape[0]):
        for column in selected_columns:
            kind = _separator_evidence(raw.iat[row_index, column])
            if kind in {"point", "comma"}:
                evidence.add(kind)
            elif kind == "ambiguous":
                ambiguous = True
            elif kind == "malformed":
                raise ValueError(
                    "Selected rheology numeric columns contain malformed "
                    "separator grouping."
                )
    if len(evidence) > 1:
        raise ValueError(
            "Selected rheology numeric columns mix point-decimal and "
            "comma-decimal values."
        )
    if ambiguous and not evidence:
        raise ValueError(
            "Selected rheology numeric columns contain ambiguous "
            "`12,345`-shaped values without decimal-separator evidence."
        )
    return evidence == {"comma"}


def _separator_evidence(value: object) -> SeparatorEvidence | None:
    if not isinstance(value, str):
        return None
    compact = (
        value.strip()
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
    )
    match = _NUMBER_TOKEN.fullmatch(compact)
    if match is None:
        return None
    mantissa = match.group("mantissa")
    if "," in mantissa and "." in mantissa:
        return "comma" if mantissa.rfind(",") > mantissa.rfind(".") else "point"
    if "," not in mantissa:
        return "malformed" if mantissa.count(".") > 1 else (
            "point" if "." in mantissa else None
        )
    groups = mantissa.split(",")
    if len(groups) > 2:
        return "point" if all(len(group) == 3 for group in groups[1:]) else "malformed"
    integer, fractional = groups
    if len(fractional) == 3 and integer.lstrip("0"):
        return "ambiguous"
    return "comma"


__all__ = ["selected_columns_use_decimal_comma"]
