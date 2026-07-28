"""Find semantic header roles in loosely structured source tables."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from sciplot_core.source_tables import (
    canonicalize_token,
    normalize_label,
    normalize_unit,
)


def cell_text(value: Any) -> str:
    if value is None or isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def cell_token(value: Any) -> str:
    return canonicalize_token(cell_text(value))


def looks_numeric(value: Any) -> bool:
    text = cell_text(value)
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def token_matches(token: str, accepted: set[str]) -> bool:
    if not token:
        return False
    return token in accepted or any(part and part in token for part in accepted)


def header_row_with(
    raw: pd.DataFrame,
    required: tuple[set[str], ...],
    *,
    limit: int = 12,
) -> int | None:
    for row_index in range(min(limit, raw.shape[0])):
        tokens = [cell_token(value) for value in raw.iloc[row_index].tolist()]
        if all(
            any(token_matches(token, accepted) for token in tokens)
            for accepted in required
        ):
            return row_index
    return None


def columns_matching(
    raw: pd.DataFrame,
    header_row: int,
    accepted: set[str],
) -> list[int]:
    return [
        column
        for column, value in enumerate(raw.iloc[header_row].tolist())
        if token_matches(cell_token(value), accepted)
    ]


def label_and_unit(raw_label: object) -> tuple[str, str]:
    label = cell_text(raw_label)
    unit = ""
    match = re.search(
        r"^(?P<label>.+?)\s*[\(\[](?P<unit>.+?)[\)\]]\s*$",
        label,
    )
    if match is not None:
        label = match.group("label")
        unit = match.group("unit")
    elif "_" in label:
        left, right = label.split("_", 1)
        if left and right:
            label = left
            unit = right
    return normalize_label(label), normalize_unit(unit)


def dedupe_labels(labels: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        cleaned = normalize_label(label) or label
        token = canonicalize_token(cleaned)
        if cleaned and token not in seen:
            seen.add(token)
            result.append(cleaned)
    return tuple(result)


__all__ = [
    "cell_text",
    "cell_token",
    "columns_matching",
    "dedupe_labels",
    "header_row_with",
    "label_and_unit",
    "looks_numeric",
    "token_matches",
]
